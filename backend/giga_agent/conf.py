import os

GIGA_PREFIX_API = os.getenv("GIGA_AGENT_PREFIX_API", "/agent").rstrip("/")
GIGA_AGENT_FRONTEND_DIR = os.getenv("GIGA_AGENT_FRONTEND_DIR", "").strip() or None


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


# Enables serving the packaged UI in dev server (combined ASGI wrapper).
GIGA_AGENT_UI = _env_bool("GIGA_AGENT_UI", True)
