"""Local MCP config (``.giga_agent/mcp.json``) — only active in local runtime.

Standard MCP config schema::

    {
      "mcpServers": {
        "filesystem": {"command": "npx", "args": ["-y", "..."], "env": {...}},
        "myremote":   {"url": "https://...", "headers": {"Authorization": "..."}}
      }
    }

Each entry ``<ns>`` becomes a virtual server named ``local_<ns>`` — never stored
in the DB. stdio servers are launched as subprocesses (impossible in Docker),
http servers are reached directly.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
from pathlib import Path

from giga_agent.conf import get_settings
from giga_agent.core.logging import get_logger
from giga_agent.core.paths import giga_agent_dir
from giga_agent.modules.mcp.resolved import ResolvedServer
from giga_agent.utils.mcp_host import is_local_url

logger = get_logger(__name__)

LOCAL_PREFIX = "local_"

_STUB = {
    "mcpServers": {
    }
}


def is_local_runtime() -> bool:
    return bool(get_settings().giga_agent_runtime_local)


def local_config_path() -> Path:
    return giga_agent_dir() / "mcp.json"


def _config_sig(cfg: dict) -> str:
    """Stable hash of a server's config entry; changes iff the entry is edited."""
    raw = json.dumps(cfg, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _to_resolved(ns: str, cfg: dict) -> ResolvedServer | None:
    name = f"{LOCAL_PREFIX}{ns}"
    sig = _config_sig(cfg)
    if cfg.get("command"):
        return ResolvedServer(
            name=name,
            transport="stdio",
            is_local=True,
            cache_id=f"local:{ns}",
            source="file",
            config_sig=sig,
            command=str(cfg["command"]),
            args=[str(a) for a in (cfg.get("args") or [])],
            env={str(k): str(v) for k, v in (cfg.get("env") or {}).items()} or None,
            cwd=cfg.get("cwd"),
        )
    if cfg.get("url"):
        url = str(cfg["url"])
        return ResolvedServer(
            name=name,
            transport="http",
            is_local=is_local_url(url),
            cache_id=f"local:{ns}",
            source="file",
            config_sig=sig,
            url=url,
            headers=cfg.get("headers") or None,
        )
    logger.warning("MCP local server '%s' has neither 'command' nor 'url'; skipped", ns)
    return None


def load_local_servers() -> dict[str, ResolvedServer]:
    """Parse the local config into ``{name: ResolvedServer}`` (empty if not local)."""
    if not is_local_runtime():
        return {}
    path = local_config_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to read %s: %s", path, exc)
        return {}

    servers: dict[str, ResolvedServer] = {}
    for ns, cfg in (data.get("mcpServers") or {}).items():
        if not isinstance(cfg, dict):
            continue
        resolved = _to_resolved(str(ns), cfg)
        if resolved is not None:
            servers[resolved.name] = resolved
    return servers


# Локальные серверы не лежат в БД, поэтому флаг «выключен» храним per-user
# в user.settings — по аналогии с user.settings["disabledModules"]. Ключ —
# имя локального сервера (``local_<ns>``).
LOCAL_DISABLED_SETTINGS_KEY = "disabledLocalServers"


def disabled_local_names(settings: dict | None) -> set[str]:
    """Имена локальных серверов, выключенных пользователем (из user.settings)."""
    if not settings:
        return set()
    raw = settings.get(LOCAL_DISABLED_SETTINGS_KEY) or []
    if not isinstance(raw, list):
        return set()
    return {str(x) for x in raw if x}


def ensure_local_config_file() -> Path:
    """Create a stub ``mcp.json`` if missing; return its path."""
    path = local_config_path()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(_STUB, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    return path


def open_local_config_in_editor() -> Path:
    """Open ``mcp.json`` in the OS default editor (local runtime only)."""
    path = ensure_local_config_file()
    system = platform.system()
    if system == "Darwin":
        subprocess.Popen(["open", str(path)])
    elif system == "Windows":
        os.startfile(str(path))  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", str(path)])
    return path
