"""FastAPI router for MCP server management (mounted at ``/agent/mcp``).

CRUD endpoints live in ``servers.py`` and OAuth start/callback in ``oauth.py``.
"""

from fastapi import APIRouter

from giga_agent.modules.mcp.api.oauth import router as oauth_router
from giga_agent.modules.mcp.api.servers import router as servers_router

router = APIRouter()
router.include_router(servers_router)
router.include_router(oauth_router)

__all__ = ["router"]
