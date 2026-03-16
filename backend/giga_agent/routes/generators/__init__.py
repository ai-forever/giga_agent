from fastapi import APIRouter

from giga_agent.routes.generators.image import router as image_router

router = APIRouter(prefix="/generators")
router.include_router(image_router)

__all__ = ["router", "image_router"]
