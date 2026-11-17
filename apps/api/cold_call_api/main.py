"""FastAPI entry point and application factory (Lane C)."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from cold_call_api.config import settings
from cold_call_api.routes import calls, health, lists, prospects, research

# Structured logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("cold_call_api")


SAFE_DEV_ENVIRONMENTS = ("development", "local", "test")


def check_auth_safety() -> None:
    """Refuse to run header-trusting dev auth outside a development environment."""
    if settings.auth_mode == "dev" and settings.environment.strip().lower() not in SAFE_DEV_ENVIRONMENTS:
        raise RuntimeError(
            f"AUTH_MODE=dev is not allowed when ENVIRONMENT={settings.environment!r}. "
            "Set AUTH_MODE=jwt (with JWT_SECRET) or ENVIRONMENT=development."
        )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    check_auth_safety()
    logger.info("Starting %s v%s in %s mode", settings.app_name, settings.app_version, settings.environment)
    yield
    logger.info("Shutting down %s", settings.app_name)


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Backend API and research worker service for Cold Call Conversion (Lane C).",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# CORS configuration for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routes
app.include_router(health.router)
app.include_router(lists.router)
app.include_router(prospects.router)
app.include_router(research.router)
app.include_router(calls.router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Security rule: Never expose internal stack traces or database errors to client."""
    logger.exception("Unhandled server error processing %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An internal server error occurred. Please try again later."},
    )


def create_app() -> FastAPI:
    return app
