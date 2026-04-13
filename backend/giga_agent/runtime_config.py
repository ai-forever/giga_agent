from __future__ import annotations

import json
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi import Request
from fastapi.responses import Response

from giga_agent.conf import (
    GIGA_AGENT_BASE_URL,
    GIGA_AGENT_PREFIX_API,
    GIGA_AGENT_SKIP_ONBOARDING,
    GIGA_AGENT_UI_PREFIX,
)


def normalize_base_path(value: str | None) -> str:
    if not value:
        return "/"
    stripped = value.strip()
    if not stripped or stripped == "/":
        return "/"
    normalized = f"/{stripped.strip('/')}"
    return f"{normalized}/"


def join_prefixed_path(base_path: str, suffix: str) -> str:
    normalized_base = normalize_base_path(base_path)
    cleaned_suffix = suffix.lstrip("/")
    if normalized_base == "/":
        return f"/{cleaned_suffix}"
    return f"{normalized_base.rstrip('/')}/{cleaned_suffix}"


def resolve_ui_base_path(request: Request) -> str:
    configured_base_url = GIGA_AGENT_BASE_URL
    if configured_base_url:
        return normalize_base_path(urlsplit(configured_base_url).path)

    root_path = normalize_base_path(request.scope.get("root_path") or "/")
    ui_prefix = normalize_base_path(GIGA_AGENT_UI_PREFIX)
    if ui_prefix == "/":
        return root_path
    return join_prefixed_path(root_path, ui_prefix)


def build_runtime_config(request: Request) -> dict[str, str | bool]:
    base_path = resolve_ui_base_path(request)
    api_base_path = join_prefixed_path(base_path, "api")
    config = {
        "basePath": base_path,
        "apiBasePath": api_base_path,
        "apiAgentBasePath": f"{api_base_path}{GIGA_AGENT_PREFIX_API}",
        "skipOnboarding": GIGA_AGENT_SKIP_ONBOARDING,
    }
    if GIGA_AGENT_BASE_URL:
        config["baseUrl"] = GIGA_AGENT_BASE_URL
    return config


def _render_runtime_config(request: Request) -> Response:
    payload = json.dumps(build_runtime_config(request), ensure_ascii=True)
    return Response(
        f"window.__GIGA_AGENT_CONFIG__ = {payload};",
        media_type="application/javascript",
    )


def mount_runtime_config_route(app: FastAPI, path: str = "/app-config.js") -> None:
    normalized_path = path if path.startswith("/") else f"/{path}"
    mounted_paths: set[str] = getattr(app.state, "_runtime_config_paths", set())
    if normalized_path in mounted_paths:
        return

    @app.get(normalized_path, include_in_schema=False)
    def _app_config(request: Request) -> Response:
        return _render_runtime_config(request)

    mounted_paths.add(normalized_path)
    app.state._runtime_config_paths = mounted_paths
