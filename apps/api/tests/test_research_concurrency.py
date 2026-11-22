"""The worker limits how many research jobs run at once."""

import asyncio

from cold_call_api.services import worker


async def test_slot_caps_concurrency(monkeypatch):
    monkeypatch.setenv("RESEARCH_MAX_CONCURRENCY", "2")
    worker._slots.clear()
    running = peak = 0

    async def fake_job():
        nonlocal running, peak
        async with worker._research_slot():
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.01)
            running -= 1

    await asyncio.gather(*(fake_job() for _ in range(8)))
    assert peak == 2


async def test_bad_env_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("RESEARCH_MAX_CONCURRENCY", "nope")
    worker._slots.clear()
    assert worker._research_slot()._value == 2
