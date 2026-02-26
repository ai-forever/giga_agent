from __future__ import annotations

from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI
from fastapi.openapi.docs import get_swagger_ui_html
from starlette.responses import HTMLResponse

API_PREFIX = "/api"


def _load_langgraph_app():
    import langgraph_api.server as langgraph_server  # imported under patched env

    # Ensure OpenAPI spec has correct server base when the app is mounted by us.
    # NOTE: `set_custom_spec` expects a complete OpenAPI spec; passing partial
    # dicts causes `/openapi.json` to error. We only set the config value used
    # for server URL generation.
    try:
        import langgraph_api.config as langgraph_config

        langgraph_config.MOUNT_PREFIX = "/api"
    except Exception:
        pass

    return langgraph_server.app


def _load_ui_app():
    from giga_agent.ui import create_ui_app

    return create_ui_app()


langgraph_app = _load_langgraph_app()
ui_app = _load_ui_app()


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    async with AsyncExitStack() as stack:
        for sub in (langgraph_app, ui_app):
            ctx = getattr(getattr(sub, "router", None), "lifespan_context", None)
            if ctx is not None:
                await stack.enter_async_context(ctx(sub))

        yield


app = FastAPI(lifespan=_lifespan)


# Provide working docs for LangGraph even when mounted.
@app.get(f"{API_PREFIX}/docs", include_in_schema=False)
async def _langgraph_docs():
    try:
        from langgraph_api.api import DOCS_HTML

        return HTMLResponse(DOCS_HTML.format(mount_prefix=API_PREFIX))
    except Exception:
        return get_swagger_ui_html(
            openapi_url=f"{API_PREFIX}/openapi.json",
            title="LangGraph API",
        )


# Mount LangGraph API under /api.
# Note: keep this mount AFTER the explicit `/api/docs` route above,
# otherwise the mounted app will shadow it.
app.mount("/api", langgraph_app, name="langgraph")


# Mount UI app at root.
app.mount("/", ui_app, name="ui")
