from __future__ import annotations

import asyncio
import inspect
import json
import traceback
import uuid
from collections.abc import Awaitable, Callable
from copy import copy, deepcopy
from dataclasses import dataclass, replace
from types import UnionType
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    Generic,
    Literal,
    TypedDict,
    Union,
    cast,
    get_args,
    get_origin,
    get_type_hints,
)

from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    RemoveMessage,
    ToolCall,
    ToolMessage,
    convert_to_messages,
)
from langchain_core.runnables.config import (
    RunnableConfig,
    get_config_list,
    get_executor_for_config,
)
from langchain_core.tools import BaseTool, InjectedToolArg
from langchain_core.tools import tool as create_tool
from langchain_core.tools.base import (
    TOOL_MESSAGE_BLOCK_TYPES,
    ToolException,
    _DirectlyInjectedToolArg,
    get_all_basemodel_annotations,
)
from langgraph._internal._runnable import RunnableCallable
from langgraph.errors import GraphBubbleUp
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from langgraph.store.base import BaseStore  # noqa: TC002
from langgraph.types import Command, Send, StreamWriter, interrupt
from pydantic import BaseModel, ValidationError
from typing_extensions import TypeVar, Unpack

from langchain.tools.tool_node import (
    ToolRuntime,
    ToolCallRequest,
    InjectedStore,
    InjectedState,
)
from langgraph.prebuilt.tool_node import (
    ToolInvocationError,
    TOOL_CALL_ERROR_TEMPLATE,
    INVALID_TOOL_NAME_ERROR_TEMPLATE,
    msg_content_output,
    AsyncToolCallWrapper,
)

from giga_agent.core.agent.types import AgentState
from giga_agent.models import UserRepository

if TYPE_CHECKING:
    from collections.abc import Sequence

    from langgraph.runtime import Runtime
    from pydantic_core import ErrorDetails
    from giga_agent.core.agent.base import BaseAgent


def _default_handle_tool_errors(e: Exception) -> str:
    """Default error handler for tool errors.

    If the tool is a tool invocation error, return its message.
    Otherwise, raise the error.
    """
    if isinstance(e, ToolInvocationError):
        return e.message
    elif isinstance(e, Exception):
        traceback.print_exception(e)
        return TOOL_CALL_ERROR_TEMPLATE.format(error=repr(e))
    raise e


def _handle_tool_error(
    e: Exception,
    *,
    flag: (
        bool | str | Callable[..., str] | type[Exception] | tuple[type[Exception], ...]
    ),
) -> str:
    """Generate error message content based on exception handling configuration.

    This function centralizes error message generation logic, supporting different
    error handling strategies configured via the `ToolNode`'s `handle_tool_errors`
    parameter.

    Args:
        e: The exception that occurred during tool execution.
        flag: Configuration for how to handle the error. Can be:
            - bool: If `True`, use default error template
            - str: Use this string as the error message
            - Callable: Call this function with the exception to get error message
            - tuple: Not used in this context (handled by caller)

    Returns:
        A string containing the error message to include in the `ToolMessage`.

    Raises:
        ValueError: If flag is not one of the supported types.

    !!! note
        The tuple case is handled by the caller through exception type checking,
        not by this function directly.
    """
    if isinstance(flag, (bool, tuple)) or (
        isinstance(flag, type) and issubclass(flag, Exception)
    ):
        content = TOOL_CALL_ERROR_TEMPLATE.format(error=repr(e))
    elif isinstance(flag, str):
        content = flag
    elif callable(flag):
        content = flag(e)  # type: ignore [assignment, call-arg]
    else:
        msg = (
            f"Got unexpected type of `handle_tool_error`. Expected bool, str "
            f"or callable. Received: {flag}"
        )
        raise ValueError(msg)
    return content


def _infer_handled_types(handler: Callable[..., str]) -> tuple[type[Exception], ...]:
    """Infer exception types handled by a custom error handler function.

    This function analyzes the type annotations of a custom error handler to determine
    which exception types it's designed to handle. This enables type-safe error handling
    where only specific exceptions are caught and processed by the handler.

    Args:
        handler: A callable that takes an exception and returns an error message string.
                The first parameter (after self/cls if present) should be type-annotated
                with the exception type(s) to handle.

    Returns:
        A tuple of exception types that the handler can process. Returns (Exception,)
        if no specific type information is available for backward compatibility.

    Raises:
        ValueError: If the handler's annotation contains non-Exception types or
            if Union types contain non-Exception types.

    !!! note
        This function supports both single exception types and Union types for
        handlers that need to handle multiple exception types differently.
    """
    sig = inspect.signature(handler)
    params = list(sig.parameters.values())
    if params:
        # If it's a method, the first argument is typically 'self' or 'cls'
        if params[0].name in ["self", "cls"] and len(params) == 2:
            first_param = params[1]
        else:
            first_param = params[0]

        type_hints = get_type_hints(handler)
        if first_param.name in type_hints:
            origin = get_origin(first_param.annotation)
            if origin in [Union, UnionType]:
                args = get_args(first_param.annotation)
                if all(issubclass(arg, Exception) for arg in args):
                    return tuple(args)
                msg = (
                    "All types in the error handler error annotation must be "
                    "Exception types. For example, "
                    "`def custom_handler(e: Union[ValueError, TypeError])`. "
                    f"Got '{first_param.annotation}' instead."
                )
                raise ValueError(msg)

            exception_type = type_hints[first_param.name]
            if Exception in exception_type.__mro__:
                return (exception_type,)
            msg = (
                f"Arbitrary types are not supported in the error handler "
                f"signature. Please annotate the error with either a "
                f"specific Exception type or a union of Exception types. "
                "For example, `def custom_handler(e: ValueError)` or "
                "`def custom_handler(e: Union[ValueError, TypeError])`. "
                f"Got '{exception_type}' instead."
            )
            raise ValueError(msg)

    # If no type information is available, return (Exception,)
    # for backwards compatibility.
    return (Exception,)


def _filter_validation_errors(
    validation_error: ValidationError,
    injected_args: _InjectedArgs | None,
) -> list[ErrorDetails]:
    """Filter validation errors to only include LLM-controlled arguments.

    When a tool invocation fails validation, only errors for arguments that the LLM
    controls should be included in error messages. This ensures the LLM receives
    focused, actionable feedback about parameters it can actually fix. System-injected
    arguments (state, store, runtime) are filtered out since the LLM has no control
    over them.

    This function also removes injected argument values from the `input` field in error
    details, ensuring that only LLM-provided arguments appear in error messages.

    Args:
        validation_error: The Pydantic ValidationError raised during tool invocation.
        injected_args: The _InjectedArgs structure containing all injected arguments,
            or None if there are no injected arguments.

    Returns:
        List of ErrorDetails containing only errors for LLM-controlled arguments,
        with system-injected argument values removed from the input field.
    """
    # Collect all injected argument names
    injected_arg_names: set[str] = set()
    if injected_args:
        if injected_args.state:
            injected_arg_names.update(injected_args.state.keys())
        if injected_args.store:
            injected_arg_names.add(injected_args.store)
        if injected_args.runtime:
            injected_arg_names.add(injected_args.runtime)

    filtered_errors: list[ErrorDetails] = []
    for error in validation_error.errors():
        # Check if error location contains any injected argument
        # error['loc'] is a tuple like ('field_name',) or ('field_name', 'nested_field')
        if error["loc"] and error["loc"][0] not in injected_arg_names:
            # Create a copy of the error dict to avoid mutating the original
            error_copy: dict[str, Any] = {**error}

            # Remove injected arguments from input_value if it's a dict
            if isinstance(error_copy.get("input"), dict):
                input_dict = error_copy["input"]
                input_copy = {
                    k: v for k, v in input_dict.items() if k not in injected_arg_names
                }
                error_copy["input"] = input_copy

            # Cast is safe because ErrorDetails is a TypedDict compatible with this structure
            filtered_errors.append(error_copy)  # type: ignore[arg-type]

    return filtered_errors


@dataclass
class _InjectedArgs:
    """Internal structure for tracking injected arguments for a tool.

    This data structure is built once during ToolNode initialization by analyzing
    the tool's signature and args schema, then reused during execution for efficient
    injection without repeated reflection.

    The structure maps from tool parameter names to their injection sources, enabling
    the ToolNode to know exactly which arguments need to be injected and where to
    get their values from.

    Attributes:
        state: Mapping from tool parameter names to state field names for injection.
            Keys are tool parameter names, values are either:
            - str: Name of the state field to extract and inject
            - None: Inject the entire state object
            Empty dict if no state injection is needed.
        store: Name of the tool parameter where the store should be injected,
            or None if no store injection is needed.
        runtime: Name of the tool parameter where the runtime should be injected,
            or None if no runtime injection is needed.

    Example:
        For a tool with signature:
        ```python
        def my_tool(
            x: int,
            messages: Annotated[list, InjectedState("messages")],
            full_state: Annotated[dict, InjectedState()],
            store: Annotated[BaseStore, InjectedStore()],
            runtime: ToolRuntime,
        ) -> str:
            ...
        ```

        The resulting `_InjectedArgs` would be:
        ```python
        _InjectedArgs(
            state={
                "messages": "messages",  # Extract state["messages"]
                "full_state": None,      # Inject entire state
            },
            store="store",               # Inject into "store" parameter
            runtime="runtime",           # Inject into "runtime" parameter
        )
        ```
    """

    state: dict[str, str | None]
    store: str | None
    runtime: str | None


@dataclass
class AgentToolRuntime(ToolRuntime):
    agent: BaseAgent


class ToolNode(RunnableCallable):

    name: str = "tools"

    def __init__(
        self,
        tools: Sequence[BaseTool | Callable],
        agent: BaseAgent,
        *,
        name: str = "tools",
        tags: list[str] | None = None,
        handle_tool_errors: (
            bool
            | str
            | Callable[..., str]
            | type[Exception]
            | tuple[type[Exception], ...]
        ) = _default_handle_tool_errors,
        messages_key: str = "messages",
        wrap_tool_call: AsyncToolCallWrapper | None = None,
    ) -> None:
        """Initialize `ToolNode` with tools and configuration.

        Args:
            tools: Sequence of tools to make available for execution.
            name: Node name for graph identification.
            tags: Optional metadata tags.
            handle_tool_errors: Error handling configuration.
            messages_key: State key containing messages.
            wrap_tool_call: Sync wrapper function to intercept tool execution. Receives
                ToolCallRequest and execute callable, returns ToolMessage or Command.
                Enables retries, caching, request modification, and control flow.
            awrap_tool_call: Async wrapper function to intercept tool execution.
                If not provided, falls back to wrap_tool_call for async execution.
        """
        super().__init__(None, self._afunc, name=name, tags=tags, trace=False)
        self._tools_by_name: dict[str, BaseTool] = {}
        self._injected_args: dict[str, _InjectedArgs] = {}
        self._handle_tool_errors = handle_tool_errors
        self._messages_key = messages_key
        self._awrap_tool_call = wrap_tool_call
        self._agent = agent
        self._tools = tools

    @property
    def tools_by_name(self) -> dict[str, BaseTool]:
        """Mapping from tool name to BaseTool instance."""
        return self._tools_by_name

    async def _fill_tools(self, config: RunnableConfig):
        user_id = config["configurable"]["langgraph_auth_user"]["identity"]
        user_uuid = uuid.UUID(user_id) if isinstance(user_id, str) else user_id

        user = await UserRepository.get_cached_or_db(user_uuid)
        if user is None:
            raise ValueError(f"User with id {user_id} not found")

        tools = await self._agent.get_tools(user)
        tools.extend(self._tools)
        for tool in tools:
            if not isinstance(tool, BaseTool):
                tool_ = create_tool(cast("type[BaseTool]", tool))
            else:
                tool_ = tool
            self._tools_by_name[tool_.name] = tool_
            # Build injected args mapping once during initialization in a single pass
            self._injected_args[tool_.name] = _get_all_injected_args(tool_)

    async def _afunc(
        self,
        input: AgentState,
        config: RunnableConfig,
        runtime: Runtime,
    ) -> Any:
        await self._fill_tools(config)
        tool_calls, input_type = self._parse_input(input)
        config_list = get_config_list(config, len(tool_calls))

        # Construct ToolRuntime instances at the top level for each tool call
        tool_runtimes = []
        for call, cfg in zip(tool_calls, config_list, strict=False):
            state = self._extract_state(input)
            tool_runtime = AgentToolRuntime(
                state=state,
                tool_call_id=call["id"],
                config=cfg,
                context=runtime.context,
                store=runtime.store,
                stream_writer=runtime.stream_writer,
                agent=self._agent,
            )
            tool_runtimes.append(tool_runtime)

        # Pass original tool calls without injection
        coros = []
        for call, tool_runtime in zip(tool_calls, tool_runtimes, strict=False):
            coros.append(self._arun_one(call, input_type, tool_runtime))  # type: ignore[arg-type]
        outputs = await asyncio.gather(*coros)

        return self._combine_tool_outputs(outputs, input_type)

    def _combine_tool_outputs(
        self,
        outputs: list[ToolMessage | Command],
        input_type: Literal["list", "dict", "tool_calls"],
    ) -> list[Command | list[ToolMessage] | dict[str, list[ToolMessage]]]:
        # preserve existing behavior for non-command tool outputs for backwards
        # compatibility
        if not any(isinstance(output, Command) for output in outputs):
            # TypedDict, pydantic, dataclass, etc. should all be able to load from dict
            return outputs if input_type == "list" else {self._messages_key: outputs}

        # LangGraph will automatically handle list of Command and non-command node
        # updates
        combined_outputs: list[
            Command | list[ToolMessage] | dict[str, list[ToolMessage]]
        ] = []

        # combine all parent commands with goto into a single parent command
        parent_command: Command | None = None
        for output in outputs:
            if isinstance(output, Command):
                if (
                    output.graph is Command.PARENT
                    and isinstance(output.goto, list)
                    and all(isinstance(send, Send) for send in output.goto)
                ):
                    if parent_command:
                        parent_command = replace(
                            parent_command,
                            goto=cast("list[Send]", parent_command.goto) + output.goto,
                        )
                    else:
                        parent_command = Command(graph=Command.PARENT, goto=output.goto)
                else:
                    combined_outputs.append(output)
            else:
                combined_outputs.append(
                    [output] if input_type == "list" else {self._messages_key: [output]}
                )

        if parent_command:
            combined_outputs.append(parent_command)
        return combined_outputs

    async def _execute_tool_async(
        self,
        request: ToolCallRequest,
        input_type: Literal["list", "dict", "tool_calls"],
        config: RunnableConfig,
    ) -> ToolMessage | Command:
        """Execute tool call asynchronously with configured error handling.

        Args:
            request: Tool execution request.
            input_type: Input format.
            config: Runnable configuration.

        Returns:
            ToolMessage or Command.

        Raises:
            Exception: If tool fails and handle_tool_errors is False.
        """
        call = request.tool_call
        tool = request.tool

        # Validate tool exists when we actually need to execute it
        if tool is None:
            if invalid_tool_message := self._validate_tool_call(call):
                return invalid_tool_message
            # This should never happen if validation works correctly
            msg = f"Tool {call['name']} is not registered with ToolNode"
            raise TypeError(msg)

        # Inject state, store, and runtime right before invocation
        injected_call = self._inject_tool_args(call, request.runtime)
        call_args = {**injected_call, "type": "tool_call"}

        try:
            try:
                response = await tool.ainvoke(call_args, config)
            except ValidationError as exc:
                # Filter out errors for injected arguments
                injected = self._injected_args.get(call["name"])
                filtered_errors = _filter_validation_errors(exc, injected)
                # Use original call["args"] without injected values for error reporting
                raise ToolInvocationError(
                    call["name"], exc, call["args"], filtered_errors
                ) from exc

        # GraphInterrupt is a special exception that will always be raised.
        # It can be triggered in the following scenarios,
        # Where GraphInterrupt(GraphBubbleUp) is raised from an `interrupt` invocation
        # most commonly:
        # (1) a GraphInterrupt is raised inside a tool
        # (2) a GraphInterrupt is raised inside a graph node for a graph called as a tool
        # (3) a GraphInterrupt is raised when a subgraph is interrupted inside a graph
        #     called as a tool
        # (2 and 3 can happen in a "supervisor w/ tools" multi-agent architecture)
        except GraphBubbleUp:
            raise
        except Exception as e:
            # Determine which exception types are handled
            handled_types: tuple[type[Exception], ...]
            if isinstance(self._handle_tool_errors, type) and issubclass(
                self._handle_tool_errors, Exception
            ):
                handled_types = (self._handle_tool_errors,)
            elif isinstance(self._handle_tool_errors, tuple):
                handled_types = self._handle_tool_errors
            elif callable(self._handle_tool_errors) and not isinstance(
                self._handle_tool_errors, type
            ):
                handled_types = _infer_handled_types(self._handle_tool_errors)
            else:
                # default behavior is catching all exceptions
                handled_types = (Exception,)

            # Check if this error should be handled
            if not self._handle_tool_errors or not isinstance(e, handled_types):
                raise

            # Error is handled - create error ToolMessage
            content = json.dumps(
                {"error": _handle_tool_error(e, flag=self._handle_tool_errors)},
                ensure_ascii=False,
            )
            return ToolMessage(
                content=content,
                name=call["name"],
                tool_call_id=call["id"],
                status="error",
            )

        # Process successful response
        if isinstance(response, Command):
            # Validate Command before returning to handler
            return self._validate_tool_command(response, request.tool_call, input_type)
        if isinstance(response, ToolMessage):
            response.content = cast("str | list", msg_content_output(response.content))
            return response

        msg = f"Tool {call['name']} returned unexpected type: {type(response)}"
        raise TypeError(msg)

    async def _arun_one(
        self,
        call: ToolCall,
        input_type: Literal["list", "dict", "tool_calls"],
        tool_runtime: AgentToolRuntime,
    ) -> ToolMessage | Command:
        """Execute single tool call asynchronously with awrap_tool_call wrapper if configured.

        Args:
            call: Tool call dict.
            input_type: Input format.
            tool_runtime: Tool runtime.

        Returns:
            ToolMessage or Command.
        """
        # Validation is deferred to _execute_tool_async to allow interceptors
        # to short-circuit requests for unregistered tools
        tool = self.tools_by_name.get(call["name"])

        # Create the tool request with state and runtime
        tool_request = ToolCallRequest(
            tool_call=call,
            tool=tool,
            state=tool_runtime.state,
            runtime=tool_runtime,
        )

        config = tool_runtime.config

        if self._awrap_tool_call is None:
            # No wrapper - execute directly
            return await self._execute_tool_async(tool_request, input_type, config)

        # Define async execute callable that can be called multiple times
        async def execute(req: ToolCallRequest) -> ToolMessage | Command:
            """Execute tool with given request. Can be called multiple times."""
            return await self._execute_tool_async(req, input_type, config)

        # Call wrapper with request and execute callable
        try:
            if self._awrap_tool_call is not None:
                return await self._awrap_tool_call(tool_request, execute)
        except Exception as e:
            # Wrapper threw an exception
            if not self._handle_tool_errors:
                raise
            # Convert to error message
            content = json.dumps(
                {"error": _handle_tool_error(e, flag=self._handle_tool_errors)},
                ensure_ascii=False,
            )
            return ToolMessage(
                content=content,
                name=tool_request.tool_call["name"],
                tool_call_id=tool_request.tool_call["id"],
                status="error",
            )

    def _parse_input(
        self,
        input: list[AnyMessage] | dict[str, Any] | BaseModel,
    ) -> tuple[list[ToolCall], Literal["list", "dict", "tool_calls"]]:
        input_type: Literal["list", "dict", "tool_calls"]
        if isinstance(input, list):
            if isinstance(input[-1], dict) and input[-1].get("type") == "tool_call":
                input_type = "tool_calls"
                tool_calls = cast("list[ToolCall]", input)
                return tool_calls, input_type
            input_type = "list"
            messages = input
        elif (
            isinstance(input, dict) and input.get("__type") == "tool_call_with_context"
        ):
            # Handle ToolCallWithContext from Send API
            # mypy will not be able to type narrow correctly since the signature
            # for input contains dict[str, Any]. We'd need to narrow dict[str, Any]
            # before we can apply correct typing.
            input_with_ctx = cast("ToolCallWithContext", input)
            input_type = "tool_calls"
            return [input_with_ctx["tool_call"]], input_type
        elif isinstance(input, dict) and (
            messages := input.get(self._messages_key, [])
        ):
            input_type = "dict"
        elif messages := getattr(input, self._messages_key, []):
            # Assume dataclass-like state that can coerce from dict
            input_type = "dict"
        else:
            msg = "No message found in input"
            raise ValueError(msg)

        try:
            latest_ai_message = next(
                m for m in reversed(messages) if isinstance(m, AIMessage)
            )
        except StopIteration:
            msg = "No AIMessage found in input"
            raise ValueError(msg)

        tool_calls = list(latest_ai_message.tool_calls)
        return tool_calls, input_type

    def _validate_tool_call(self, call: ToolCall) -> ToolMessage | None:
        requested_tool = call["name"]
        if requested_tool not in self.tools_by_name:
            all_tool_names = list(self.tools_by_name.keys())
            content = INVALID_TOOL_NAME_ERROR_TEMPLATE.format(
                requested_tool=requested_tool,
                available_tools=", ".join(all_tool_names),
            )
            return ToolMessage(
                content, name=requested_tool, tool_call_id=call["id"], status="error"
            )
        return None

    def _extract_state(
        self, input: list[AnyMessage] | dict[str, Any] | BaseModel
    ) -> list[AnyMessage] | dict[str, Any] | BaseModel:
        """Extract state from input, handling ToolCallWithContext if present.

        Args:
            input: The input which may be raw state or ToolCallWithContext.

        Returns:
            The actual state to pass to wrap_tool_call wrappers.
        """
        if isinstance(input, dict) and input.get("__type") == "tool_call_with_context":
            return input["state"]
        return input

    def _inject_tool_args(
        self,
        tool_call: ToolCall,
        tool_runtime: ToolRuntime,
    ) -> ToolCall:
        """Inject graph state, store, and runtime into tool call arguments.

        This is an internal method that enables tools to access graph context that
        should not be controlled by the model. Tools can declare dependencies on graph
        state, persistent storage, or runtime context using InjectedState, InjectedStore,
        and ToolRuntime annotations. This method automatically identifies these
        dependencies and injects the appropriate values.

        The injection process preserves the original tool call structure while adding
        the necessary context arguments. This allows tools to be both model-callable
        and context-aware without exposing internal state management to the model.

        Args:
            tool_call: The tool call dictionary to augment with injected arguments.
                Must contain 'name', 'args', 'id', and 'type' fields.
            tool_runtime: The ToolRuntime instance containing all runtime context
                (state, config, store, context, stream_writer) to inject into tools.

        Returns:
            A new ToolCall dictionary with the same structure as the input but with
            additional arguments injected based on the tool's annotation requirements.

        Raises:
            ValueError: If a tool requires store injection but no store is provided,
                or if state injection requirements cannot be satisfied.

        !!! note
            This method is called automatically during tool execution. It should not
            be called from outside the `ToolNode`.
        """
        if tool_call["name"] not in self.tools_by_name:
            return tool_call

        injected = self._injected_args.get(tool_call["name"])
        if not injected:
            return tool_call

        tool_call_copy: ToolCall = copy(tool_call)
        injected_args = {}

        # Inject state
        if injected.state:
            state = tool_runtime.state
            # Handle list state by converting to dict
            if isinstance(state, list):
                required_fields = list(injected.state.values())
                if (
                    len(required_fields) == 1
                    and required_fields[0] == self._messages_key
                ) or required_fields[0] is None:
                    state = {self._messages_key: state}
                else:
                    err_msg = (
                        f"Invalid input to ToolNode. Tool {tool_call['name']} requires "
                        f"graph state dict as input."
                    )
                    if any(state_field for state_field in injected.state.values()):
                        required_fields_str = ", ".join(f for f in required_fields if f)
                        err_msg += (
                            f" State should contain fields {required_fields_str}."
                        )
                    raise ValueError(err_msg)

            # Extract state values
            if isinstance(state, dict):
                for tool_arg, state_field in injected.state.items():
                    injected_args[tool_arg] = (
                        state[state_field] if state_field else state
                    )
            else:
                for tool_arg, state_field in injected.state.items():
                    injected_args[tool_arg] = (
                        getattr(state, state_field) if state_field else state
                    )

        # Inject store
        if injected.store:
            if tool_runtime.store is None:
                msg = (
                    "Cannot inject store into tools with InjectedStore annotations - "
                    "please compile your graph with a store."
                )
                raise ValueError(msg)
            injected_args[injected.store] = tool_runtime.store

        # Inject runtime
        if injected.runtime:
            injected_args[injected.runtime] = tool_runtime

        tool_call_copy["args"] = {**tool_call_copy["args"], **injected_args}
        return tool_call_copy

    def _validate_tool_command(
        self,
        command: Command,
        call: ToolCall,
        input_type: Literal["list", "dict", "tool_calls"],
    ) -> Command:
        if isinstance(command.update, dict):
            # input type is dict when ToolNode is invoked with a dict input
            # (e.g. {"messages": [AIMessage(..., tool_calls=[...])]})
            if input_type not in ("dict", "tool_calls"):
                msg = (
                    "Tools can provide a dict in Command.update only when using dict "
                    f"with '{self._messages_key}' key as ToolNode input, "
                    f"got: {command.update} for tool '{call['name']}'"
                )
                raise ValueError(msg)

            updated_command = deepcopy(command)
            state_update = cast("dict[str, Any]", updated_command.update) or {}
            messages_update = state_update.get(self._messages_key, [])
        elif isinstance(command.update, list):
            # Input type is list when ToolNode is invoked with a list input
            # (e.g. [AIMessage(..., tool_calls=[...])])
            if input_type != "list":
                msg = (
                    "Tools can provide a list of messages in Command.update "
                    "only when using list of messages as ToolNode input, "
                    f"got: {command.update} for tool '{call['name']}'"
                )
                raise ValueError(msg)

            updated_command = deepcopy(command)
            messages_update = updated_command.update
        else:
            return command

        # convert to message objects if updates are in a dict format
        messages_update = convert_to_messages(messages_update)

        # no validation needed if all messages are being removed
        if messages_update == [RemoveMessage(id=REMOVE_ALL_MESSAGES)]:
            return updated_command

        has_matching_tool_message = False
        for message in messages_update:
            if not isinstance(message, ToolMessage):
                continue

            if message.tool_call_id == call["id"]:
                message.name = call["name"]
                has_matching_tool_message = True

        # validate that we always have a ToolMessage matching the tool call in
        # Command.update if command is sent to the CURRENT graph
        if updated_command.graph is None and not has_matching_tool_message:
            example_update = (
                '`Command(update={"messages": '
                '[ToolMessage("Success", tool_call_id=tool_call_id), ...]}, ...)`'
                if input_type == "dict"
                else "`Command(update="
                '[ToolMessage("Success", tool_call_id=tool_call_id), ...], ...)`'
            )
            msg = (
                "Expected to have a matching ToolMessage in Command.update "
                f"for tool '{call['name']}', got: {messages_update}. "
                "Every tool call (LLM requesting to call a tool) "
                "in the message history MUST have a corresponding ToolMessage. "
                f"You can fix it by modifying the tool to return {example_update}."
            )
            raise ValueError(msg)
        return updated_command


def _is_injection(
    type_arg: Any,
    injection_type: type[InjectedState | InjectedStore | ToolRuntime],
) -> bool:
    """Check if a type argument represents an injection annotation.

    This utility function determines whether a type annotation indicates that
    an argument should be injected with state or store data. It handles both
    direct annotations and nested annotations within Union or Annotated types.

    Args:
        type_arg: The type argument to check for injection annotations.
        injection_type: The injection type to look for (InjectedState or InjectedStore).

    Returns:
        True if the type argument contains the specified injection annotation.
    """
    if isinstance(type_arg, injection_type) or (
        isinstance(type_arg, type) and issubclass(type_arg, injection_type)
    ):
        return True
    origin_ = get_origin(type_arg)
    if origin_ is Union or origin_ is Annotated:
        return any(_is_injection(ta, injection_type) for ta in get_args(type_arg))
    return False


def _get_injection_from_type(
    type_: Any, injection_type: type[InjectedState | InjectedStore | ToolRuntime]
) -> Any | None:
    """Extract injection instance from a type annotation.

    Args:
        type_: The type annotation to check.
        injection_type: The injection type to look for.

    Returns:
        The injection instance if found, True if injection marker found without instance, None otherwise.
    """
    type_args = get_args(type_)
    matches = [arg for arg in type_args if _is_injection(arg, injection_type)]

    if len(matches) > 1:
        msg = (
            f"A tool argument should not be annotated with {injection_type.__name__} "
            f"more than once. Found: {matches}"
        )
        raise ValueError(msg)

    if len(matches) == 1:
        return matches[0]
    elif _is_injection(type_, injection_type):
        return True

    return None


def _get_all_injected_args(tool: BaseTool) -> _InjectedArgs:
    """Extract all injected arguments from tool in a single pass.

    This function analyzes both the tool's input schema and function signature
    to identify all arguments that should be injected (state, store, runtime).

    Args:
        tool: The tool to analyze for injection requirements.

    Returns:
        _InjectedArgs structure containing all detected injections.
    """
    # Get annotations from both schema and function signature
    full_schema = tool.get_input_schema()
    schema_annotations = get_all_basemodel_annotations(full_schema)

    func = getattr(tool, "func", None) or getattr(tool, "coroutine", None)
    func_annotations = get_type_hints(func, include_extras=True) if func else {}

    # Combine both annotation sources, preferring schema annotations
    # In the future, we might want to add more restrictions here...
    all_annotations = {**func_annotations, **schema_annotations}

    # Track injected args
    state_args: dict[str, str | None] = {}
    store_arg: str | None = None
    runtime_arg: str | None = None

    for name, type_ in all_annotations.items():
        # Check for runtime (special case: parameter named "runtime")
        if name == "runtime":
            runtime_arg = name

        # Check for InjectedState
        if state_inj := _get_injection_from_type(type_, InjectedState):
            if isinstance(state_inj, InjectedState) and state_inj.field:
                state_args[name] = state_inj.field
            else:
                state_args[name] = None

        # Check for InjectedStore
        if _get_injection_from_type(type_, InjectedStore):
            store_arg = name

        # Check for ToolRuntime
        if _get_injection_from_type(type_, ToolRuntime):
            runtime_arg = name

    return _InjectedArgs(
        state=state_args,
        store=store_arg,
        runtime=runtime_arg,
    )
