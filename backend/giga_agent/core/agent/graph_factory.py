"""Agent factory for creating agents with middleware support."""

from __future__ import annotations

import mimetypes
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Coroutine, Literal, cast

from langchain.agents.middleware.types import (
    ModelRequest,
    ModelResponse,
    ResponseT,
    StateT_co,
    _InputAgentState,
    _OutputAgentState,
)
from langchain.tools.tool_node import (
    ToolCallRequest,
)
from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langgraph._internal._runnable import RunnableCallable
from langgraph.constants import END, START
from langgraph.graph.state import StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Command, Send
from langgraph.typing import ContextT

from giga_agent.conf import (
    GIGA_AGENT_ENABLE_MULTI_TOOL_USE,
    GIGA_AGENT_ENABLE_MULTI_TOOL_USE_PROVIDERS,
    GIGA_AGENT_ENABLE_THINK_TOOL,
    GIGA_AGENT_ENABLE_THINK_TOOL_PROVIDERS,
)
from giga_agent.core.agent.anti_loop import detect_loop
from giga_agent.core.agent.connectors.sources import collect_sources
from giga_agent.core.agent.connectors.tools import (
    connector_call_tool,
    connector_get_info,
)
from giga_agent.core.agent.few_shots_single import FEW_SHOT_EXAMPLES_SINGLE
from giga_agent.core.agent.middleware import AgentMiddleware
from giga_agent.core.agent.multi_tool_use import (
    collapse_tool_messages,
    expand_multi_tool_use,
)
from giga_agent.core.agent.prompt import BASE_PROMPT, SCHEDULED_RUN_PROMPT
from giga_agent.core.agent.runtime_resolver import RuntimeResolver
from giga_agent.core.agent.think import (
    THINK_VIA_FAST_MODEL,
    _count_trailing_think_tool_pairs,
    collapse_think_hops,
    is_single_think_call,
    process_think_via_fast_model,
    resolve_bound_tool_choice,
)
from giga_agent.core.agent.tool_node import ToolCallsWithContext, ToolNode
from giga_agent.core.agent.tools import multi_tool_use, think
from giga_agent.core.db import get_session_factory
from giga_agent.core.logging import get_logger
from giga_agent.utils.mcp import transform_tool

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from langchain.agents.middleware.types import ToolCallRequest
    from langgraph.cache.base import BaseCache
    from langgraph.graph.state import CompiledStateGraph
    from langgraph.store.base import BaseStore
    from langgraph.types import Checkpointer

    from giga_agent.core.agent.base import BaseAgent
from giga_agent.core.agent.types import AgentState, Context
from giga_agent.core.agent.utils import merge_state, reduce_updates

logger = get_logger(__name__)

# Safety cap on consecutive think hops. Normally forced think is bounded by
# MAX_FORCED_THINK_FOLLOWUPS, so reaching this means a runaway loop.
MAX_THINK_HOPS = 6

# User-facing message emitted when an anti-loop detector breaks the run.
ANTI_LOOP_STOP_MESSAGE = (
    "Похоже, я зациклился и не могу продвинуться дальше по этой задаче — "
    "повторяю одни и те же действия без прогресса. Останавливаюсь, чтобы не "
    "тратить шаги впустую. Уточни, пожалуйста, запрос или подскажи, как лучше "
    "действовать, и я попробую снова."
)


def _is_feature_enabled_for_provider(
    enabled: bool,
    allowed_providers: list[str],
    llm_type: str,
) -> bool:
    if not enabled:
        return False
    return llm_type.lower() in {p.lower() for p in allowed_providers}


def _generate_user_info(state: AgentState) -> str:
    # TODO: Вынести язык пользователя в явные пользовательские настройки
    language = "ru"
    language_prompt = ""
    if not language.startswith("ru"):
        language_prompt = f"\nВыбранный язык пользователя: {language}\n"
    # Current time in the configured/system timezone so "in N minutes" the agent
    # computes matches how scheduled times are interpreted (see scheduler).
    from giga_agent.scheduled.cron import default_tz

    now = datetime.now(default_tz())
    return (
        f"<user_info>\n"
        f"Текущая дата: {now.strftime('%d.%m.%Y %H:%M')} ({now.strftime('%Z') or 'local'})"
        f"{language_prompt}</user_info>"
    )


def _build_file_prompt(last_message: AnyMessage) -> str:
    files = getattr(last_message, "additional_kwargs", {}).get("files", [])
    file_prompt_items = []
    for file in files:
        path = file.get("path") or file.get("sandbox_path")
        path_str = path if isinstance(path, str) else str(path)

        file_type = str(file.get("file_type", "")).strip().lower()
        guessed_mime, _ = mimetypes.guess_type(path_str)
        is_image = file_type == "image" or (
            isinstance(guessed_mime, str) and guessed_mime.startswith("image/")
        )

        item = f"""Файл загружен в виртуальное окружение по пути: '{path_str}'"""
        if is_image:
            image_path = file.get("image_path") or path_str
            item += (
                "\nФайл является изображением его можно отобразить с помощью: "
                f"'![алт-текст](attachment:{image_path})'."
            )
        file_prompt_items.append(item)

    if not file_prompt_items:
        return ""
    return "<files_data>" + "\n----\n".join(file_prompt_items) + "</files_data>"


def _build_selected_prompt(last_message: AnyMessage) -> str:
    selected = getattr(last_message, "additional_kwargs", {}).get("selected", {})
    if not selected:
        return ""

    selected_items = [
        f"![{value}](attachment:{key})" for key, value in selected.items()
    ]
    return "Пользователь указал на следующие вложения: \n" + "\n".join(selected_items)


def _resolve_channel_prompt(config: RunnableConfig | None) -> str:
    if not isinstance(config, dict):
        return ""

    metadata = config.get("metadata", {}) or {}
    channel_type = metadata.get("channel")
    if not isinstance(channel_type, str) or not channel_type.strip():
        return ""

    import giga_agent.channels  # noqa: F401
    from giga_agent.channels.registry import ChannelRegistry

    normalized_channel_type = channel_type.strip().lower()
    if not ChannelRegistry.is_registered(normalized_channel_type):
        return ""

    return ChannelRegistry.get(normalized_channel_type).get_prompt()


def _resolve_scheduled_prompt(config: RunnableConfig | None) -> str:
    """Extra system instructions for autonomous scheduled-task runs.

    Gated on ``metadata.is_scheduled`` (set on the thread in
    ``scheduled/runner.py``). Tells the model there is no live user, that the
    system delivers the result itself, and that its final tool-call-free
    message is the only thing the user receives — so all artifacts must be
    gathered there.
    """
    if not isinstance(config, dict):
        return ""
    metadata = config.get("metadata", {}) or {}
    if not metadata.get("is_scheduled"):
        return ""
    return SCHEDULED_RUN_PROMPT


def _chain_async_tool_call_wrappers(
    wrappers: Sequence[
        Callable[
            [
                ToolCallRequest,
                Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
            ],
            Awaitable[ToolMessage | Command[Any]],
        ]
    ],
) -> (
    Callable[
        [
            ToolCallRequest,
            Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
        ],
        Awaitable[ToolMessage | Command[Any]],
    ]
    | None
):
    if not wrappers:
        return None

    if len(wrappers) == 1:
        return wrappers[0]

    def compose_two(
        outer: Callable[
            [
                ToolCallRequest,
                Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
            ],
            Awaitable[ToolMessage | Command[Any]],
        ],
        inner: Callable[
            [
                ToolCallRequest,
                Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
            ],
            Awaitable[ToolMessage | Command[Any]],
        ],
    ) -> Callable[
        [
            ToolCallRequest,
            Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
        ],
        Awaitable[ToolMessage | Command[Any]],
    ]:
        """
        Compose two async wrappers where outer wraps inner. ковырять
        """

        async def composed(
            request: ToolCallRequest,
            execute: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
        ) -> ToolMessage | Command[Any]:
            # Create an async callable that invokes inner with the original execute
            async def call_inner(req: ToolCallRequest) -> ToolMessage | Command[Any]:
                return await inner(req, execute)

            # Outer can call call_inner multiple times
            return await outer(request, call_inner)

        return composed

    # Chain all wrappers: first -> second -> ... -> last
    result = wrappers[-1]
    for wrapper in reversed(wrappers[:-1]):
        result = compose_two(wrapper, result)

    return result


def _normalize_to_model_response(result: ModelResponse | AIMessage) -> ModelResponse:
    """Normalize middleware return value to ModelResponse."""
    if isinstance(result, AIMessage):
        return ModelResponse(result=[result], structured_response=None)
    return result


def _fetch_last_ai_and_tool_messages(
    messages: list[AnyMessage],
) -> tuple[AIMessage | None, list[ToolMessage]]:
    """Return the last AI message and any subsequent tool messages.

    Args:
        messages: List of messages to search through.

    Returns:
        A tuple of (last_ai_message, tool_messages). If no AIMessage is found,
        returns (None, []). Callers must handle the None case appropriately.
    """
    for i in range(len(messages) - 1, -1, -1):
        if isinstance(messages[i], AIMessage):
            last_ai_message = cast("AIMessage", messages[i])
            tool_messages = [m for m in messages[i + 1 :] if isinstance(m, ToolMessage)]
            return last_ai_message, tool_messages

    return None, []


def _make_model_to_tools_edge(
    *,
    model_destination: str,
    end_destination: str,
) -> Callable[[dict[str, Any]], str | list[Send] | None]:
    def model_to_tools(
        state: dict[str, Any],
    ) -> str | list[Send] | None:

        last_ai_message, tool_messages = _fetch_last_ai_and_tool_messages(
            state["messages"]
        )

        # 1. if no AIMessage exists (e.g., messages were cleared), exit the loop
        if last_ai_message is None:
            return end_destination

        tool_message_ids = [m.tool_call_id for m in tool_messages]

        # 2. If the model hasn't called any tools, exit the loop
        # this is the classic exit condition for an agent loop
        if len(last_ai_message.tool_calls) == 0:
            return end_destination

        pending_tool_calls = [
            c for c in last_ai_message.tool_calls if c["id"] not in tool_message_ids
        ]

        # 3. If there are pending tool calls, jump to the tool node
        if pending_tool_calls:
            return [
                Send(
                    "tools",
                    ToolCallsWithContext(
                        __type="tool_calls_with_context",
                        tool_calls=pending_tool_calls,
                        state=state,
                    ),
                )
            ]

        # 4. If there is a structured response, exit the loop
        if "structured_response" in state:
            return end_destination

        # 5. AIMessage has tool calls, but there are no pending tool calls which suggests
        # the injection of artificial tool messages. Jump to the model node
        return model_destination

    return model_to_tools


def _chain_async_model_call_handlers(
    handlers: Sequence[
        Callable[
            [ModelRequest, Callable[[ModelRequest], Awaitable[ModelResponse]]],
            Awaitable[ModelResponse | AIMessage],
        ]
    ],
) -> (
    Callable[
        [ModelRequest, Callable[[ModelRequest], Awaitable[ModelResponse]]],
        Awaitable[ModelResponse],
    ]
    | None
):
    """
    Compose multiple async `wrap_model_call` handlers into single middleware stack.

    Args:
        handlers: List of async handlers.

            First handler wraps all others.

    Returns:
        Composed async handler, or `None` if handlers empty.
    """
    if not handlers:
        return None

    if len(handlers) == 1:
        # Single handler - wrap to normalize output
        single_handler = handlers[0]

        async def normalized_single(
            request: ModelRequest,
            handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
        ) -> ModelResponse:
            result = await single_handler(request, handler)
            return _normalize_to_model_response(result)

        return normalized_single

    def compose_two(
        outer: Callable[
            [ModelRequest, Callable[[ModelRequest], Awaitable[ModelResponse]]],
            Awaitable[ModelResponse | AIMessage],
        ],
        inner: Callable[
            [ModelRequest, Callable[[ModelRequest], Awaitable[ModelResponse]]],
            Awaitable[ModelResponse | AIMessage],
        ],
    ) -> Callable[
        [ModelRequest, Callable[[ModelRequest], Awaitable[ModelResponse]]],
        Awaitable[ModelResponse],
    ]:
        """Compose two async handlers where outer wraps inner."""

        async def composed(
            request: ModelRequest,
            handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
        ) -> ModelResponse:
            # Create a wrapper that calls inner with the base handler and normalizes
            async def inner_handler(req: ModelRequest) -> ModelResponse:
                inner_result = await inner(req, handler)
                return _normalize_to_model_response(inner_result)

            # Call outer with the wrapped inner as its handler and normalize
            outer_result = await outer(request, inner_handler)
            return _normalize_to_model_response(outer_result)

        return composed

    # Compose right-to-left: outer(inner(innermost(handler)))
    result = handlers[-1]
    for handler in reversed(handlers[:-1]):
        result = compose_two(handler, result)

    # Wrap to ensure final return type is exactly ModelResponse
    async def final_normalized(
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        # result here is typed as returning
        # ModelResponse | AIMessage but compose_two normalizes
        final_result = await result(request, handler)
        return _normalize_to_model_response(final_result)

    return final_normalized


def create_graph(
    agent: BaseAgent,
    tools: Sequence[BaseTool | Callable | dict[str, Any]] | None = None,
    *,
    system_prompt: str | SystemMessage | None = BASE_PROMPT,
    middleware: Sequence[AgentMiddleware[StateT_co, ContextT]] = (),
    checkpointer: Checkpointer | None = None,
    store: BaseStore | None = None,
    debug: bool = False,
    name: str | None = None,
    cache: BaseCache | None = None,
) -> CompiledStateGraph[AgentState, Context]:
    """Creates an agent graph that calls tools in a loop until a stopping condition is met.

    For more details on using `create_agent`,
    visit the [Agents](https://docs.langchain.com/oss/python/langchain/agents) docs.
    """
    # Handle tools being None or empty
    if tools is None:
        tools = []

    middleware_tools = [t for m in middleware for t in getattr(m, "tools", [])]

    # Collect middleware with wrap_tool_call or awrap_tool_call hooks
    # Include middleware with either implementation to ensure NotImplementedError is raised
    # when middleware doesn't support the execution path
    middleware_w_wrap_tool_call = [
        m
        for m in middleware
        if m.__class__.wrap_tool_call is not AgentMiddleware.wrap_tool_call
    ]

    # Chain all wrap_tool_call handlers into a single composed handler
    wrap_tool_call_wrapper = None
    if middleware_w_wrap_tool_call:
        wrappers = [m.wrap_tool_call for m in middleware_w_wrap_tool_call]
        wrap_tool_call_wrapper = _chain_async_tool_call_wrappers(wrappers)

    # Extract built-in provider tools (dict format) and regular tools (BaseTool/callables)
    built_in_tools = [t for t in tools if isinstance(t, dict)]
    regular_tools = [t for t in tools if not isinstance(t, dict)]

    builtin_tools: list[BaseTool] = [connector_call_tool, connector_get_info]
    if GIGA_AGENT_ENABLE_THINK_TOOL:
        builtin_tools.append(think)
    if GIGA_AGENT_ENABLE_MULTI_TOOL_USE:
        builtin_tools.append(multi_tool_use)

    available_tools = builtin_tools + middleware_tools + regular_tools

    # Only create ToolNode if we have client-side tools
    tool_node = ToolNode(
        tools=available_tools,
        wrap_tool_call=wrap_tool_call_wrapper,
        agent=agent,
    )

    # validate middleware
    if len({m.name for m in middleware}) != len(middleware):
        msg = "Please remove duplicate middleware instances."
        raise AssertionError(msg)
    # Collect middleware with wrap_model_call or awrap_model_call hooks
    # Include middleware with either implementation to ensure NotImplementedError is raised
    # when middleware doesn't support the execution path
    middleware_w_wrap_model_call = [
        m
        for m in middleware
        if m.__class__.wrap_model_call is not AgentMiddleware.wrap_model_call
    ]

    # Compose wrap_model_call handlers into a single middleware stack (sync)
    wrap_model_call_handler = None
    if middleware_w_wrap_model_call:
        async_handlers = [m.wrap_model_call for m in middleware_w_wrap_model_call]
        wrap_model_call_handler = _chain_async_model_call_handlers(async_handlers)

    # create graph, add nodes
    graph: StateGraph[
        AgentState, Context, _InputAgentState, _OutputAgentState[ResponseT]
    ] = StateGraph(
        state_schema=AgentState,
        context_schema=Context,
    )

    async def _execute_model_async(request: ModelRequest) -> ModelResponse:
        """Execute model asynchronously and return response.

        This is the core async model execution logic wrapped by `wrap_model_call`
        handlers.

        Raises any exceptions that occur during model invocation.
        """
        model_ = request.model.bind(**request.model_settings)
        messages = request.messages
        if request.system_message:
            messages = [request.system_message, *messages]

        output = await model_.with_retry().ainvoke(messages)
        if name:
            output.name = name
        output.additional_kwargs.pop("function_call", None)
        output.additional_kwargs["rendered"] = True
        for call in output.tool_calls:
            call.setdefault("id", str(uuid.uuid4()))

        return ModelResponse(
            result=[output],
        )

    async def amodel_node(
        state: AgentState, runtime: Runtime[ContextT], config
    ) -> dict[str, Any]:
        """Async model request handler with sequential middleware processing."""
        # Anti-loop guard: if the agent is stuck (repeating a call, oscillating,
        # over the step budget, or failing the same tool), stop the run with a
        # terminal assistant message instead of invoking the model again. The
        # message has no tool calls, so _make_model_to_tools_edge routes it to
        # the end of the graph.
        loop_reason = detect_loop(state["messages"])
        if loop_reason:
            logger.warning("Anti-loop triggered, stopping run: %s", loop_reason)
            stop_message = AIMessage(content=ANTI_LOOP_STOP_MESSAGE)
            stop_message.additional_kwargs["rendered"] = True
            if name:
                stop_message.name = name
            return {"messages": [stop_message]}

        resolver = await RuntimeResolver.create(config)
        resolver.inject(config)

        user = resolver.user

        llm_runtime = await resolver.get_llm_runtime()
        llm = await llm_runtime.get_llm()

        llm_type = llm_runtime.get_llm_type()
        think_enabled = _is_feature_enabled_for_provider(
            GIGA_AGENT_ENABLE_THINK_TOOL,
            GIGA_AGENT_ENABLE_THINK_TOOL_PROVIDERS,
            llm_type,
        )
        multi_tool_use_enabled = _is_feature_enabled_for_provider(
            GIGA_AGENT_ENABLE_MULTI_TOOL_USE,
            GIGA_AGENT_ENABLE_MULTI_TOOL_USE_PROVIDERS,
            llm_type,
        )

        if think_enabled:
            think_hops = _count_trailing_think_tool_pairs(state["messages"])
            if think_hops > MAX_THINK_HOPS:
                msg = (
                    f"Too many consecutive think hops: {think_hops} "
                    f"(limit {MAX_THINK_HOPS})"
                )
                raise RuntimeError(msg)

        if multi_tool_use_enabled:
            few_shots_collapse = collapse_tool_messages(FEW_SHOT_EXAMPLES_SINGLE)
            collapsed_messages = collapse_tool_messages(state["messages"])
        elif think_enabled:
            few_shots_collapse = list(FEW_SHOT_EXAMPLES_SINGLE)
            collapsed_messages = list(state["messages"])
        else:
            few_shots_collapse = []
            collapsed_messages = list(state["messages"])
        state_messages_collapse = (
            collapse_think_hops(collapsed_messages)
            if think_enabled
            else collapsed_messages
        )
        configurable = (config or {}).get("configurable") or {}
        deep_research_forced = bool(configurable.get("deep_research_forced"))

        messages_for_llm = few_shots_collapse + state_messages_collapse
        if messages_for_llm and messages_for_llm[-1].type == "human":
            last_message = messages_for_llm[-1]
            user_input = last_message.content
            file_prompt = _build_file_prompt(last_message)
            selected_prompt = _build_selected_prompt(last_message)
            extended_task = await agent.extend_task(
                user=user,
                task=user_input,
                state=state,
                config=config,
            )

            final_parts = [
                _generate_user_info(state),
            ]
            if file_prompt:
                final_parts.append(file_prompt)
            if selected_prompt:
                final_parts.append(selected_prompt)
            if extended_task:
                final_parts.append(extended_task)
            # final_parts.append(
            #     "Активно планируй и следуй своему плану! "
            #     "Действуй по простым шагам!"
            #     "Следующий шаг: "
            # )
            final_parts.append(f"<user_query>{user_input}<user_query>")
            if deep_research_forced:
                final_parts.append(
                    "<forced_mode>Пользователь явно включил режим глубокого "
                    "исследования. Обязательно вызови инструмент "
                    "`run_deep_research` для ответа на этот запрос — даже если "
                    "тема кажется простой. Перед вызовом напиши короткую "
                    "строчку-прелюдию о запуске исследования."
                    "</forced_mode>"
                )
            enriched_message = last_message.model_copy(
                update={"content": "\n".join(final_parts)}
            )
            messages_for_llm[-1] = enriched_message

        agent_tools = await agent.get_tools(user, config=config)
        from giga_agent.core.agent.base import _disabled_module_ids
        disabled_set = _disabled_module_ids(config, user)
        if disabled_set:
            agent_tools = [
                t for t in agent_tools
                if (t.extras or {}).get("module_id")
                not in disabled_set
            ]
        mcp_tools = [
            transform_tool(
                {
                    "name": tool["name"],
                    "description": tool.get("description", "."),
                    "parameters": tool.get("inputSchema", {}),
                },
            )
            for tool in state.get("mcp_tools", [])
        ]

        tool_choice = (
            resolve_bound_tool_choice(state["messages"])
            if think_enabled
            else "auto"
        )
        # TODO: Сейчас ломается для deepseek, при мерже v0.2 будем включать только для GigaChat
        # chosen_tool_choice: Any = "auto"
        # if deep_research_forced:
        #     has_dr_tool = any(
        #         getattr(t, "name", None) == "run_deep_research" for t in all_tools
        #     )
        #     if has_dr_tool:
        #         chosen_tool_choice = "run_deep_research"
        #     else:
        #         # Флаг пришёл, но тул не зарегистрирован у юзера (нет llm/search_engine).
        #         # Оставляем auto — юзер увидит обычный ответ.
        #         pass
        optional_tools: list[BaseTool] = []
        if think_enabled:
            optional_tools.append(think)
        if multi_tool_use_enabled:
            optional_tools.append(multi_tool_use)

        # Connector-дисптач: если у юзера есть хоть один источник (MCP-сервер или
        # включённый ленивый модуль) — биндим две мета-тулы. Источники считаем
        # один раз и переиспользуем для системного промпта.
        connector_sources = await collect_sources(agent, user, config)
        if connector_sources:
            optional_tools.append(connector_get_info)
            optional_tools.append(connector_call_tool)

        all_tools = (
            optional_tools
            + built_in_tools
            + regular_tools
            + middleware_tools
            + agent_tools
            + mcp_tools
        )
        llm = llm.bind_tools(tools=all_tools)
        channel_prompt = _resolve_channel_prompt(config)
        scheduled_prompt = _resolve_scheduled_prompt(config)
        system_message = SystemMessage(
            content=await agent.get_prompt(
                user,
                state=state,
                config=config,
                channel_prompt=channel_prompt,
                scheduled_prompt=scheduled_prompt,
                enable_think=think_enabled,
                enable_multi_tool_use=multi_tool_use_enabled,
                connector_sources=connector_sources,
            )
        )

        request = ModelRequest(
            model=llm,
            tools=all_tools,
            system_message=system_message,
            messages=messages_for_llm,
            tool_choice=tool_choice,
            state=state,
            runtime=runtime,
        )

        async def _execute_with_expand(req: ModelRequest) -> ModelResponse:
            response = await _execute_model_async(req)
            if not multi_tool_use_enabled:
                return response
            expanded = [
                expand_multi_tool_use(m) if isinstance(m, AIMessage) else m
                for m in response.result
            ]
            return ModelResponse(
                result=expanded,
                structured_response=response.structured_response,
            )

        if wrap_model_call_handler is None:
            response = await _execute_with_expand(request)
        else:
            response = await wrap_model_call_handler(request, _execute_with_expand)

        result_messages = list(response.result)

        if think_enabled and THINK_VIA_FAST_MODEL and len(result_messages) == 1:
            ai_msg = result_messages[0]
            if isinstance(ai_msg, AIMessage) and is_single_think_call(ai_msg):
                factory = await get_session_factory()
                async with factory() as session:
                    result_messages = await process_think_via_fast_model(
                        ai_msg,
                        user=user,
                        session=session,
                        messages_for_llm=state_messages_collapse,
                        system_message=system_message,
                        tools=all_tools
                    )

        # Persist the enriched HumanMessage back to state (model_copy preserves
        # its id so add_messages replaces it in place). For any other last
        # message type (e.g. a synthetic ToolMessage produced by
        # collapse_tool_messages with a fresh uuid), we must NOT append it —
        # it would land in state as an orphan ToolMessage with no matching
        # AIMessage tool_call, which makes GigaChat reject the next request
        # with 422 "every function result must have an assistant function
        # call in history".
        state_messages_update: list[AnyMessage] = list(result_messages)
        if messages_for_llm and messages_for_llm[-1].type == "human":
            state_messages_update = [messages_for_llm[-1], *state_messages_update]

        state_updates = {"messages": state_messages_update}
        if response.structured_response is not None:
            state_updates["structured_response"] = response.structured_response

        return state_updates

    # Use sync or async based on model capabilities
    graph.add_node("model", amodel_node)

    # Only add tools node if we have tools
    if tool_node is not None:
        graph.add_node("tools", tool_node)

    def create_callback_node(
        callback_type: Literal[
            "before_agent", "before_model", "after_model", "after_agent"
        ],
    ) -> Callable[
        [AgentState, Runtime[ContextT], RunnableConfig],
        Coroutine[Any, Any, dict[str, Any]],
    ]:
        async def callback_node(
            state: AgentState,
            runtime: Runtime[ContextT],
            config: RunnableConfig,
        ) -> dict[str, Any]:
            resolver = await RuntimeResolver.create(config)
            resolver.inject(config)

            updates: list[dict[str, Any]] = []
            for m in middleware:
                if getattr(m.__class__, callback_type) is not getattr(
                    AgentMiddleware, callback_type
                ):
                    async_callback = (
                        getattr(m, callback_type)
                        if getattr(m.__class__, callback_type)
                        is not getattr(AgentMiddleware, callback_type)
                        else None
                    )
                    if async_callback is not None:
                        update = await async_callback(state, runtime, config)
                        if update:
                            updates.append(update)
                            state = merge_state(state, update, AgentState)
            # Return only the accumulated deltas: returning the full merged
            # state would put existing message ids back on their old channel
            # positions and a RemoveMessage would never reach the channel,
            # which breaks the dangling tool_calls repair reordering.
            return reduce_updates(updates, AgentState)

        return callback_node

    before_agent_node = create_callback_node("before_agent")
    before_model_node = create_callback_node("before_model")
    after_model_node = create_callback_node("after_model")
    after_agent_node = create_callback_node("after_agent")

    graph.add_node("before_agent", before_agent_node)
    graph.add_node("before_model", before_model_node)
    graph.add_node("after_model", after_model_node)
    graph.add_node("after_agent", after_agent_node)

    graph.add_edge(START, "before_agent")
    graph.add_edge("before_agent", "before_model")
    graph.add_edge("before_model", "model")
    graph.add_edge("model", "after_model")
    graph.add_edge("after_agent", END)

    # add conditional edges only if tools exist
    if tool_node is not None:
        graph.add_edge(
            "tools",
            "before_model",
        )

        graph.add_conditional_edges(
            "after_model",
            RunnableCallable(
                _make_model_to_tools_edge(
                    model_destination="before_model",
                    end_destination="after_agent",
                ),
                trace=False,
            ),
        )
    else:
        graph.add_edge("model", "after_model")
        graph.add_edge("after_model", "after_agent")

    compiled = graph.compile(
        checkpointer=checkpointer,
        store=store,
        debug=debug,
        name=name,
        cache=cache,
    ).with_config({"recursion_limit": 10_000})
    return compiled
