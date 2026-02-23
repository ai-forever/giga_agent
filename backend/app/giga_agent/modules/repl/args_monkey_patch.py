from typing import Any
from langchain_core.utils.pydantic import (
    get_fields,
)
from pydantic import BaseModel


def _parse_input(
    self, tool_input: str | dict, tool_call_id: str | None
) -> str | dict[str, Any]:
    """
    Это грязный хак для передачи tool_node в python для вызова из него тулов
    """
    input_args = self.args_schema

    if isinstance(tool_input, str):
        if input_args is not None:
            if isinstance(input_args, dict):
                msg = (
                    "String tool inputs are not allowed when "
                    "using tools with JSON schema args_schema."
                )
                raise ValueError(msg)
            key_ = next(iter(get_fields(input_args).keys()))
            if issubclass(input_args, BaseModel):
                input_args.model_validate({key_: tool_input})
            else:
                msg = f"args_schema must be a Pydantic BaseModel, got {input_args}"
                raise TypeError(msg)
        return tool_input

    return tool_input
