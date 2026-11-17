"""Contract fixes: workspace shape, 404s, CSV size and messages."""

import re

import pytest
from httpx import AsyncClient

H1 = {"X-Seller-ID": "seller-1"}
H2 = {"X-Seller-ID": "seller-2"}
Z = re.compile(r"^\d{4}-\d{2}-\d{2}T[\d:.]+Z$")
P = {"name": "Jane", "company": "Acme", "role": "CTO", "phone": "", "notes": ""}


@pytest.mark.asyncio
async def test_workspace_has_default_list_and_real_calls(client: AsyncClient) -> None:
    ws = (await client.get("/v1/workspace", headers=H1)).json()
    assert len(ws["lists"]) == 1 and ws["calls"] == []
    lid = ws["lists"][0]["id"]
    pid = (await client.post(f"/v1/lists/{lid}/prospects", headers=H1, json=P)).json()[0]["id"]
    await client.post("/v1/calls", headers=H1, json={"prospectId": pid})
    active = (await client.get("/v1/workspace", headers=H1)).json()["activeCall"]
    assert Z.match(active["startedAt"])
    await client.post("/v1/calls/end", headers=H1, json={"outcome": "follow-up"})
    ws = (await client.get("/v1/workspace", headers=H1)).json()
    assert len(ws["calls"]) == 1
    call = ws["calls"][0]
    assert set(call) == {"prospectId", "startedAt", "endedAt", "outcome"}
    assert call["prospectId"] == pid and call["outcome"] == "follow-up"
    assert Z.match(call["startedAt"]) and Z.match(call["endedAt"])
    # another seller sees none of it
    assert (await client.get("/v1/workspace", headers=H2)).json()["calls"] == []


@pytest.mark.asyncio
async def test_other_sellers_resources_are_404(client: AsyncClient) -> None:
    lid = (await client.post("/v1/lists", headers=H1, json={"name": "L"})).json()["id"]
    await client.post("/v1/lists", headers=H2, json={"name": "mine"})
    pid = (await client.post(f"/v1/lists/{lid}/prospects", headers=H1, json=P)).json()[0]["id"]
    assert (await client.delete(f"/v1/lists/{lid}", headers=H2)).status_code == 404
    assert (await client.patch(f"/v1/prospects/{pid}", headers=H2, json={"name": "x"})).status_code == 404
    assert (await client.delete(f"/v1/prospects/{pid}", headers=H2)).status_code == 404
    assert (await client.post("/v1/calls", headers=H2, json={"prospectId": pid})).status_code == 404
    # active-call conflicts stay 4xx but are not 404
    await client.post("/v1/calls", headers=H1, json={"prospectId": pid})
    assert (await client.delete(f"/v1/prospects/{pid}", headers=H1)).status_code == 409


async def _import(client, lid, content):
    return await client.post(f"/v1/lists/{lid}/import", headers=H1, files={"file": ("x.csv", content, "text/csv")})


@pytest.mark.asyncio
async def test_csv_oversize_is_413(client: AsyncClient) -> None:
    lid = (await client.post("/v1/lists", headers=H1, json={"name": "L"})).json()["id"]
    res = await _import(client, lid, b"name,company,role\n" + b"a" * 1_000_100)
    assert res.status_code == 413


@pytest.mark.asyncio
async def test_csv_error_rows_use_file_lines_and_hide_values(client: AsyncClient) -> None:
    lid = (await client.post("/v1/lists", headers=H1, json={"name": "L"})).json()["id"]
    long_company = "SECRETVALUE" * 30
    csv = f"name,company,role\n\nOk,Co,VP\n\n,Co,VP\nBob,{long_company},VP\nShort,Row\n"
    res = await _import(client, lid, csv.encode())
    assert res.status_code == 200
    rows = {r["row"]: r["message"] for r in res.json()["rejectedRows"]}
    assert set(rows) == {5, 6, 7}
    assert "name is required" in rows[5]
    assert "company is too long" in rows[6]
    assert all("SECRETVALUE" not in m and "input_value" not in m for m in rows.values())
