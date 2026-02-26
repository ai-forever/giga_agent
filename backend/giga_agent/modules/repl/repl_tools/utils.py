from __future__ import annotations

import inspect


def _is_tool_runtime_param(param: inspect.Parameter) -> bool:
    annotation = param.annotation
    if annotation is inspect.Parameter.empty:
        return False
    if isinstance(annotation, str):
        lowered = annotation.lower()
        return "toolruntime" in lowered or "tool_runtime" in lowered
    name = getattr(annotation, "__name__", "")
    lowered_name = str(name).lower()
    return "toolruntime" in lowered_name or "tool_runtime" in lowered_name


def _format_function_signature(func) -> str:
    signature = inspect.signature(func)
    filtered_params = [
        param
        for param in signature.parameters.values()
        if not _is_tool_runtime_param(param)
    ]
    filtered_signature = signature.replace(parameters=filtered_params)
    return f"def {func.__name__}{filtered_signature}:"


def _format_docstring(doc: str | None, indent: int = 4) -> str:
    if not doc:
        return "".rjust(indent) + '"""Описание отсутствует"""'
    ind = " " * indent
    lines = doc.strip().splitlines()
    if len(lines) == 1:
        return f'{ind}"""{lines[0]}"""'
    # Многострочная строка документации с сохранением исходных переносов
    body = "\n".join(f"{ind}{line}" if line else "" for line in lines)
    return f'{ind}"""\n{body}\n{ind}"""'


def describe_repl_tool(repl_tool) -> str:
    """Возвращает текстовое описание функций,
    определённых в пакете `giga_agent.repl_tools`.
    """
    signature_line = _format_function_signature(repl_tool)
    doc_block = _format_docstring(inspect.getdoc(repl_tool))
    return f"{signature_line}\n{doc_block}"
