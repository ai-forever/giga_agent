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
    ToolCallWithContext,
)
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
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

import giga_agent.channels  # noqa: F401
from giga_agent.channels.registry import ChannelRegistry
from giga_agent.core.logging import get_logger
from langchain.agents.middleware.types import (
    ModelRequest,
    ModelResponse,
    ResponseT,
    StateT_co,
    _InputAgentState,
    _OutputAgentState,
)
from giga_agent.core.agent.middleware import AgentMiddleware

from langchain.tools.tool_node import (
    ToolCallRequest,
    ToolCallWithContext,
)

import json
import uuid

from giga_agent.core.db import get_session_factory
from giga_agent.core.agent.few_shots_single import FEW_SHOT_EXAMPLES_SINGLE
from giga_agent.core.agent.multi_tool_use import (
    collapse_tool_messages,
    expand_multi_tool_use,
)
from giga_agent.core.agent.prompt import BASE_PROMPT
from giga_agent.core.agent.tool_node import ToolNode
from giga_agent.core.db import get_session_factory
from giga_agent.llm.manager import LLMManager
from giga_agent.models.users import UserRepository
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
from giga_agent.core.agent.utils import merge_state

logger = get_logger(__name__)

THINK_TOOL_NAME = "think"
MAX_FORCED_THINK_FOLLOWUPS = 2
THINK_VIA_FAST_MODEL = False
THINK_HOP_RESULT = (
    "Подумай еще глубже и подробнее. Проверь, что ты мог упустить, "
    "покритикуй свой текущий ход мысли, проверь слабые места плана. "
    "Пересмотри выводы, попробуй найти оставшиеся противоречия, неочевидные "
    "риски и альтернативные трактовки. Убедись, что твой следующий шаг "
    "действительно самый лучший."
)
FAST_MODEL_THINK_PROMPT = (
    "Расширь и углуби предыдущие рассуждения ассистента. "
    "Найди слабые места, оцени плюсы и минусы подхода, "
    "предложи альтернативы и укажи, что ещё стоит учесть. "
)



def _generate_user_info(state: AgentState) -> str:
    # TODO: Вынести язык пользователя в явные пользовательские настройки
    language = "ru"
    language_prompt = ""
    if not language.startswith("ru"):
        language_prompt = f"\nВыбранный язык пользователя: {language}\n"
    return (
        f"<user_info>\n"
        f"Текущая дата: {datetime.today().strftime('%d.%m.%Y %H:%M')}"
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

    normalized_channel_type = channel_type.strip().lower()
    if not ChannelRegistry.is_registered(normalized_channel_type):
        return ""

    return ChannelRegistry.get(normalized_channel_type).get_prompt()


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


def _count_trailing_think_tool_pairs(messages: list[AnyMessage]) -> int:
    """Count trailing consecutive AI(think) -> ToolMessage pairs."""
    pairs = 0
    index = len(messages) - 1

    while index >= 1:
        tool_message = messages[index]
        ai_message = messages[index - 1]

        if not isinstance(tool_message, ToolMessage):
            break
        if not isinstance(ai_message, AIMessage):
            break
        if len(ai_message.tool_calls) != 1:
            break

        tool_call = ai_message.tool_calls[0]
        if tool_call.get("name") != THINK_TOOL_NAME:
            break
        if tool_call.get("id") != tool_message.tool_call_id:
            break

        pairs += 1
        index -= 2

    return pairs


def _is_think_pair(ai_msg: AnyMessage, tool_msg: AnyMessage) -> bool:
    """Check if an AI+ToolMessage pair is a single think tool call."""
    if not isinstance(ai_msg, AIMessage) or not isinstance(tool_msg, ToolMessage):
        return False
    if len(ai_msg.tool_calls) != 1:
        return False
    call = ai_msg.tool_calls[0]
    return (
        call.get("name") == THINK_TOOL_NAME
        and call.get("id") == tool_msg.tool_call_id
    )


def _merge_think_group(
    pairs: list[tuple[AIMessage, ToolMessage]],
) -> list[AnyMessage]:
    """Collapse a group of consecutive think pairs into one AI+ToolMessage.

    Single pairs are returned as-is. For 2+ pairs the thoughts are joined
    and content on the merged AIMessage is cleared.
    """
    if len(pairs) == 1:
        return [pairs[0][0], pairs[0][1]]

    thoughts = [_extract_think_thoughts(ai) for ai, _ in pairs]
    merged_thoughts = "\n---\n".join(t for t in thoughts if t)

    last_ai, last_tool = pairs[-1]

    merged_call = last_ai.tool_calls[0].copy()
    merged_args = dict(merged_call.get("args", {}))
    merged_args["thoughts"] = merged_thoughts
    merged_call["args"] = merged_args

    merged_ai = last_ai.model_copy(
        update={"tool_calls": [merged_call], "content": ""}
    )
    merged_tool = last_tool.model_copy(update={"content": ""})
    return [merged_ai, merged_tool]


def collapse_think_hops(messages: list[AnyMessage]) -> list[AnyMessage]:
    """Merge every run of consecutive AI(think)+ToolMessage pairs across
    the whole conversation into a single pair per run.
    """
    if len(messages) < 4:
        return messages

    result: list[AnyMessage] = []
    i = 0

    while i < len(messages) - 1:
        if _is_think_pair(messages[i], messages[i + 1]):
            group: list[tuple[AIMessage, ToolMessage]] = []
            while (
                i < len(messages) - 1
                and _is_think_pair(messages[i], messages[i + 1])
            ):
                group.append(
                    (cast("AIMessage", messages[i]),
                     cast("ToolMessage", messages[i + 1]))
                )
                i += 2
            result.extend(_merge_think_group(group))
        else:
            result.append(messages[i])
            i += 1

    if i < len(messages):
        result.append(messages[i])

    return result


def _resolve_bound_tool_choice(messages: list[AnyMessage]) -> str:
    """Force repeated think calls for a limited trailing think/tool chain."""
    trailing_think_pairs = _count_trailing_think_tool_pairs(messages)
    if 1 <= trailing_think_pairs <= MAX_FORCED_THINK_FOLLOWUPS:
        return THINK_TOOL_NAME
    return "auto"


async def _wrap_think_hop_result(
    request: ToolCallRequest,
    execute: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
) -> ToolMessage | Command[Any]:
    """Inject hop-specific reflection prompts for repeated think calls."""
    response = await execute(request)
    if request.tool_call.get("name") != THINK_TOOL_NAME:
        return response
    if not isinstance(response, ToolMessage):
        return response

    state_messages = request.state.get("messages", []) + [response]
    if not isinstance(state_messages, list):
        return response

    trailing_think_pairs = _count_trailing_think_tool_pairs(state_messages)
    if trailing_think_pairs >= MAX_FORCED_THINK_FOLLOWUPS:
        return response

    return response.model_copy(
        update={"content": json.dumps(THINK_HOP_RESULT, ensure_ascii=False)}
    )


def _is_single_think_call(ai_message: AIMessage) -> bool:
    """Check if AIMessage contains exactly one think tool_call and nothing else."""
    return (
        len(ai_message.tool_calls) == 1
        and ai_message.tool_calls[0].get("name") == THINK_TOOL_NAME
    )


def _extract_think_thoughts(ai_message: AIMessage) -> str:
    """Extract thoughts text from a single think tool_call."""
    args = ai_message.tool_calls[0].get("args", {})
    return args.get("thoughts") or args.get("thought") or ""


async def _process_think_via_fast_model(
    ai_message: AIMessage,
    *,
    user,
    session,
    messages_for_llm: list[AnyMessage],
    system_message: SystemMessage,
    tools: list[BaseTool],
) -> list[AnyMessage]:
    """Replace think tool_call with fast_model reasoning and return patched messages.

    Flow:
    1. Strip think tool_call from AIMessage, move thoughts into content
    2. Append HumanMessage asking fast_model to critique/analyze
    3. Call fast_model
    4. Wrap fast_model answer as ToolMessage for the original think call
    5. Return [original AIMessage with tool_call, ToolMessage with fast_model answer]
    """
    thoughts = _extract_think_thoughts(ai_message)
    think_call = ai_message.tool_calls[0]
    think_call_id = think_call.get("id") or str(uuid.uuid4())

    fast_llm_id = user.fast_llm_id or user.llm_id
    if fast_llm_id is None:
        return [ai_message]

    fast_llm_runtime = await LLMManager.resolve_by_id(fast_llm_id, session=session)
    fast_llm = await fast_llm_runtime.get_llm()
    fast_llm = fast_llm.with_config(tags=["nostream"])

    ai_as_content = ai_message.model_copy(
        update={"tool_calls": [], "content": f"{thoughts}", "additional_kwargs": {}}
    )
    critique_request = HumanMessage(content=FAST_MODEL_THINK_PROMPT)
    fast_messages = [system_message] + messages_for_llm[:-1] + [ai_as_content, critique_request]
    agent = fast_llm
    fast_response = await agent.ainvoke(fast_messages)
    fast_text = (
        fast_response.content
        if isinstance(fast_response.content, str)
        else str(fast_response.content)
    )
    think_call['args']['thoughts'] = thoughts + "\n" + fast_text

    return [ai_message.model_copy(update={"tool_calls": [think_call]})]


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
                    ToolCallWithContext(
                        __type="tool_call_with_context",
                        tool_call=tool_call,
                        state=state,
                    ),
                )
                for tool_call in pending_tool_calls
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
    wrappers = [_wrap_think_hop_result]
    if middleware_w_wrap_tool_call:
        wrappers.extend(m.wrap_tool_call for m in middleware_w_wrap_tool_call)
    if wrappers:
        wrap_tool_call_wrapper = _chain_async_tool_call_wrappers(wrappers)

    # Extract built-in provider tools (dict format) and regular tools (BaseTool/callables)
    built_in_tools = [t for t in tools if isinstance(t, dict)]
    regular_tools = [t for t in tools if not isinstance(t, dict)]

    # Tools that require client-side execution (must be in ToolNode)
    available_tools = middleware_tools + regular_tools

    # Only create ToolNode if we have client-side tools
    tool_node = ToolNode(
        tools=available_tools,
        wrap_tool_call=wrap_tool_call_wrapper,
        agent=agent,
    )

    # Default tools for ModelRequest initialization
    # Use converted BaseTool instances from ToolNode (not raw callables)
    # Include built-ins and converted tools (can be changed dynamically by middleware)
    # Structured tools are NOT included - they're added dynamically based on response_format
    if tool_node:
        default_tools = list(tool_node.tools_by_name.values()) + built_in_tools
    else:
        default_tools = list(built_in_tools)

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
        # Get the bound model (with auto-detection if needed)
        model_ = request.model.bind(**request.model_settings)
        messages = request.messages
        if request.system_message:
            messages = [request.system_message, *messages]

        output = await model_.ainvoke(messages)
        if name:
            output.name = name
        output.additional_kwargs.pop("function_call", None)
        output.additional_kwargs["rendered"] = True
        for call in output.tool_calls:
            call.setdefault("id", str(uuid.uuid4()))

        output = expand_multi_tool_use(output)

        return ModelResponse(
            result=[output],
        )

    async def amodel_node(
        state: AgentState, runtime: Runtime[ContextT], config
    ) -> dict[str, Any]:
        """Async model request handler with sequential middleware processing."""
        # Получаем user_id из конфигурации langgraph auth
        user_id = config["configurable"]["langgraph_auth_user"]["identity"]
        user_uuid = uuid.UUID(user_id) if isinstance(user_id, str) else user_id

        factory = await get_session_factory()
        async with factory() as session:
            user = await UserRepository.get_cached_or_db(user_uuid, session=session)
            if user is None:
                raise ValueError(f"User with id {user_id} not found")

            if not user.llm_id:
                raise ValueError("User has no default LLM configured")

            llm_runtime = await LLMManager.resolve_by_id(user.llm_id, session=session)
            llm = await llm_runtime.get_llm()
        configurable = (config or {}).get("configurable") or {}
        deep_research_forced = bool(configurable.get("deep_research_forced"))

        few_shots_collapse = collapse_tool_messages(
            FEW_SHOT_EXAMPLES_SINGLE + list(state["messages"])
        )
        state_messages_collapse = collapse_think_hops(
            collapse_tool_messages(state["messages"])
        )
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

        agent_tools = await agent.get_tools(user)
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
        tool_choice = _resolve_bound_tool_choice(state["messages"])
        llm = llm.bind_tools(
            tools=agent_tools + default_tools + mcp_tools, tool_choice=tool_choice
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
        channel_prompt = _resolve_channel_prompt(config)
        system_message = SystemMessage(
            content=await agent.get_prompt(
                user,
                state=state,
                config=config,
                channel_prompt=channel_prompt,
            )
        )

        request = ModelRequest(
            model=llm,
            tools=default_tools,
            system_message=system_message,
            messages=messages_for_llm,
            tool_choice=tool_choice,
            state=state,
            runtime=runtime,
        )

        if wrap_model_call_handler is None:
            # No async handlers - execute directly
            response = await _execute_model_async(request)
        else:
            # Call composed async handler with base handler
            response = await wrap_model_call_handler(request, _execute_model_async)

        result_messages = list(response.result)

        if THINK_VIA_FAST_MODEL and len(result_messages) == 1:
            ai_msg = result_messages[0]
            if isinstance(ai_msg, AIMessage) and _is_single_think_call(ai_msg):
                factory = await get_session_factory()
                async with factory() as session:
                    result_messages = await _process_think_via_fast_model(
                        ai_msg,
                        user=user,
                        session=session,
                        messages_for_llm=state_messages_collapse,
                        system_message=system_message,
                        tools=agent_tools + default_tools + mcp_tools
                    )

        state_updates = {"messages": result_messages}
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
                        state = merge_state(
                            state,
                            await async_callback(state, runtime, config),
                            AgentState,
                        )
            return state

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

    return graph.compile(
        checkpointer=checkpointer,
        store=store,
        debug=debug,
        name=name,
        cache=cache,
    ).with_config({"recursion_limit": 10_000})
