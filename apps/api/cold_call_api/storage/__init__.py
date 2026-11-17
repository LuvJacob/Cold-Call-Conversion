"""Storage layer for Cold Call Conversion backend (Lane C)."""

from cold_call_api.config import settings
from cold_call_api.storage.interface import StorageRepository
from cold_call_api.storage.memory import MemoryStorageRepository

_repo_instance: StorageRepository | None = None


def get_repository() -> StorageRepository:
    """Return the singleton repository instance."""
    global _repo_instance
    if _repo_instance is None:
        if settings.storage_backend == "mongodb" and settings.mongodb_uri:
            # Fallback to MongoDB repository when configured
            from cold_call_api.storage.mongodb import MongoStorageRepository
            _repo_instance = MongoStorageRepository(
                uri=settings.mongodb_uri,
                db_name=settings.mongodb_db_name,
            )
        else:
            _repo_instance = MemoryStorageRepository(seed=True)
    return _repo_instance


def set_repository(repo: StorageRepository) -> None:
    """Explicitly set repository instance (primarily for tests)."""
    global _repo_instance
    _repo_instance = repo
