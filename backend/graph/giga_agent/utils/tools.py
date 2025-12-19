#
# Эти функции перенесены is langchain.tools они нужны, чтобы вставлять Runtime, State, Store
# в вызов тула. Пока это часть достаточно грязного хака, когда мы тулы вызываем
# вне ToolNode.
#
from copy import copy
from typing import Annotated, Any, Union, get_args, get_origin

from langchain.messages import AnyMessage
from langchain.tools import BaseTool, InjectedState, InjectedStore, ToolRuntime
from langchain_core.tools.base import ToolCall, get_all_basemodel_annotations
from langgraph.store.base import BaseStore
from pydantic import BaseModel


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


def _get_state_args(tool: BaseTool) -> dict[str, str | None]:
    """Extract state injection mappings from tool annotations.

    This function analyzes a tool's input schema to identify arguments that should
    be injected with graph state. It processes InjectedState annotations to build
    a mapping of tool argument names to state field names.

    Args:
        tool: The tool to analyze for state injection requirements.

    Returns:
        A dictionary mapping tool argument names to state field names. If a field
        name is None, the entire state should be injected for that argument.
    """
    full_schema = tool.get_input_schema()
    tool_args_to_state_fields: dict = {}

    for name, type_ in get_all_basemodel_annotations(full_schema).items():
        injections = [
            type_arg
            for type_arg in get_args(type_)
            if _is_injection(type_arg, InjectedState)
        ]
        if len(injections) > 1:
            msg = (
                "A tool argument should not be annotated with InjectedState more than "
                f"once. Received arg {name} with annotations {injections}."
            )
            raise ValueError(msg)
        if len(injections) == 1:
            injection = injections[0]
            if isinstance(injection, InjectedState) and injection.field:
                tool_args_to_state_fields[name] = injection.field
            else:
                tool_args_to_state_fields[name] = None
        else:
            pass
    return tool_args_to_state_fields


def _get_store_arg(tool: BaseTool) -> str | None:
    """Extract store injection argument from tool annotations.

    This function analyzes a tool's input schema to identify the argument that
    should be injected with the graph store. Only one store argument is supported
    per tool.

    Args:
        tool: The tool to analyze for store injection requirements.

    Returns:
        The name of the argument that should receive the store injection, or None
        if no store injection is required.

    Raises:
        ValueError: If a tool argument has multiple InjectedStore annotations.
    """
    full_schema = tool.get_input_schema()
    for name, type_ in get_all_basemodel_annotations(full_schema).items():
        injections = [
            type_arg
            for type_arg in get_args(type_)
            if _is_injection(type_arg, InjectedStore)
        ]
        if len(injections) > 1:
            msg = (
                "A tool argument should not be annotated with InjectedStore more than "
                f"once. Received arg {name} with annotations {injections}."
            )
            raise ValueError(msg)
        if len(injections) == 1:
            return name

    return None


def _get_runtime_arg(tool: BaseTool) -> str | None:
    """Extract runtime injection argument from tool annotations.

    This function analyzes a tool's input schema to identify the argument that
    should be injected with the ToolRuntime instance. Only one runtime argument
    is supported per tool.

    Args:
        tool: The tool to analyze for runtime injection requirements.

    Returns:
        The name of the argument that should receive the runtime injection, or None
        if no runtime injection is required.

    Raises:
        ValueError: If a tool argument has multiple ToolRuntime annotations.
    """
    full_schema = tool.get_input_schema()
    for name, type_ in get_all_basemodel_annotations(full_schema).items():
        # Check if the parameter name is "runtime" (regardless of type)
        if name == "runtime":
            return name
        # Check if the type itself is ToolRuntime (direct usage)
        if _is_injection(type_, ToolRuntime):
            return name
        # Check if ToolRuntime is in Annotated args
        injections = [
            type_arg
            for type_arg in get_args(type_)
            if _is_injection(type_arg, ToolRuntime)
        ]
        if len(injections) > 1:
            msg = (
                "A tool argument should not be annotated with ToolRuntime more than "
                f"once. Received arg {name} with annotations {injections}."
            )
            raise ValueError(msg)
        if len(injections) == 1:
            return name

    return None


def _inject_runtime(
    tool: BaseTool, tool_call: ToolCall, tool_runtime: ToolRuntime
) -> ToolCall:
    """Inject ToolRuntime into tool call arguments.

    Args:
        tool: The tool to inject runtime arg
        tool_call: The tool call to inject runtime into.
        tool_runtime: The ToolRuntime instance to inject.

    Returns:
        The tool call with runtime injected if needed.
    """
    runtime_arg = _get_runtime_arg(tool)
    if not runtime_arg:
        return tool_call

    tool_call["args"] = {
        **tool_call["args"],
        runtime_arg: tool_runtime,
    }
    return tool_call


def _inject_state(
    tool: BaseTool,
    tool_call: ToolCall,
    state: list[AnyMessage] | dict[str, Any] | BaseModel,
    messages_key: str = "messages",
) -> ToolCall:
    state_args = _get_state_args(tool)

    if state_args and isinstance(state, list):
        required_fields = list(state_args.values())
        if (
            len(required_fields) == 1 and required_fields[0] == messages_key
        ) or required_fields[0] is None:
            state = {messages_key: state}
        else:
            err_msg = (
                f"Invalid input to ToolNode. Tool {tool_call['name']} requires "
                f"graph state dict as input."
            )
            if any(state_field for state_field in state_args.values()):
                required_fields_str = ", ".join(f for f in required_fields if f)
                err_msg += f" State should contain fields {required_fields_str}."
            raise ValueError(err_msg)

    if isinstance(state, dict):
        tool_state_args = {
            tool_arg: state[state_field] if state_field else state
            for tool_arg, state_field in state_args.items()
        }
    else:
        tool_state_args = {
            tool_arg: getattr(state, state_field) if state_field else state
            for tool_arg, state_field in state_args.items()
        }

    tool_call["args"] = {
        **tool_call["args"],
        **tool_state_args,
    }
    return tool_call


def _inject_store(
    tool: BaseTool, tool_call: ToolCall, store: BaseStore | None
) -> ToolCall:
    store_arg = _get_store_arg(tool)
    if not store_arg:
        return tool_call

    if store is None:
        msg = (
            "Cannot inject store into tools with InjectedStore annotations - "
            "please compile your graph with a store."
        )
        raise ValueError(msg)

    tool_call["args"] = {
        **tool_call["args"],
        store_arg: store,
    }
    return tool_call


def inject_tool_args(
    tool: BaseTool,
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
    tool_call_copy: ToolCall = copy(tool_call)
    tool_call_with_state = _inject_state(tool, tool_call_copy, tool_runtime.state)
    tool_call_with_store = _inject_store(tool, tool_call_with_state, tool_runtime.store)
    return _inject_runtime(tool, tool_call_with_store, tool_runtime)
