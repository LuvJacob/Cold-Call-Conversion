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
import os
import random
from typing import Any, Awaitable, Callable
from pydantic import ValidationError
from cold_call_agents.adapter import research_status as calc_research_status, to_frontend_brief
from cold_call_agents.models import Prospect as AgentProspect
from cold_call_agents.orchestrator import Budget, run_research
from cold_call_agents.free_sources import build_free_providers
from cold_call_agents.live import build_live_providers
from cold_call_agents.providers import (
    FIXTURE_KEYS,
    MockLLM,
    MockProfiles,
    MockSearch,
    load_fixture,
    mocks_from_fixture,
)
from cold_call_api.config import research_mode, settings
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


def _free_sources_enabled() -> bool:
    """RESEARCH_PROVIDERS=free turns on the no-key public sources (Wikidata, SEC EDGAR, company site)."""
    return research_mode() == "free"


def _live_enabled() -> bool:
    """RESEARCH_PROVIDERS=live uses the paid providers (keys from the environment; missing keys fall back to free sources)."""
    return research_mode() == "live"


def _get_providers_for_prospect(
    p: ProspectModel, agent_prospect: AgentProspect | None = None, budget: Budget | None = None
) -> tuple[Any, Any, Any]:
    """Resolve LLM, Search, and Profile providers for a prospect.

    Sample fixtures are used only for the exact fictional sample prospects (or an explicit
    fixtureKey). Otherwise, with RESEARCH_PROVIDERS=free, the free public sources are used.
    With the variable unset, everything else gets empty providers (no facts, no network).
    """
    matched_key = _fixture_key_for(p)
    if matched_key:
        return mocks_from_fixture(load_fixture(matched_key))

    if agent_prospect is not None and _live_enabled():
        return build_live_providers(agent_prospect, budget or Budget(), dict(os.environ))

    if agent_prospect is not None and _free_sources_enabled():
        return build_free_providers(agent_prospect, budget or Budget())

    # No fixture and no live providers yet: return empty providers so the
    # briefing contains no facts rather than invented ones.
    return MockLLM(), MockSearch([]), MockProfiles(None, None)


def _cache_key(p: ProspectModel, mode: str = "") -> str:
    """Cache key: seller, identity fields, notes and company domain, so sellers never share a brief and a notes or domain edit never returns an old one.
    `mode` ("free" or "live" for researched prospects) is appended only when set, so a brief from one mode is never served in another."""
    key = f"{p.sellerId}\u001f{normalize_prospect_key(p.listId, p.name, p.company, p.role)}\u001f{_norm(p.notes or '')}\u001f{p.companyDomain or ''}"
    return f"{key}\u001f{mode}" if mode else key


def _close_providers(*providers: Any) -> None:
    """Close every provider that owns an HTTP client; one failing close never skips the others.
    search and profiles can be the same shared free provider, so close() must be (and is) idempotent."""
    for provider in providers:
        if provider is None:
            continue
        close = getattr(provider, "close", None)
        if close:
            try:
                close()
            except Exception:
                logger.exception("Could not close research provider")


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


# Our own bugs or bad data: retrying cannot help, so fail immediately.
_DETERMINISTIC_ERRORS = (ValidationError, TypeError, KeyError, AttributeError, AssertionError)


_slots: dict[int, asyncio.Semaphore] = {}  # one semaphore per running event loop


def _research_slot() -> asyncio.Semaphore:
    """Limit concurrent research jobs (RESEARCH_MAX_CONCURRENCY, default 2).
    BackgroundTasks runs async jobs on the event loop, so an asyncio.Semaphore is the right primitive."""
    loop_id = id(asyncio.get_running_loop())
    if loop_id not in _slots:
        try:
            limit = max(1, int(os.environ.get("RESEARCH_MAX_CONCURRENCY", "2")))
        except ValueError:
            limit = 2
        _slots.clear()  # a new loop means the old one is gone
        _slots[loop_id] = asyncio.Semaphore(limit)
    return _slots[loop_id]


def backoff_seconds(attempt: int, base: float, rand: Callable[[], float] | None = None) -> float:
    """Exponential backoff after failed attempt number `attempt` (1-based): base * 2^(attempt-1),
    jittered by +/-25% and capped at 5 minutes."""
    return min(base * 2 ** (attempt - 1), 300.0) * (0.75 + 0.5 * (rand or random.random)())


async def process_job(
    repo: StorageRepository,
    job: ResearchJobModel,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """Claim (if still queued) and execute a research job, retrying failures with backoff.

    A failed attempt (exception) is retried up to settings.research_max_attempts total attempts.
    Each retry re-claims the job (new lease, attempts + 1) and re-checks the prospect revision, so a
    prospect edited during backoff is never researched or overwritten with stale data.
    """
    while True:
        # Hold a slot only while claiming and running (not while waiting or backing off), so the lease
        # starts when work starts and a big batch cannot burst the free sources.
        async with _research_slot():
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
                return
            except Exception as exc:
                logger.exception("Research failed for prospect %s (attempt %d)", job.prospectId, job.attempts)
                deterministic = isinstance(exc, _DETERMINISTIC_ERRORS)

        if (
            deterministic
            or job.attempts >= settings.research_max_attempts
            or not await _should_retry(repo, job)
        ):
            await _record_failure(repo, job, "Research pipeline encountered an error. Please retry.")
            return
        delay = backoff_seconds(job.attempts, settings.research_retry_base_seconds)
        try:
            requeued = await repo.requeue_research_job(
                job.id,
                "Research attempt failed; retrying.",
                int(delay) + settings.research_lease_seconds,
                delay_seconds=delay,
            )
        except Exception:
            logger.exception("Could not requeue research job %s", job.id)
            await _record_failure(repo, job, "Research pipeline encountered an error. Please retry.")
            return
        if not requeued:
            # The job is no longer ours (lease expired and a newer job took over): never touch the prospect.
            logger.warning("Job %s is no longer running; abandoning retry without recording failure", job.id)
            return
        logger.info("Retrying job %s in %.1fs (attempt %d failed)", job.id, delay, job.attempts)
        await sleep(delay)
        job = job.model_copy(update={"status": ResearchStatusEnum.QUEUED})


async def _should_retry(repo: StorageRepository, job: ResearchJobModel) -> bool:
    """Retry only while the prospect still exists at the job's revision."""
    try:
        prospect = await repo.get_prospect(job.sellerId, job.prospectId)
    except Exception:
        logger.exception("Could not read prospect %s before retry", job.prospectId)
        return False
    return prospect is not None and prospect.revision == job.revision


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

    fixture_match = _fixture_key_for(prospect) is not None
    mode = research_mode()
    researched_mode = "" if fixture_match else mode  # fixture briefs are mode independent
    pkey = _cache_key(prospect, researched_mode)

    # 1. Check cache first
    cached = await repo.get_cached_entry(pkey, max_age_days=settings.brief_cache_days)
    if cached:
        cached_brief, stored_status = cached
        logger.info("Cache hit for prospect %s", prospect_id)
        # Same status as the original run; entries saved without one fall back to the uncertainty heuristic.
        status = stored_status or (
            ResearchStatusEnum.PARTIAL if cached_brief.uncertainty else ResearchStatusEnum.READY
        )
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
        company_domain=prospect.companyDomain,
        notes=prospect.notes or "",
        revision=prospect.revision,
    )
    budget = Budget(timeout_seconds=settings.research_timeout_seconds)
    free = researched_mode in ("free", "live")
    llm = search = profiles = None

    # Run research off the async loop in a worker thread
    try:
        llm, search, profiles = _get_providers_for_prospect(prospect, agent_prospect, budget)
        briefing = await asyncio.to_thread(
            run_research,
            agent_prospect,
            llm=llm,
            search=search,
            profiles=profiles,
            budget=budget,
            mode="live" if free else "sample",
        )
    finally:
        _close_providers(search, profiles, llm)  # free and live providers own HTTP clients

    # Adapt to frontend brief schema
    # Fixture (sample) briefs stay "demo"; real research is labelled "free" or "live".
    brief_dict = to_frontend_brief(briefing, mode=researched_mode or "demo")
    if not briefing.facts:
        brief_dict["uncertainty"].insert(
            0,
            (
                "Live research providers found no matching facts for this prospect."
                if researched_mode == "live"
                else "Free public sources found no matching facts for this prospect."
            )
            if free
            else "No live research providers are connected yet, so no facts were gathered for this prospect.",
        )
    brief_model = BriefModel.model_validate(brief_dict)
    raw_status = calc_research_status(briefing)
    status_enum = (
        ResearchStatusEnum.PARTIAL if raw_status == "partial" or not briefing.facts else ResearchStatusEnum.READY
    )

    # Only cache briefings that actually contain facts (free and live briefings only when complete,
    # so a transient network failure is not cached for the whole cache window)
    if briefing.facts and not (free and status_enum != ResearchStatusEnum.READY):
        await repo.save_cached_briefing(pkey, brief_model, status_enum)

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
