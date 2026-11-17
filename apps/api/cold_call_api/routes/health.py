"""Health check routes (Lane C)."""

from fastapi import APIRouter
from cold_call_api.config import settings

router = APIRouter(tags=["Health"])


@router.get("/healthz")
async def health_check() -> dict[str, str]:
    """Liveness and readiness probe for IBM Code Engine and load balancers."""
    return {
        "status": "healthy",
        "app": settings.app_name,
        "version": settings.app_version,
    }
