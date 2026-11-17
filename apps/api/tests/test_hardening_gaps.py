"""Adversarial gap tests: concurrency, stale results, JWT edge cases, hostile CSVs."""

import asyncio
import base64
import json
import threading
import time

import jwt
import pytest
from httpx import AsyncClient

from cold_call_api.config import settings
from cold_call_api.services import worker
from cold_call_api.storage import get_repository

SECRET = "unit-test-secret-with-at-least-32-bytes!!"
H1 = {"X-Seller-ID": "seller-1"}
H2 = {"X-Seller-ID": "seller-2"}


async def _prospect(client, headers=H1, company="Unknown Co", name="Zed Nobody"):
    lid = (await client.post("/v1/lists", headers=headers, json={"name": "L"})).json()["id"]
    res = await client.post(
        f"/v1/lists/{lid}/prospects",
        headers=headers,
        json={"name": name, "company": company, "role": "VP", "phone": "", "notes": ""},
    )
    return lid, res.json()[0]["id"]


# ---------- concurrency ----------

@pytest.mark.asyncio
async def test_concurrent_enqueue_creates_one_job(client: AsyncClient) -> None:
    _, pid = await _prospect(client)
    repo = get_repository()
    results = await asyncio.gather(*[repo.enqueue_research_jobs("seller-1", [pid]) for _ in range(10)])
    assert sum(len(r) for r in results) == 1


@pytest.mark.asyncio
async def test_duplicate_ids_in_one_request_create_one_job(client: AsyncClient) -> None:
    _, pid = await _prospect(client)
    res = await client.post("/v1/research", headers=H1, json={"prospectIds": [pid, pid, pid]})
    assert res.status_code == 202
    assert len(res.json()) == 1


@pytest.mark.asyncio
async def test_edit_during_running_research_discards_stale_result(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, pid = await _prospect(client, company="Northwind Logistics Sample Inc")
    repo = get_repository()
    started, release = threading.Event(), threading.Event()
    real = worker.run_research

    def slow(*a, **kw):
        started.set()
        release.wait(5)
        return real(*a, **kw)

    monkeypatch.setattr(worker, "run_research", slow)
    jobs = await repo.enqueue_research_jobs("seller-1", [pid])
    task = asyncio.create_task(worker.process_job(repo, jobs[0]))
    await asyncio.to_thread(started.wait, 5)
    res = await client.patch(f"/v1/prospects/{pid}", headers=H1, json={"role": "CEO"})
    assert res.status_code == 200
    release.set()
    await task
    p = await repo.get_prospect("seller-1", pid)
    assert p.revision == 1
    assert p.brief is None, "stale brief overwrote edited prospect"
    assert p.researchStatus.value == "not-started"


@pytest.mark.asyncio
async def test_pipeline_exception_marks_failed_without_leaking(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, pid = await _prospect(client)
    repo = get_repository()

    def boom(*a, **kw):
        raise RuntimeError("secret-internal-detail")

    monkeypatch.setattr(worker, "run_research", boom)
    jobs = await repo.enqueue_research_jobs("seller-1", [pid])
    await worker.process_job(repo, jobs[0])
    body = (await client.get(f"/v1/prospects/{pid}/research", headers=H1)).json()
    assert body["researchStatus"] == "failed"
    assert body["brief"] is None
    assert "secret-internal-detail" not in json.dumps(body)


@pytest.mark.asyncio
async def test_no_fixture_prospect_is_partial_with_no_facts(client: AsyncClient) -> None:
    _, pid = await _prospect(client)
    await client.post("/v1/research", headers=H1, json={"prospectIds": [pid]})
    body = (await client.get(f"/v1/prospects/{pid}/research", headers=H1)).json()
    assert body["researchStatus"] == "partial"
    assert body["brief"]["facts"] == [] and body["brief"]["sources"] == []
    assert body["brief"]["uncertainty"]


@pytest.mark.asyncio
async def test_brief_matches_frontend_brief_schema_shape(client: AsyncClient) -> None:
    _, pid = await _prospect(client, company="Northwind Logistics Sample Inc")
    await client.post("/v1/research", headers=H1, json={"prospectIds": [pid]})
    b = (await client.get(f"/v1/prospects/{pid}/research", headers=H1)).json()["brief"]
    assert b["mode"] == "demo"
    assert set(b) >= {"preparedAt", "summary", "facts", "sources", "questions", "roleContext", "uncertainty"}
    ids = {s["id"] for s in b["sources"]}
    for f in b["facts"]:
        assert set(f) >= {"label", "text", "sourceIds"} and f["sourceIds"], "fact without citation"
        assert set(f["sourceIds"]) <= ids
    for s in b["sources"]:
        assert s["url"] is None or s["url"].startswith(("http://", "https://"))
    for q in b["questions"]:
        assert set(q) >= {"text", "basis"}


# ---------- tenancy ----------

@pytest.mark.asyncio
async def test_cross_seller_cannot_read_modify_research_or_call(client: AsyncClient) -> None:
    lid, pid = await _prospect(client)
    await client.post("/v1/research", headers=H1, json={"prospectIds": [pid]})
    assert (await client.get(f"/v1/prospects/{pid}/research", headers=H2)).status_code == 404
    assert (await client.get(f"/v1/lists/{lid}/prospects", headers=H2)).status_code == 404
    assert (await client.post(f"/v1/lists/{lid}/prospects", headers=H2, json={"name": "a", "company": "b", "role": "c", "phone": "", "notes": ""})).status_code == 404
    assert (await client.patch(f"/v1/lists/{lid}", headers=H2, json={"name": "hax"})).status_code == 404
    assert (await client.delete(f"/v1/lists/{lid}", headers=H2)).status_code == 404
    assert (await client.patch(f"/v1/prospects/{pid}", headers=H2, json={"name": "x"})).status_code == 404
    assert (await client.delete(f"/v1/prospects/{pid}", headers=H2)).status_code == 404
    assert (await client.post("/v1/calls", headers=H2, json={"prospectId": pid})).status_code == 404
    assert (await client.post(f"/v1/calls/reset/{pid}", headers=H2)).status_code == 404
    ws = (await client.get("/v1/workspace", headers=H2)).json()
    assert ws["prospects"] == [] and all(l["sellerId"] == "seller-2" for l in ws["lists"])
    assert len((await client.get(f"/v1/lists/{lid}/prospects", headers=H1)).json()) == 1
    own = (await client.get(f"/v1/prospects/{pid}/research", headers=H1)).json()
    assert own["researchStatus"] == "partial"


# ---------- JWT edge cases ----------

@pytest.fixture
def jwt_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "auth_mode", "jwt")
    monkeypatch.setattr(settings, "jwt_secret", SECRET)
    monkeypatch.setattr(settings, "jwt_algorithm", "HS256")


def _b64(d) -> str:
    return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()


@pytest.mark.asyncio
async def test_jwt_wrong_alg_garbage_and_bad_claims_are_401(client: AsyncClient, jwt_mode: None) -> None:
    exp = int(time.time()) + 300
    secret64 = SECRET * 2
    bad = [
        jwt.encode({"sub": "v", "exp": exp}, secret64, algorithm="HS512"),
        f"{_b64({'alg': 'none'})}.{_b64({'sub': 'v', 'exp': exp})}.",
        f"{_b64({'alg': 'RS256'})}.{_b64({'sub': 'v', 'exp': exp})}.AAAA",
        "garbage", "a.b.c", "....",
        jwt.encode({"sub": "", "exp": exp}, SECRET, algorithm="HS256"),
        jwt.encode({"sub": 123, "exp": exp}, SECRET, algorithm="HS256"),
        jwt.encode({"sub": "x" * 101, "exp": exp}, SECRET, algorithm="HS256"),
        jwt.encode({"exp": exp}, SECRET, algorithm="HS256"),
        jwt.encode({"sub": "v", "exp": int(time.time()) - 1}, SECRET, algorithm="HS256"),
    ]
    for tok in bad:
        res = await client.get("/v1/lists", headers={"Authorization": f"Bearer {tok}"})
        assert res.status_code == 401, tok
    good = jwt.encode({"sub": "v", "exp": exp}, SECRET, algorithm="HS256")
    for hdr in (good, f"Basic {good}", f"Token {good}", "Bearer", f"Bearer {good} extra"):
        res = await client.get("/v1/lists", headers={"Authorization": hdr})
        assert res.status_code == 401, hdr


# ---------- CSV ----------

async def _import(client, lid, content: bytes | str, headers=H1):
    if isinstance(content, str):
        content = content.encode()
    return await client.post(f"/v1/lists/{lid}/import", headers=headers, files={"file": ("x.csv", content, "text/csv")})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    [b"", b"\n\n  \n", b"name,company\nA,B\n", b"foo,bar,baz\n1,2,3\n", b"name,company,role\n",
     b'name,company,role\n"unterminated,B,C\n', b"name,company,role,title\nA,B,C,D\n"],
)
async def test_malformed_csv_rejected_cleanly(client: AsyncClient, content: bytes) -> None:
    lid = (await client.post("/v1/lists", headers=H1, json={"name": "L"})).json()["id"]
    res = await _import(client, lid, content)
    assert res.status_code == 400, res.text
    assert (await client.get(f"/v1/lists/{lid}/prospects", headers=H1)).json() == []


@pytest.mark.asyncio
async def test_csv_huge_cell_and_too_many_rows_and_oversize(client: AsyncClient) -> None:
    lid = (await client.post("/v1/lists", headers=H1, json={"name": "L"})).json()["id"]
    res = await _import(client, lid, "name,company,role,notes\nA,B,C," + "x" * 50_000 + "\nD,E,F,ok\n")
    assert res.status_code == 200
    assert len(res.json()["imported"]) == 1 and len(res.json()["rejectedRows"]) == 1
    rows = "".join(f"P{i},Co{i},R\n" for i in range(501))
    assert (await _import(client, lid, "name,company,role\n" + rows)).status_code in (400, 413)
    assert (await _import(client, lid, "name,company,role\n" + "A,B,C\n" * 200_000)).status_code in (400, 413)
    assert (await _import(client, lid, b"name,company,role\n\xff\xfe,B,C\n")).status_code in (200, 400)


@pytest.mark.asyncio
async def test_csv_formula_cells_are_inert_data_and_not_researched_as_code(client: AsyncClient) -> None:
    lid = (await client.post("/v1/lists", headers=H1, json={"name": "L"})).json()["id"]
    res = await _import(client, lid, 'name,company,role\n"=HYPERLINK(""http://evil"")",+cmd|x,@SUM(1)\n')
    assert res.status_code == 200
    got = res.json()["imported"][0]
    # Stored verbatim as text; JSON API must never be interpreted as a spreadsheet.
    assert got["name"].startswith("=HYPERLINK")
    pid = got["id"]
    await client.post("/v1/research", headers=H1, json={"prospectIds": [pid]})
    body = (await client.get(f"/v1/prospects/{pid}/research", headers=H1)).json()
    assert body["brief"]["facts"] == []
