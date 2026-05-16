from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator

MemoryKind = Literal["fact", "preference", "tool_outcome", "scratchpad"]
HistoryKind = Literal["answer", "action", "note"]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:8]}"


class MemoryItem(BaseModel):
    id: str = Field(default_factory=lambda: new_id("mem"))
    kind: MemoryKind
    keywords: list[str] = Field(default_factory=list)
    descriptor: str
    value: dict[str, Any] = Field(default_factory=dict)
    artifact_id: str | None = None
    source: str
    run_id: str
    goal_id: str | None = None
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    created_at: datetime = Field(default_factory=utc_now)


class Artifact(BaseModel):
    id: str
    content_type: str = "text/plain"
    size_bytes: int
    source: str
    descriptor: str
    created_at: datetime = Field(default_factory=utc_now)


class Goal(BaseModel):
    id: str = Field(default_factory=lambda: new_id("goal"))
    text: str
    done: bool = False
    attach_artifact_id: str | None = None
    attach_artifact_ids: list[str] = Field(default_factory=list)

    def all_attachment_ids(self) -> list[str]:
        ids: list[str] = []
        if self.attach_artifact_id:
            ids.append(self.attach_artifact_id)
        ids.extend(self.attach_artifact_ids)
        # Preserve order while deduplicating.
        return list(dict.fromkeys(ids))


class Observation(BaseModel):
    goals: list[Goal]

    @property
    def all_done(self) -> bool:
        return bool(self.goals) and all(g.done for g in self.goals)

    def next_unfinished(self) -> Goal | None:
        return next((g for g in self.goals if not g.done), None)


class ToolCall(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class DecisionOutput(BaseModel):
    answer: str | None = None
    tool_call: ToolCall | None = None

    @model_validator(mode="after")
    def exactly_one_output(self) -> "DecisionOutput":
        if (self.answer is None) == (self.tool_call is None):
            raise ValueError("DecisionOutput must contain exactly one of answer or tool_call")
        return self

    @property
    def is_answer(self) -> bool:
        return self.answer is not None


class HistoryEvent(BaseModel):
    iter: int
    kind: HistoryKind
    goal_id: str | None = None
    goal_text: str | None = None
    text: str | None = None
    tool: str | None = None
    arguments: dict[str, Any] | None = None
    result_descriptor: str | None = None
    result_text: str | None = None
    artifact_id: str | None = None
    artifact_ids: list[str] = Field(default_factory=list)
    ok: bool = True
    created_at: datetime = Field(default_factory=utc_now)


class ToolSpec(BaseModel):
    name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)


class MemoryReadInput(BaseModel):
    query: str
    history: list[HistoryEvent] = Field(default_factory=list)
    kinds: list[MemoryKind] | None = None
    top_k: int = Field(default=8, ge=1, le=50)


class MemoryReadOutput(BaseModel):
    hits: list[MemoryItem] = Field(default_factory=list)


class MemoryRememberInput(BaseModel):
    raw_text: str
    source: str
    run_id: str
    goal_id: str | None = None


class MemoryRememberOutput(BaseModel):
    stored: list[MemoryItem] = Field(default_factory=list)


class MemoryOutcomeInput(BaseModel):
    tool_call: ToolCall
    result_text: str
    artifact_id: str | None = None
    run_id: str
    goal_id: str | None = None


class PerceptionInput(BaseModel):
    query: str
    hits: list[MemoryItem] = Field(default_factory=list)
    history: list[HistoryEvent] = Field(default_factory=list)
    prior_goals: list[Goal] = Field(default_factory=list)
    run_id: str


class PerceptionOutput(BaseModel):
    observation: Observation


class DecisionInput(BaseModel):
    query: str
    goal: Goal
    hits: list[MemoryItem] = Field(default_factory=list)
    attached_artifacts: dict[str, str] = Field(default_factory=dict)
    history: list[HistoryEvent] = Field(default_factory=list)
    tools: list[ToolSpec] = Field(default_factory=list)


class ActionInput(BaseModel):
    tool_call: ToolCall


class ActionOutput(BaseModel):
    ok: bool
    descriptor: str
    result_text: str = ""
    artifact_id: str | None = None
    artifact: Artifact | None = None
