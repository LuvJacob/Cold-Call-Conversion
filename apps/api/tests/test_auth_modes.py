"""Authentication mode tests: signed JWTs only in jwt mode, header trust only in dev (Lane C)."""

import base64
import json
import time

import jwt
import pytest
from httpx import AsyncClient

from cold_call_api.config import settings

SECRET = "unit-test-secret-with-at-least-32-bytes!!"


def _token(sub: str = "seller-a", *, secret: str = SECRET, exp_offset: int = 300, alg: str = "HS256") -> str:
    claims: dict[str, object] = {"sub": sub}
    if exp_offset is not None:
        claims["exp"] = int(time.time()) + exp_offset
    return jwt.encode(claims, secret, algorithm=alg)


@pytest.fixture
def jwt_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "auth_mode", "jwt")
    monkeypatch.setattr(settings, "jwt_secret", SECRET)
    monkeypatch.setattr(settings, "jwt_algorithm", "HS256")


@pytest.mark.asyncio
async def test_jwt_mode_accepts_valid_token(client: AsyncClient, jwt_mode: None) -> None:
    res = await client.post("/v1/lists", headers={"Authorization": f"Bearer {_token()}"}, json={"name": "Mine"})
    assert res.status_code == 201
    assert res.json()["sellerId"] == "seller-a"


@pytest.mark.asyncio
async def test_jwt_mode_ignores_x_seller_id_header(client: AsyncClient, jwt_mode: None) -> None:
    res = await client.get("/v1/lists", headers={"X-Seller-ID": "victim"})
    assert res.status_code == 401
    # A valid token still wins over a spoofed header
    res = await client.post(
        "/v1/lists",
        headers={"Authorization": f"Bearer {_token('seller-a')}", "X-Seller-ID": "victim"},
        json={"name": "Mine"},
    )
    assert res.json()["sellerId"] == "seller-a"


@pytest.mark.asyncio
async def test_jwt_mode_rejects_forged_unsigned_and_wrong_secret_tokens(
    client: AsyncClient, jwt_mode: None
) -> None:
    def b64(obj: dict[str, object]) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()

    forged_payload = f"{b64({'alg': 'HS256', 'typ': 'JWT'})}.{b64({'sub': 'victim', 'exp': int(time.time()) + 300})}.bogus"
    alg_none = f"{b64({'alg': 'none', 'typ': 'JWT'})}.{b64({'sub': 'victim', 'exp': int(time.time()) + 300})}."
    for bad in (forged_payload, alg_none, _token("victim", secret="a-different-secret-of-sufficient-length!!")):
        res = await client.get("/v1/lists", headers={"Authorization": f"Bearer {bad}"})
        assert res.status_code == 401


@pytest.mark.asyncio
async def test_jwt_mode_rejects_expired_and_missing_exp(client: AsyncClient, jwt_mode: None) -> None:
    expired = _token(exp_offset=-60)
    no_exp = jwt.encode({"sub": "seller-a"}, SECRET, algorithm="HS256")
    for bad in (expired, no_exp, "not-a-jwt", "victim"):
        res = await client.get("/v1/lists", headers={"Authorization": f"Bearer {bad}"})
        assert res.status_code == 401


@pytest.mark.asyncio
async def test_jwt_mode_without_secret_fails_closed(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "auth_mode", "jwt")
    monkeypatch.setattr(settings, "jwt_secret", "")
    res = await client.get("/v1/lists", headers={"Authorization": f"Bearer {_token()}"})
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_unknown_auth_mode_fails_closed(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "auth_mode", "oops")
    res = await client.get("/v1/lists", headers={"X-Seller-ID": "seller-1"})
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_dev_mode_uses_header_and_default(client: AsyncClient) -> None:
    res = await client.post("/v1/lists", headers={"X-Seller-ID": "dev-1"}, json={"name": "A"})
    assert res.json()["sellerId"] == "dev-1"
    res = await client.post("/v1/lists", json={"name": "B"})
    assert res.json()["sellerId"] == settings.default_dev_seller_id
