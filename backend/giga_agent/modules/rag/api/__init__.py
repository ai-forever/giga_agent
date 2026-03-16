from fastapi import APIRouter

from giga_agent.modules.rag.api.collections import router as collections_router
from giga_agent.modules.rag.api.documents import router as documents_router

router = APIRouter()
router.include_router(collections_router)
router.include_router(documents_router)

__all__ = ["router", "collections_router", "documents_router"]
