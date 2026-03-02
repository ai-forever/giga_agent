from __future__ import annotations

from contextlib import ExitStack
from importlib.resources import as_file, files
from pathlib import Path

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from giga_agent.conf import GIGA_AGENT_FRONTEND_DIR, GIGA_AGENT_PREFIX_API


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
                app.add_event_handler("shutdown", stack.close)
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


def mount_ui(app: FastAPI) -> None:
    ui_dir = _resolve_ui_dir(app)
    if ui_dir is None:
        return

    index = ui_dir / "index.html"
    assets_dir = ui_dir / "assets"
    reserved_prefixes = {
        GIGA_AGENT_PREFIX_API.lstrip("/"),
        "docs",
        "redoc",
    }
    reserved_exact = {"openapi.json"}

    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="ui-assets")

    @app.get("/", include_in_schema=False)
    def _ui_root():
        return FileResponse(index)

    @app.get("/{path:path}", include_in_schema=False)
    def _ui_spa(path: str):
        if path in reserved_exact or any(
            path == prefix or path.startswith(f"{prefix}/") for prefix in reserved_prefixes
        ):
            raise HTTPException(status_code=404)
        if path:
            candidate = ui_dir / path
            if candidate.is_file():
                return FileResponse(candidate)
        return FileResponse(index)
