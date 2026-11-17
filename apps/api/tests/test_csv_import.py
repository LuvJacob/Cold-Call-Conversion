"""CSV import tests (Lane C)."""

import io
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_csv_import_valid_and_bom(
    client: AsyncClient, auth_headers_seller1: dict[str, str]
) -> None:
    res = await client.post("/v1/lists", headers=auth_headers_seller1, json={"name": "CSV List"})
    list_id = res.json()["id"]

    csv_data = "\ufeffName,Company,Role,Phone,Notes\nJane Doe,Acme Inc,CTO,555-1234,\"Important customer\nSecond line\"\n"
    files = {"file": ("prospects.csv", csv_data.encode("utf-8"), "text/csv")}

    res = await client.post(
        f"/v1/lists/{list_id}/import",
        headers=auth_headers_seller1,
        files=files,
    )
    assert res.status_code == 200
    data = res.json()
    assert len(data["imported"]) == 1
    assert data["imported"][0]["name"] == "Jane Doe"
    assert "Second line" in data["imported"][0]["notes"]
    assert len(data["rejectedRows"]) == 0


@pytest.mark.asyncio
async def test_csv_import_handles_bad_rows_gracefully(
    client: AsyncClient, auth_headers_seller1: dict[str, str]
) -> None:
    res = await client.post("/v1/lists", headers=auth_headers_seller1, json={"name": "CSV List 2"})
    list_id = res.json()["id"]

    csv_data = "Name,Company,Role\nValid Person,Corp,VP\n,Missing Name,Director\nAnother Person,Corp 2,Head of Sales\n"
    files = {"file": ("prospects.csv", csv_data.encode("utf-8"), "text/csv")}

    res = await client.post(
        f"/v1/lists/{list_id}/import",
        headers=auth_headers_seller1,
        files=files,
    )
    assert res.status_code == 200
    data = res.json()
    assert len(data["imported"]) == 2
    assert len(data["rejectedRows"]) == 1
    assert data["rejectedRows"][0]["row"] == 3
