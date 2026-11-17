"""Application configuration for Cold Call Conversion API (Lane C)."""

import os
from pydantic import BaseModel, ConfigDict


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
    brief_cache_days: int = int(os.getenv("BRIEF_CACHE_DAYS", "30"))
    max_research_attempts: int = int(os.getenv("MAX_RESEARCH_ATTEMPTS", "3"))
    research_lease_seconds: int = int(os.getenv("RESEARCH_LEASE_SECONDS", "90"))
    research_timeout_seconds: int = int(os.getenv("RESEARCH_TIMEOUT_SECONDS", "60"))


settings = Settings()
