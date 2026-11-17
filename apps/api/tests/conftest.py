"""Pytest fixtures for backend API tests (Lane C)."""

from typing import AsyncIterator
import pytest
from httpx import ASGITransport, AsyncClient
from cold_call_api.main import app
from cold_call_api.storage import set_repository
from cold_call_api.storage.memory import MemoryStorageRepository


@pytest.fixture(autouse=True)
def reset_storage() -> None:
    """Ensure a clean, isolated repository is used for every test."""
    repo = MemoryStorageRepository(seed=False)
    set_repository(repo)


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """Async HTTP client for testing the FastAPI application."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


@pytest.fixture
def auth_headers_seller1() -> dict[str, str]:
    return {"X-Seller-ID": "seller-1"}


@pytest.fixture
def auth_headers_seller2() -> dict[str, str]:
    return {"X-Seller-ID": "seller-2"}
