"""Pydantic data models for the Cold Call Conversion backend API (Lane C).

Mirrors the frontend workspace models and brief schemas defined in apps/web/src/lib/model.ts.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


def utc_now_iso() -> str:
    """Return the current UTC time formatted as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def normalize_prospect_key(list_id: str, name: str, company: str, role: str) -> str:
    """Compute the deterministic deduplication and cache key for a prospect."""
    parts = [list_id, name, company, role]
    return "\u001f".join(p.strip().lower() for p in parts)


class SourceModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=100)
    title: str
    publisher: str
    excerpt: str
    url: str | None = Field(default=None)

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if not re.match(r"^https?://", v):
            return None
        return v


class FactModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    text: str
    sourceIds: list[str] = Field(default_factory=list)


class QuestionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    basis: str


class BriefModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["demo"] = "demo"
    preparedAt: str
    summary: str
    facts: list[FactModel] = Field(default_factory=list)
    sources: list[SourceModel] = Field(default_factory=list)
    questions: list[QuestionModel] = Field(default_factory=list)
    roleContext: str = ""
    uncertainty: list[str] = Field(default_factory=list)


class ResearchStatusEnum(str, Enum):
    NOT_STARTED = "not-started"
    QUEUED = "queued"
    RUNNING = "running"
    READY = "ready"
    PARTIAL = "partial"
    FAILED = "failed"


class CallStatusEnum(str, Enum):
    READY = "ready"
    CALLED = "called"


class CallOutcomeEnum(str, Enum):
    COMPLETED = "completed"
    FOLLOW_UP = "follow-up"
    NOT_INTERESTED = "not-interested"
    NO_ANSWER = "no-answer"


class ProspectInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    company: str = Field(min_length=1, max_length=160)
    role: str = Field(min_length=1, max_length=160)
    phone: str = Field(default="", max_length=80)
    notes: str = Field(default="", max_length=4000)

    @field_validator("name", "company", "role", "phone", mode="before")
    @classmethod
    def strip_strings(cls, v: Any) -> Any:
        if isinstance(v, str):
            return v.strip()
        return v


class ProspectUpdateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    company: str | None = Field(default=None, min_length=1, max_length=160)
    role: str | None = Field(default=None, min_length=1, max_length=160)
    phone: str | None = Field(default=None, max_length=80)
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator("name", "company", "role", "phone", mode="before")
    @classmethod
    def strip_strings(cls, v: Any) -> Any:
        if isinstance(v, str):
            return v.strip()
        return v


class ProspectModel(ProspectInput):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=100)
    sellerId: str = Field(min_length=1, max_length=100)
    listId: str = Field(min_length=1, max_length=100)
    revision: int = 0
    position: int = 0
    fixtureKey: str | None = None
    researchStatus: ResearchStatusEnum = ResearchStatusEnum.NOT_STARTED
    callStatus: CallStatusEnum = CallStatusEnum.READY
    outcome: CallOutcomeEnum | None = None
    brief: BriefModel | None = None
    researchError: str | None = None


class ListInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, v: Any) -> Any:
        if isinstance(v, str):
            return v.strip()
        return v


class ListModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=100)
    sellerId: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=80)
    createdAt: str = Field(default_factory=utc_now_iso)


class ActiveCallModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prospectId: str = Field(min_length=1, max_length=100)
    startedAt: str = Field(default_factory=utc_now_iso)


class WorkspaceCallModel(BaseModel):
    """Completed call as the frontend workspaceSchema.calls expects it."""

    model_config = ConfigDict(extra="forbid")

    prospectId: str
    startedAt: str
    endedAt: str
    outcome: CallOutcomeEnum


class CompletedCallModel(ActiveCallModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=100)
    sellerId: str = Field(min_length=1, max_length=100)
    endedAt: str = Field(default_factory=utc_now_iso)
    outcome: CallOutcomeEnum
    idempotencyKey: str | None = None


class ConnectCallInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prospectId: str = Field(min_length=1, max_length=100)


class EndCallInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: CallOutcomeEnum


class MoveProspectInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    direction: Literal[-1, 1]


class ResearchEnqueueInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prospectIds: list[str] = Field(min_length=1, max_length=100)


class ResearchJobModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    prospectId: str
    sellerId: str
    revision: int
    status: ResearchStatusEnum
    attempts: int = 0
    leaseExpiresAt: str | None = None
    claimedBy: str | None = None
    lastError: str | None = None
    createdAt: str = Field(default_factory=utc_now_iso)


class ResearchStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prospectId: str
    revision: int
    researchStatus: ResearchStatusEnum
    researchError: str | None = None
    brief: BriefModel | None = None


class WorkspaceSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = 1
    lists: list[ListModel]
    prospects: list[ProspectModel]
    activeCall: ActiveCallModel | None = None
    calls: list[WorkspaceCallModel] = Field(default_factory=list)


class CsvImportRowError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    row: int
    message: str


class CsvImportResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    imported: list[ProspectModel]
    rejectedRows: list[CsvImportRowError]
    duplicatesSkipped: int
