"""Call session management tests (Lane C)."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_call_lifecycle_and_idempotency(
    client: AsyncClient, auth_headers_seller1: dict[str, str]
) -> None:
    # Setup list and prospect
    res = await client.post("/v1/lists", headers=auth_headers_seller1, json={"name": "Calling List"})
    list_id = res.json()["id"]

    res = await client.post(
        f"/v1/lists/{list_id}/prospects",
        headers=auth_headers_seller1,
        json={"name": "Sam Rivera", "company": "Cedar Health", "role": "IT Ops", "phone": "123", "notes": ""},
    )
    prospect_id = res.json()[0]["id"]

    # Connect call
    res = await client.post("/v1/calls", headers=auth_headers_seller1, json={"prospectId": prospect_id})
    assert res.status_code == 201
    assert res.json()["prospectId"] == prospect_id

    # Second active call should be rejected
    res = await client.post("/v1/calls", headers=auth_headers_seller1, json={"prospectId": prospect_id})
    assert res.status_code == 400

    # Ending call with idempotency key
    headers_with_idem = {**auth_headers_seller1, "Idempotency-Key": "call-key-123"}
    res = await client.post("/v1/calls/end", headers=headers_with_idem, json={"outcome": "completed"})
    assert res.status_code == 200
    call_res = res.json()
    assert call_res["outcome"] == "completed"

    # Repeated request with same idempotency key returns completed call
    res = await client.post("/v1/calls/end", headers=headers_with_idem, json={"outcome": "completed"})
    assert res.status_code == 200
    assert res.json()["id"] == call_res["id"]

    # Prospect should now be in called status
    res = await client.get(f"/v1/lists/{list_id}/prospects", headers=auth_headers_seller1)
    p = res.json()[0]
    assert p["callStatus"] == "called"
    assert p["outcome"] == "completed"

    # Reset call status
    res = await client.post(f"/v1/calls/reset/{prospect_id}", headers=auth_headers_seller1)
    assert res.status_code == 200
    res = await client.get(f"/v1/lists/{list_id}/prospects", headers=auth_headers_seller1)
    assert res.json()[0]["callStatus"] == "ready"
