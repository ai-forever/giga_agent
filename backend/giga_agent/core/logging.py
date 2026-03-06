from __future__ import annotations

import logging as stdlib_logging
import sys

import structlog
from giga_agent.conf import get_settings


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
    settings = get_settings()
    fmt = (settings.giga_agent_log_format or "").strip().lower()
    if fmt in {"json", "pretty"}:
        return fmt
    if settings.giga_agent_log_json:
        return "json"
    return "pretty"


def setup_cli_logging(level: str | int = "INFO") -> None:
    """
    CLI-oriented logging config:
    - structlog everywhere (our code)
    - colorful console output (single-line records; no hard wrapping)
    - multiline tracebacks on .exception(...) / exc_info
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
        handler = stdlib_logging.StreamHandler(sys.stdout)
        handler._giga_agent_cli_handler = True  # type: ignore[attr-defined]
        handler._giga_agent_cli_format = "pretty"  # type: ignore[attr-defined]
        _ensure_cli_filters(handler)
        handler.setFormatter(
            stdlib_logging.Formatter(
                fmt="%(asctime)s %(levelname)-8s %(message)s",
                datefmt="%H:%M:%S",
            )
        )
        # Important: render to a single human-readable line BEFORE stdlib logging,
        # so uvicorn/dictConfig can't force dict/JSON formatting for our records.
        renderer = structlog.dev.ConsoleRenderer(colors=True, sort_keys=True)
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
