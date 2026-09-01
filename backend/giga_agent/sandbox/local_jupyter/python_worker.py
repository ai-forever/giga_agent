"""Persistent Python worker used by the local CLI sandbox.

The parent process owns the transport.  This module deliberately uses only
the standard library plus optional matplotlib/plotly imports, so worker mode
does not require Jupyter or IPython to be installed.
"""

from __future__ import annotations

import ast
import base64
import builtins
import contextlib
import io
import json
import os
import sys
import traceback
from typing import Any

_REPL_TOOL_INPUT_PREFIX = "__GIGA_REPL_TOOL_CALL__:"
_current_request_id: str | None = None
_displayed_matplotlib_figures: set[int] = set()


def _send(payload: dict[str, Any]) -> None:
    payload["request_id"] = _current_request_id
    sys.__stdout__.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    sys.__stdout__.flush()


class _EventTextStream(io.TextIOBase):
    def __init__(self, event_type: str) -> None:
        self._event_type = event_type

    def write(self, text: str) -> int:
        if text:
            _send({"type": self._event_type, "text": text})
        return len(text)

    def flush(self) -> None:
        return None


def _read_message() -> dict[str, Any]:
    raw = sys.__stdin__.readline()
    if not raw:
        raise RuntimeError("Python worker control stream closed")
    try:
        message = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Invalid Python worker control message") from exc
    if not isinstance(message, dict):
        raise RuntimeError("Python worker control message must be an object")
    return message


def _worker_input(prompt: object = "") -> str:
    if not isinstance(prompt, str) or not prompt.startswith(_REPL_TOOL_INPUT_PREFIX):
        raise RuntimeError(
            "Interactive input() is not supported by the Python worker. "
            "Only internal agent tool calls may use input()."
        )

    _send({"type": "input_request", "prompt": prompt, "password": False})
    reply = _read_message()
    if reply.get("type") != "input_reply":
        raise RuntimeError("Expected input_reply from Python worker parent")
    if reply.get("request_id") != _current_request_id:
        raise RuntimeError("Python worker input reply belongs to another request")
    value = reply.get("value", "")
    return value if isinstance(value, str) else str(value)


def _capture_matplotlib_figure(figure: Any) -> None:
    figure_id = id(figure)
    if figure_id in _displayed_matplotlib_figures:
        return
    _displayed_matplotlib_figures.add(figure_id)

    buffer = io.BytesIO()
    figure.savefig(buffer, format="png")
    _send(
        {
            "type": "display_data",
            "data": {"image/png": base64.b64encode(buffer.getvalue()).decode("ascii")},
        }
    )


def _configure_matplotlib() -> None:
    os.environ.setdefault("MPLBACKEND", "Agg")
    try:
        import matplotlib

        matplotlib.use("Agg", force=True)
        import matplotlib.pyplot as pyplot
    except ModuleNotFoundError:
        return

    def show(*_args: Any, **_kwargs: Any) -> None:
        for number in pyplot.get_fignums():
            _capture_matplotlib_figure(pyplot.figure(number))

    pyplot.show = show


def _capture_open_matplotlib_figures() -> None:
    try:
        import matplotlib.pyplot as pyplot
    except ModuleNotFoundError:
        return
    for number in pyplot.get_fignums():
        _capture_matplotlib_figure(pyplot.figure(number))


def _configure_plotly() -> None:
    try:
        import plotly.io as plotly_io
    except ModuleNotFoundError:
        return

    def show(figure: Any, *_args: Any, **_kwargs: Any) -> None:
        _send(
            {
                "type": "display_data",
                "data": {
                    "application/vnd.plotly.v1+json": json.loads(figure.to_json())
                },
            }
        )

    plotly_io.show = show


def _execute_code(code: str, namespace: dict[str, Any]) -> None:
    tree = ast.parse(code, filename="<python-tool>", mode="exec")
    final_expression: ast.Expr | None = None
    if tree.body and isinstance(tree.body[-1], ast.Expr):
        final_expression = tree.body.pop()

    if tree.body:
        exec(compile(tree, "<python-tool>", "exec"), namespace, namespace)
    if final_expression is not None:
        expression = ast.Expression(final_expression.value)
        value = eval(compile(expression, "<python-tool>", "eval"), namespace, namespace)
        if value is not None:
            _send({"type": "result", "data": {"text/plain": repr(value)}})


def _handle_execute(message: dict[str, Any], namespace: dict[str, Any]) -> None:
    global _current_request_id, _displayed_matplotlib_figures

    request_id = message.get("request_id")
    code = message.get("code")
    envs = message.get("envs")
    if not isinstance(request_id, str) or not request_id:
        raise RuntimeError("execute request_id must be a non-empty string")
    if not isinstance(code, str):
        raise RuntimeError("execute code must be a string")
    if envs is not None and not isinstance(envs, dict):
        raise RuntimeError("execute envs must be an object")

    _current_request_id = request_id
    _displayed_matplotlib_figures = set()
    if envs:
        os.environ.update({str(key): str(value) for key, value in envs.items()})

    try:
        with (
            contextlib.redirect_stdout(_EventTextStream("stdout")),
            contextlib.redirect_stderr(_EventTextStream("stderr")),
        ):
            _execute_code(code, namespace)
            _capture_open_matplotlib_figures()
    except BaseException as exc:  # noqa: BLE001
        _send(
            {
                "type": "error",
                "ename": exc.__class__.__name__,
                "evalue": str(exc),
                "traceback": traceback.format_exception(exc),
            }
        )
    finally:
        _send({"type": "done"})
        _current_request_id = None
        _displayed_matplotlib_figures = set()


def main() -> int:
    builtins.input = _worker_input
    _configure_matplotlib()
    _configure_plotly()
    namespace: dict[str, Any] = {"__name__": "__main__", "__builtins__": builtins}

    while True:
        try:
            message = _read_message()
        except RuntimeError:
            return 0
        message_type = message.get("type")
        if message_type == "shutdown":
            return 0
        if message_type != "execute":
            _send(
                {
                    "type": "error",
                    "ename": "WorkerProtocolError",
                    "evalue": f"Unsupported worker command: {message_type!r}",
                    "traceback": [],
                }
            )
            continue
        try:
            _handle_execute(message, namespace)
        except BaseException as exc:  # noqa: BLE001
            _send(
                {
                    "type": "error",
                    "ename": exc.__class__.__name__,
                    "evalue": str(exc),
                    "traceback": traceback.format_exception(exc),
                }
            )


if __name__ == "__main__":
    raise SystemExit(main())
