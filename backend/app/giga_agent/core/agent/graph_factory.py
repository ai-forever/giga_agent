"""Agent factory for creating agents with middleware support."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast, Awaitable, Literal, Coroutine, Callable

from langchain_core.messages import (
    AIMessage,
    SystemMessage,
    ToolMessage,
    AnyMessage,
)
from langchain_core.tools import BaseTool
from langgraph._internal._runnable import RunnableCallable
from langgraph.constants import END, START
from langgraph.graph.state import StateGraph
from langgraph.runtime import Runtime
from langgraph.typing import ContextT
from langgraph.types import Command, Send
from langchain_core.runnables import RunnableConfig

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

import uuid

from giga_agent.core.db import get_session_factory
from giga_agent.core.agent.prompt import BASE_PROMPT
from giga_agent.core.agent.tool_node import ToolNode
from giga_agent.llm.manager import LLMManager
from giga_agent.models.users import UserRepository
from giga_agent.utils.mcp import transform_tool

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from langgraph.cache.base import BaseCache
    from langgraph.graph.state import CompiledStateGraph
    from langgraph.store.base import BaseStore
    from langgraph.types import Checkpointer
    from langchain.agents.middleware.types import ToolCallRequest
    from giga_agent.core.agent.base import BaseAgent
from giga_agent.core.agent.utils import merge_state
from giga_agent.core.agent.types import AgentState, Context


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
    if middleware_w_wrap_tool_call:
        wrappers = [m.wrap_tool_call for m in middleware_w_wrap_tool_call]
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
            # Проставляем ID вызовов тулов, если их нет, как в гиге
            call.setdefault("id", str(uuid.uuid4()))

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

            llm = await LLMManager.resolve_by_id(user.llm_id, session=session)
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
        llm = llm.bind_tools(
            tools=agent_tools + default_tools + mcp_tools, tool_choice="auto"
        )
        system_message = SystemMessage(content=await agent.get_prompt(user))

        request = ModelRequest(
            model=llm,
            tools=default_tools,
            system_message=system_message,
            messages=state["messages"],
            tool_choice=None,
            state=state,
            runtime=runtime,
        )

        if wrap_model_call_handler is None:
            # No async handlers - execute directly
            response = await _execute_model_async(request)
        else:
            # Call composed async handler with base handler
            response = await wrap_model_call_handler(request, _execute_model_async)

        # Extract state updates from ModelResponse
        state_updates = {"messages": response.result}
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
