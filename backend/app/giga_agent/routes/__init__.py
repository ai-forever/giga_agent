"""
API Routes для Giga Agent.
"""

from fastapi import APIRouter

from giga_agent.routes.connectors import router as connectors_router
from giga_agent.routes.files import router as files_router
from giga_agent.routes.generators import router as generators_router
from giga_agent.routes.llms import router as llms_router
from giga_agent.routes.sandboxes import router as sandboxes_router
from giga_agent.routes.search_engines import router as search_engines_router

router = APIRouter()
router.include_router(connectors_router)
router.include_router(llms_router)
router.include_router(sandboxes_router)
router.include_router(files_router)
router.include_router(generators_router)
router.include_router(search_engines_router)

__all__ = [
    "router",
    "connectors_router",
    "llms_router",
    "sandboxes_router",
    "files_router",
    "generators_router",
    "search_engines_router",
]
