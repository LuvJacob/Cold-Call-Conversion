"""Application configuration for Cold Call Conversion API (Lane C)."""

import logging
import os
from pydantic import BaseModel, ConfigDict

logger = logging.getLogger("cold_call_api.config")

RESEARCH_MODES = ("", "free", "live")
_warned_modes: set[str] = set()


def research_mode(raw: str | None = None) -> str:
    """Normalised RESEARCH_PROVIDERS: "", "free" or "live". Read at call time so tests and
    deployments can change it; an unknown value is treated as unset with a one-time warning."""
    value = (os.getenv("RESEARCH_PROVIDERS", "") if raw is None else raw).strip().lower()
    if value in RESEARCH_MODES:
        return value
    if value not in _warned_modes:
        _warned_modes.add(value)
        logger.warning("Unknown RESEARCH_PROVIDERS value %r; treating as unset (allowed: free, live).", value[:20])
    return ""


class Settings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    app_name: str = "Cold Call Conversion API"
    app_version: str = "0.1.0"
    environment: str = os.getenv("ENVIRONMENT", "development")
    host: str = os.getenv("HOST", "127.0.0.1")
    port: int = int(os.getenv("PORT", "8000"))
    storage_backend: str = os.getenv("STORAGE_BACKEND", "memory")  # "memory" | "mongodb"
    mongodb_uri: str = os.getenv("MONGODB_URI", "")
    mongodb_db_name: str = os.getenv("MONGODB_DB_NAME", "cold_call_conversion")
    auth_mode: str = os.getenv("AUTH_MODE", "dev")  # "dev" | "jwt"
    jwt_secret: str = os.getenv("JWT_SECRET", "")
    jwt_algorithm: str = os.getenv("JWT_ALGORITHM", "HS256")
    default_dev_seller_id: str = os.getenv("DEFAULT_DEV_SELLER_ID", "seller-default")
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]
    brief_cache_days: int = int(os.getenv("BRIEF_CACHE_DAYS", "7"))
    research_lease_seconds: int = int(os.getenv("RESEARCH_LEASE_SECONDS", "90"))
    research_timeout_seconds: int = int(os.getenv("RESEARCH_TIMEOUT_SECONDS", "60"))
    research_max_attempts: int = int(os.getenv("RESEARCH_MAX_ATTEMPTS", "3"))
    research_retry_base_seconds: float = float(os.getenv("RESEARCH_RETRY_BASE_SECONDS", "5"))


settings = Settings()
