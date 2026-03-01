import os

GIGA_PREFIX_API = os.getenv("GIGA_AGENT_PREFIX_API", "/agent").rstrip("/")
GIGA_AGENT_FRONTEND_DIR = os.getenv("GIGA_AGENT_FRONTEND_DIR", "").strip() or None


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int, *, min_value: int | None = None) -> int:
    raw = os.getenv(name)
    if raw is None:
        value = default
    else:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = default

    if min_value is not None:
        return max(value, min_value)
    return value


# Enables serving the packaged UI in dev server (combined ASGI wrapper).
GIGA_AGENT_UI = _env_bool("GIGA_AGENT_UI", True)

GIGA_AGENT_SANDBOX_IDLE_SWEEPER_ENABLED = _env_bool(
    "GIGA_AGENT_SANDBOX_IDLE_SWEEPER_ENABLED", True
)
GIGA_AGENT_SANDBOX_IDLE_SWEEPER_INTERVAL_SEC = _env_int(
    "GIGA_AGENT_SANDBOX_IDLE_SWEEPER_INTERVAL_SEC",
    60,
    min_value=10,
)
GIGA_AGENT_SANDBOX_IDLE_SWEEPER_LOCK_KEY = os.getenv(
    "GIGA_AGENT_SANDBOX_IDLE_SWEEPER_LOCK_KEY",
    "sandbox:idle-cleanup:lock",
)
GIGA_AGENT_SANDBOX_IDLE_SWEEPER_LOCK_TTL_SEC = _env_int(
    "GIGA_AGENT_SANDBOX_IDLE_SWEEPER_LOCK_TTL_SEC",
    55,
    min_value=5,
)
GIGA_AGENT_SANDBOX_STARTING_TTL_SEC = _env_int(
    "GIGA_AGENT_SANDBOX_STARTING_TTL_SEC",
    120,
    min_value=10,
)
