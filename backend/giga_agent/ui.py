from __future__ import annotations

import re
from contextlib import ExitStack
from importlib.resources import as_file, files
from pathlib import Path

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from giga_agent.conf import (
    GIGA_AGENT_FRONTEND_DIR,
    GIGA_AGENT_PREFIX_API,
    GIGA_AGENT_UI_PREFIX,
)
from giga_agent.runtime_config import mount_runtime_config_route
from giga_agent.runtime_config import resolve_ui_base_path


def _resolve_ui_dir(app: FastAPI) -> Path | None:
    override = GIGA_AGENT_FRONTEND_DIR
    if override:
        p = Path(override).expanduser().resolve()
        if p.is_file():
            p = p.parent
        if p.is_dir():
            if (p / "index.html").is_file():
                return p
            if (p / "dist" / "index.html").is_file():
                return p / "dist"

    # Local development fallback: if we're running from the monorepo checkout and
    # `front/dist` exists, serve it directly to avoid requiring UI syncing into
    # `giga_agent/ui_dist`.
    try:
        repo_root = Path(__file__).resolve().parents[2]
        dev_dist = repo_root / "front" / "dist"
        if (dev_dist / "index.html").is_file():
            return dev_dist
    except Exception:
        # Best-effort only; never fail UI mount due to path probing.
        pass

    # Try loading packaged UI via importlib.resources (works even when resources
    # are inside a zip/packed wheel). Keep the context alive for app lifetime.
    try:
        ui_root = files("giga_agent").joinpath("ui_dist")
    except ModuleNotFoundError:
        ui_root = None

    if ui_root is not None and ui_root.is_dir():
        existing: ExitStack | None = getattr(app.state, "_ui_resources_stack", None)
        if existing is not None:
            ui_dir = Path(existing.enter_context(as_file(ui_root)))
            if (ui_dir / "index.html").is_file():
                return ui_dir
        else:
            # Only keep the resource extraction context alive if the UI is valid.
            stack = ExitStack()
            ui_dir = Path(stack.enter_context(as_file(ui_root)))
            if (ui_dir / "index.html").is_file():
                app.state._ui_resources_stack = stack
                return ui_dir
            stack.close()

    # Fallback for editable installs / local development layouts.
    packaged = Path(__file__).resolve().parent / "ui_dist"
    if (packaged / "index.html").is_file():
        return packaged
    return None


def create_ui_app() -> FastAPI:
    app = FastAPI()
    mount_ui(app)
    return app


def _render_index(index: Path, request: Request) -> HTMLResponse:
    html = index.read_text(encoding="utf-8")
    base_path = resolve_ui_base_path(request)
    html = re.sub(
        r'<base\s+href="[^"]*"\s*/?>',
        f'<base href="{base_path}"/>',
        html,
        count=1,
    )
    return HTMLResponse(html)


def mount_ui(app: FastAPI) -> None:
    ui_dir = _resolve_ui_dir(app)
    if ui_dir is None:
        return

    index = ui_dir / "index.html"
    assets_dir = ui_dir / "assets"
    ui_prefix = GIGA_AGENT_UI_PREFIX
    config_path = f"{ui_prefix}/app-config.js" if ui_prefix else "/app-config.js"
    # Reserved paths only matter when UI is mounted at root ("/") and would
    # otherwise swallow API/docs routes.
    reserved_prefixes = (
        {
            GIGA_AGENT_PREFIX_API.lstrip("/"),
            "docs",
            "redoc",
        }
        if not ui_prefix
        else set()
    )
    reserved_exact = {"openapi.json"} if not ui_prefix else set()

    if assets_dir.is_dir():
        assets_mount = f"{ui_prefix}/assets" if ui_prefix else "/assets"
        app.mount(assets_mount, StaticFiles(directory=assets_dir), name="ui-assets")

    mount_runtime_config_route(app, path=config_path)

    def _ui_root(request: Request):
        return _render_index(index, request)

    root_paths = []
    if ui_prefix:
        root_paths.extend([ui_prefix, f"{ui_prefix}/"])
    else:
        root_paths.append("/")
    for root_path in dict.fromkeys(root_paths):
        app.get(root_path, include_in_schema=False)(_ui_root)

    spa_path = f"{ui_prefix}/{{path:path}}" if ui_prefix else "/{path:path}"

    @app.get(spa_path, include_in_schema=False)
    def _ui_spa(path: str, request: Request):
        if reserved_exact and path in reserved_exact:
            raise HTTPException(status_code=404)
        if reserved_prefixes and any(
            path == prefix or path.startswith(f"{prefix}/")
            for prefix in reserved_prefixes
        ):
            raise HTTPException(status_code=404)
        if path:
            candidate = ui_dir / path
            if candidate.is_file():
                return FileResponse(candidate)
        return _render_index(index, request)
