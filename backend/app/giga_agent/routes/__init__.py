"""
API Routes для Giga Agent.
"""

from giga_agent.routes.llms import router as llms_router
from giga_agent.routes.sandboxes import router as sandboxes_router
from giga_agent.routes.files import router as files_router
from giga_agent.routes.generators.image import router as generators_router

__all__ = ["llms_router", "sandboxes_router", "files_router", "generators_router"]
