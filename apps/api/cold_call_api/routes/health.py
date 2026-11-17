"""Health check routes (Lane C)."""

import os

from typing import Annotated

from fastapi import APIRouter, Depends
from cold_call_api.auth import get_current_seller_id
from cold_call_api.config import research_mode, settings

router = APIRouter(tags=["Health"])


@router.get("/healthz")
async def health_check() -> dict[str, str]:
    """Liveness and readiness probe for IBM Code Engine and load balancers."""
    return {
        "status": "healthy",
        "app": settings.app_name,
        "version": settings.app_version,
    }


def _set(name: str) -> bool:
    return bool(os.getenv(name, "").strip())


@router.get("/healthz/research")
async def research_health(_seller_id: Annotated[str, Depends(get_current_seller_id)]) -> dict[str, str | bool]:
    """Which research providers are configured. Booleans and names only, never key values. Requires auth like the research routes."""
    llm = os.getenv("LLM_PROVIDER", "").strip().lower()
    llm = llm if llm in ("watsonx", "gemini") else "watsonx"
    return {
        "mode": research_mode() or "default",
        "tavily": _set("TAVILY_API_KEY"),
        "pdl": _set("PDL_API_KEY"),
        "llm": llm,
        "watsonx": all(_set(n) for n in ("WATSONX_API_KEY", "WATSONX_URL", "WATSONX_PROJECT_ID"))
        and os.getenv("WATSONX_URL", "").strip().lower().startswith("https://"),  # same rule as the factory
        "gemini": _set("GEMINI_API_KEY"),
    }
