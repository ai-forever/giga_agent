from __future__ import annotations

import logging as stdlib_logging
import os
import sys

import structlog


_SUPPRESSED_LOGGER_PREFIXES: tuple[str, ...] = ("langgraph_runtime_inmem",)
_SUPPRESSED_MESSAGE_SUBSTRINGS: tuple[str, ...] = (
    "Heads up: You've set --allow-blocking",
)


class _SuppressNoisyExternalWarnings(stdlib_logging.Filter):
    def filter(self, record: stdlib_logging.LogRecord) -> bool:  # noqa: A003
        name = getattr(record, "name", "") or ""
        if not name.startswith(_SUPPRESSED_LOGGER_PREFIXES):
            return True
        try:
            msg = record.getMessage()
        except Exception:
            msg = ""
        return not any(substr in msg for substr in _SUPPRESSED_MESSAGE_SUBSTRINGS)


def _ensure_cli_filters(handler: stdlib_logging.Handler) -> None:
    if any(isinstance(f, _SuppressNoisyExternalWarnings) for f in handler.filters):
        return
    handler.addFilter(_SuppressNoisyExternalWarnings())


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)


def _is_truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _resolve_log_format() -> str:
    """
    Returns: "pretty" | "json"
    """
    fmt = (os.getenv("GIGA_AGENT_LOG_FORMAT") or "").strip().lower()
    if fmt in {"json", "pretty"}:
        return fmt
    if _is_truthy(os.getenv("GIGA_AGENT_LOG_JSON")):
        return "json"
    return "pretty"


def setup_cli_logging(level: str | int = "INFO") -> None:
    """
    CLI-oriented logging config:
    - structlog everywhere (our code)
    - Rich-formatted, colorful console output (when available)
    - pretty, multiline tracebacks on .exception(...) / exc_info
    - suppress noisy external loggers by default

    Env toggles:
    - GIGA_AGENT_LOG_FORMAT=pretty|json
    - GIGA_AGENT_LOG_JSON=1 (force json)
    """
    root = stdlib_logging.getLogger()
    desired_format = _resolve_log_format()

    # Idempotent: if already configured with our handler, just update levels.
    for h in root.handlers:
        if getattr(h, "_giga_agent_cli_handler", False):
            if getattr(h, "_giga_agent_cli_format", None) == desired_format:
                _ensure_cli_filters(h)
                root.setLevel(stdlib_logging.WARNING)
                stdlib_logging.getLogger("giga_agent").setLevel(str(level).upper())
                return
            break

    if desired_format == "json":
        handler = stdlib_logging.StreamHandler(sys.stdout)
        handler._giga_agent_cli_handler = True  # type: ignore[attr-defined]
        handler._giga_agent_cli_format = "json"  # type: ignore[attr-defined]
        _ensure_cli_filters(handler)
        handler.setFormatter(stdlib_logging.Formatter("%(message)s"))
        renderer = structlog.processors.JSONRenderer(sort_keys=True, ensure_ascii=False)
        processors = [
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.UnicodeDecoder(),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ]
    else:
        try:
            from rich.console import Console
            from rich.logging import RichHandler
        except Exception:
            # Fallback: plain stdlib logging + structlog console renderer.
            stdlib_logging.basicConfig(level=str(level).upper(), stream=sys.stdout)
            for h in stdlib_logging.getLogger().handlers:
                _ensure_cli_filters(h)
            structlog.configure(
                processors=[
                    structlog.stdlib.filter_by_level,
                    structlog.stdlib.add_logger_name,
                    structlog.stdlib.add_log_level,
                    structlog.processors.TimeStamper(fmt="iso"),
                    structlog.processors.UnicodeDecoder(),
                    structlog.processors.StackInfoRenderer(),
                    structlog.processors.format_exc_info,
                    structlog.dev.ConsoleRenderer(colors=False),
                ],
                logger_factory=structlog.stdlib.LoggerFactory(),
                wrapper_class=structlog.stdlib.BoundLogger,
                cache_logger_on_first_use=True,
            )
            return

        handler = RichHandler(
            console=Console(file=sys.stdout, stderr=False),
            rich_tracebacks=True,
            markup=True,
            show_time=True,
            show_level=True,
            show_path=False,
            log_time_format="%H:%M:%S",
        )
        handler._giga_agent_cli_handler = True  # type: ignore[attr-defined]
        handler._giga_agent_cli_format = "pretty"  # type: ignore[attr-defined]
        _ensure_cli_filters(handler)
        handler.setFormatter(stdlib_logging.Formatter("%(message)s"))
        # Important: render to a single human-readable line BEFORE stdlib logging,
        # so uvicorn/dictConfig can't force dict/JSON formatting for our records.
        # RichHandler is responsible for coloring; keep structlog renderer plain.
        renderer = structlog.dev.ConsoleRenderer(colors=False, sort_keys=True)
        processors = [
            structlog.stdlib.filter_by_level,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ]

    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(stdlib_logging.WARNING)
    stdlib_logging.getLogger("giga_agent").setLevel(str(level).upper())
    # Allow Alembic migration logs to be visible in the same style.
    stdlib_logging.getLogger("alembic").setLevel(str(level).upper())
    stdlib_logging.getLogger("alembic.runtime").setLevel(str(level).upper())
    stdlib_logging.getLogger("alembic.runtime.migration").setLevel(str(level).upper())

    structlog.configure(
        processors=processors,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

