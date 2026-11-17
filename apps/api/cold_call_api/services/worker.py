"""Background research job worker (Lane C).

Responsible for:
- Claiming and processing research jobs
- Caching briefings by prospect key
- Calling cold_call_agents.run_research
- Stale-revision protection (never overwrites an edited prospect)
- Graceful error handling (stale or crashed jobs are reclaimed by lease expiry on re-enqueue)
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from cold_call_agents.adapter import research_status as calc_research_status, to_frontend_brief
from cold_call_agents.models import Prospect as AgentProspect
from cold_call_agents.orchestrator import Budget, run_research
from cold_call_agents.providers import (
    FIXTURE_KEYS,
    MockLLM,
    MockProfiles,
    MockSearch,
    load_fixture,
    mocks_from_fixture,
)
from cold_call_api.config import settings
from cold_call_api.models import (
    BriefModel,
    ProspectModel,
    ResearchJobModel,
    ResearchStatusEnum,
    normalize_prospect_key,
)
from cold_call_api.storage.interface import StorageRepository

logger = logging.getLogger("cold_call_api.worker")


def _norm(value: str) -> str:
    return " ".join(value.lower().split())


def _fixture_key_for(p: ProspectModel) -> str | None:
    """Return a fixture key only for an explicit fixtureKey or an exact name AND company match."""
    if p.fixtureKey and p.fixtureKey.lower() in FIXTURE_KEYS:
        return p.fixtureKey.lower()
    for key in FIXTURE_KEYS:
        person = load_fixture(key)["prospect"]
        if _norm(p.name) == _norm(person["name"]) and _norm(p.company) == _norm(person["company"]):
            return key
    return None


def _get_providers_for_prospect(p: ProspectModel) -> tuple[Any, Any, Any]:
    """Resolve LLM, Search, and Profile providers for a prospect.

    Sample fixtures are used only for the exact fictional sample prospects (or an explicit
    fixtureKey). Everything else gets empty providers (no facts) until live providers exist.
    """
    matched_key = _fixture_key_for(p)
    if matched_key:
        return mocks_from_fixture(load_fixture(matched_key))

    # No fixture and no live providers yet: return empty providers so the
    # briefing contains no facts rather than invented ones.
    return MockLLM(), MockSearch([]), MockProfiles(None, None)


def _cache_key(p: ProspectModel) -> str:
    """Cache key: seller, identity fields and notes, so sellers never share a brief and a notes edit never returns an old one."""
    return f"{p.sellerId}\u001f{normalize_prospect_key(p.listId, p.name, p.company, p.role)}\u001f{_norm(p.notes or '')}"


async def _record_failure(repo: StorageRepository, job: ResearchJobModel, message: str) -> None:
    """Best-effort failure recording; each write is isolated so one failing does not skip the other."""
    try:
        await repo.update_prospect_research(
            seller_id=job.sellerId,
            prospect_id=job.prospectId,
            revision=job.revision,
            status=ResearchStatusEnum.FAILED,
            brief=None,
            error=message,
        )
    except Exception:
        logger.exception("Could not record failed research on prospect %s", job.prospectId)
    try:
        await repo.finish_research_job(job.id, ResearchStatusEnum.FAILED, message)
    except Exception:
        logger.exception("Could not mark research job %s failed (lease expiry will reclaim it)", job.id)


async def process_job(repo: StorageRepository, job: ResearchJobModel) -> None:
    """Claim (if still queued) and execute a research job end-to-end."""
    if job.status == ResearchStatusEnum.QUEUED:
        claimed = await repo.claim_research_job(
            "background", lease_seconds=settings.research_lease_seconds, job_id=job.id
        )
        if claimed is None:
            logger.info("Job %s already claimed or finished; skipping", job.id)
            return
        job = claimed
    try:
        await _run_job(repo, job)
    except Exception:
        logger.exception("Research failed for prospect %s", job.prospectId)
        await _record_failure(repo, job, "Research pipeline encountered an error. Please retry.")


async def _run_job(repo: StorageRepository, job: ResearchJobModel) -> None:
    seller_id = job.sellerId
    prospect_id = job.prospectId
    revision = job.revision

    prospect = await repo.get_prospect(seller_id, prospect_id)
    if not prospect:
        logger.warning("Prospect %s not found for job %s", prospect_id, job.id)
        await repo.finish_research_job(job.id, ResearchStatusEnum.FAILED, "Prospect not found.")
        return

    # If prospect was edited while job was queued, drop this job
    if prospect.revision != revision:
        logger.info("Dropping stale job %s (prospect rev: %d, job rev: %d)", job.id, prospect.revision, revision)
        await repo.finish_research_job(job.id, ResearchStatusEnum.FAILED, "Prospect was updated.")
        return

    pkey = _cache_key(prospect)

    # 1. Check cache first
    cached_brief = await repo.get_cached_briefing(pkey, max_age_days=settings.brief_cache_days)
    if cached_brief:
        logger.info("Cache hit for prospect %s", prospect_id)
        status = ResearchStatusEnum.PARTIAL if cached_brief.uncertainty else ResearchStatusEnum.READY
        updated = await repo.update_prospect_research(
            seller_id=seller_id,
            prospect_id=prospect_id,
            revision=revision,
            status=status,
            brief=cached_brief,
            error=None,
        )
        await repo.finish_research_job(job.id, status if updated else ResearchStatusEnum.FAILED)
        return

    # 2. Run agent pipeline
    agent_prospect = AgentProspect(
        prospect_id=prospect.id,
        name=prospect.name,
        role=prospect.role,
        company=prospect.company,
        notes=prospect.notes or "",
        revision=prospect.revision,
    )
    llm, search, profiles = _get_providers_for_prospect(prospect)
    budget = Budget(timeout_seconds=settings.research_timeout_seconds)

    # Run research off the async loop in a worker thread
    briefing = await asyncio.to_thread(
        run_research,
        agent_prospect,
        llm=llm,
        search=search,
        profiles=profiles,
        budget=budget,
    )

    # Adapt to frontend brief schema
    brief_dict = to_frontend_brief(briefing)
    if not briefing.facts:
        brief_dict["uncertainty"].insert(
            0, "No live research providers are connected yet, so no facts were gathered for this prospect."
        )
    brief_model = BriefModel.model_validate(brief_dict)
    raw_status = calc_research_status(briefing)
    status_enum = (
        ResearchStatusEnum.PARTIAL if raw_status == "partial" or not briefing.facts else ResearchStatusEnum.READY
    )

    # Only cache briefings that actually contain facts
    if briefing.facts:
        await repo.save_cached_briefing(pkey, brief_model)

    # Update prospect with stale guard
    applied = await repo.update_prospect_research(
        seller_id=seller_id,
        prospect_id=prospect_id,
        revision=revision,
        status=status_enum,
        brief=brief_model,
        error=None,
    )
    if applied:
        await repo.finish_research_job(job.id, status_enum)
    else:
        logger.info("Prospect %s revision changed during research; discarded result", prospect_id)
        await repo.finish_research_job(job.id, ResearchStatusEnum.FAILED, "Prospect was updated during research.")


async def run_worker_loop(repo: StorageRepository, poll_interval: float = 0.5, once: bool = False) -> None:
    """Continuously poll and process queued research jobs."""
    worker_id = "worker-1"
    while True:
        job = await repo.claim_research_job(worker_id, lease_seconds=settings.research_lease_seconds)
        if job:
            await process_job(repo, job)
        elif once:
            break
        else:
            await asyncio.sleep(poll_interval)
