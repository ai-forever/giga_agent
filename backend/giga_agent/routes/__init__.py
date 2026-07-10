"""
API Routes для Giga Agent.
"""

from fastapi import APIRouter
from giga_agent.conf import GIGA_AGENT_PREFIX_API, GIGA_AGENT_RUNTIME_LOCAL
from giga_agent.routes.agent import router as agent_router
from giga_agent.routes.channels import router as channels_router
from giga_agent.routes.connectors import router as connectors_router
from giga_agent.routes.embeddings import router as embeddings_router
from giga_agent.routes.files import router as files_router
from giga_agent.routes.generators import router as generators_router
from giga_agent.routes.groups import router as groups_router
from giga_agent.routes.integrations import router as integrations_router
from giga_agent.routes.llms import router as llms_router
from giga_agent.routes.models_config import router as models_config_router
from giga_agent.routes.rate_limits import router as rate_limits_router
from giga_agent.routes.resource_permissions import router as resource_permissions_router
from giga_agent.routes.sandbox_redirect import router as sandbox_redirect_router
from giga_agent.routes.sandboxes import router as sandboxes_router
from giga_agent.routes.search_engines import router as search_engines_router
from giga_agent.routes.stt import router as stt_router
from giga_agent.routes.threads import router as threads_router

router = APIRouter(prefix=GIGA_AGENT_PREFIX_API)
router.include_router(agent_router)
router.include_router(channels_router)
router.include_router(connectors_router)
router.include_router(embeddings_router)
router.include_router(llms_router)
router.include_router(models_config_router)
router.include_router(sandboxes_router)
router.include_router(sandbox_redirect_router)
router.include_router(files_router)
router.include_router(generators_router)
router.include_router(search_engines_router)
router.include_router(groups_router)
router.include_router(integrations_router)
router.include_router(rate_limits_router)
router.include_router(resource_permissions_router)
router.include_router(stt_router)
router.include_router(threads_router)
if GIGA_AGENT_RUNTIME_LOCAL:
    from giga_agent.routes.local_functions import router as local_functions_router

    router.include_router(local_functions_router)

__all__ = [
    "router",
    "agent_router",
    "channels_router",
    "connectors_router",
    "embeddings_router",
    "llms_router",
    "models_config_router",
    "sandboxes_router",
    "sandbox_redirect_router",
    "files_router",
    "generators_router",
    "search_engines_router",
    "groups_router",
    "integrations_router",
    "rate_limits_router",
    "resource_permissions_router",
    "stt_router",
    "threads_router",
]
