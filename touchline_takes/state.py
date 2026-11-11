"""Shared state objects passed between agents.

Every agent takes a :class:`NewsroomState` and returns it (updated). Keeping the
contract this small makes agents testable in isolation and maps one-to-one onto
LangGraph nodes later (the state becomes the graph's ``TypedDict``).
"""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def utcnow_iso() -> str:
    """Current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def story_id_for(url: str, title: str = "") -> str:
    """Stable short id for a story derived from its URL (or title)."""
    return hashlib.sha1((url or title).encode("utf-8")).hexdigest()[:12]


@dataclass
class Story:
    """A normalised source story plus the classifier's tags."""

    id: str
    title: str
    summary: str
    url: str
    source: str
    published: str
    body: str = ""
    league: str | None = None
    teams: list[str] = field(default_factory=list)
    topic: str | None = None
    sentiment: str | None = None
    sentiment_score: float = 0.0
    emotion: str | None = None
    image_url: str = ""
    image_tags: list[dict[str, Any]] = field(default_factory=list)

    @property
    def text(self) -> str:
        """Title and summary joined, the text used for embeddings and classification."""
        return f"{self.title}. {self.summary}".strip()

    def to_dict(self) -> dict[str, Any]:
        """Plain-dict representation."""
        return asdict(self)


@dataclass
class Evidence:
    """A citable record: a source story, a stats record, a fixture or a model output."""

    id: str
    kind: str  # story | stats | fixture | model
    text: str
    source: str
    url: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Plain-dict representation."""
        return asdict(self)


@dataclass
class Draft:
    """An article moving through Writer -> Fact-check -> Editor -> Publisher."""

    id: str
    article_type: str  # match_report | preview | explainer
    title: str
    body: str
    evidence: list[Evidence]
    story_ids: list[str] = field(default_factory=list)
    league: str | None = None
    teams: list[str] = field(default_factory=list)
    fixture_id: str | None = None
    status: str = "drafted"
    revision: int = 0
    mode: str = "template"  # template | llm
    slug: str = ""  # reserved when sent for review (static mode)
    claims: list[dict[str, Any]] = field(default_factory=list)
    feedback: list[str] = field(default_factory=list)
    rejection_history: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=lambda: {
        "llm_calls": 0, "cost_usd": 0.0, "tokens_in": 0, "tokens_out": 0, "latency_s": 0.0})
    created_at: str = field(default_factory=utcnow_iso)

    @property
    def sources(self) -> list[dict[str, str]]:
        """Unique attributable sources (name + link) behind the evidence."""
        seen: dict[str, dict[str, str]] = {}
        for item in self.evidence:
            key = item.url or item.source
            if key not in seen:
                seen[key] = {"name": item.source, "url": item.url, "kind": item.kind}
        return list(seen.values())

    def add_metrics(self, **values: float) -> None:
        """Accumulate cost/latency counters."""
        for key, value in values.items():
            self.metrics[key] = self.metrics.get(key, 0) + value

    def to_dict(self) -> dict[str, Any]:
        """Plain-dict representation (JSON-serialisable)."""
        data = asdict(self)
        data["evidence"] = [e.to_dict() for e in self.evidence]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Draft":
        """Inverse of :meth:`to_dict`."""
        data = dict(data)
        data["evidence"] = [Evidence(**e) for e in data.get("evidence", [])]
        return cls(**data)


@dataclass
class LogEntry:
    """One line of the per-run agent log."""

    agent: str
    action: str
    detail: str
    story_id: str | None = None
    ts: str = field(default_factory=utcnow_iso)


@dataclass
class NewsroomState:
    """Everything that flows through one pipeline run."""

    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    new_stories: list[Story] = field(default_factory=list)
    stories: list[Story] = field(default_factory=list)
    drafts: list[Draft] = field(default_factory=list)
    fixtures: list[dict[str, Any]] = field(default_factory=list)
    published: list[str] = field(default_factory=list)
    logs: list[LogEntry] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    drafting_done: bool = False
    started: float = field(default_factory=time.perf_counter)

    def log(self, agent: str, action: str, detail: str = "", story_id: str | None = None) -> None:
        """Record what an agent did (optionally for a specific story/draft)."""
        self.logs.append(LogEntry(agent=agent, action=action, detail=detail, story_id=story_id))

    def drafts_with_status(self, *statuses: str) -> list[Draft]:
        """Drafts currently in any of ``statuses``."""
        return [d for d in self.drafts if d.status in statuses]
