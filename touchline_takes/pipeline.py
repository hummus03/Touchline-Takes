"""Newsroom wiring: builds every agent and tool, then runs them.

Orchestration is a LangGraph ``StateGraph`` (see :mod:`touchline_takes.graph`)::

    ingest -> classifier -> photo_tagger -> research -> analyst -> writer -> factcheck -> editor
                                                    ^                       |
                                                    +-- needs revision -----+
    editor -> publisher -> finalize -> human_review (interrupt; resumed by a human) -> END

``ORCHESTRATOR=sequential`` runs the same agents in a plain Python loop instead
(no checkpoints or interrupts; drafts awaiting review are approved directly).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph

from touchline_takes.agents.analyst import AnalystAgent
from touchline_takes.agents.classifier import ClassifierAgent, LexiconClassifier, LLMClassifier
from touchline_takes.agents.editor import EditorAgent
from touchline_takes.agents.factcheck import FactCheckAgent, LLMVerifier
from touchline_takes.agents.ingest import IngestAgent
from touchline_takes.agents.photo_tagger import ImageFetcher, PhotoTaggerAgent
from touchline_takes.agents.publisher import PublisherAgent
from touchline_takes.agents.writer import WriterAgent
from touchline_takes.config import DATA_DIR, Settings
from touchline_takes.db import Database
from touchline_takes import graph as newsroom_graph
from touchline_takes.state import Draft, NewsroomState, utcnow_iso
from touchline_takes.tools.embeddings import build_embeddings
from touchline_takes.tools.feeds import FeedClient
from touchline_takes.tools.football_api import FixturesClient
from touchline_takes.tools.llm import GuardedLLM, LLMClient, build_llm
from touchline_takes.tools.rag import ResearchIndex, build_vector_store
from touchline_takes.tools.stats import ResultsStore, load_results
from touchline_takes.tools.teams import TeamDirectory

LOGGER = logging.getLogger("touchline_takes.pipeline")


def results_label(results_dir: str) -> str:
    """Honest label for the results data in use."""
    files = list(Path(results_dir).glob("*.csv"))
    if files and all(f.name.startswith("sample_") for f in files):
        return "synthetic sample results"
    return "Football-Data.co.uk results"


def photo_tagger_loader(settings: Settings) -> Callable[[], object | None]:
    """Lazy loader for the trained VGG16 tagger (``None`` if disabled or not trained)."""
    def load():
        if not settings.photo_tagger:
            return None
        try:
            from touchline_takes.models.photo_tagger import (  # pylint: disable=import-outside-toplevel
                PhotoTagger, model_available)
        except ImportError as exc:  # Keras/JAX not installed
            LOGGER.warning("photo tagger unavailable: %s", exc)
            return None
        if not model_available(settings.photo_model_dir):
            return None
        return PhotoTagger.load(settings.photo_model_dir)
    return load


@dataclass
class Newsroom:
    """All agents plus the shared tools for one deployment."""

    settings: Settings
    db: Database
    llm: LLMClient | None
    research: ResearchIndex
    ingest: IngestAgent
    classifier: ClassifierAgent
    photo_tagger: PhotoTaggerAgent
    analyst: AnalystAgent
    writer: WriterAgent
    factcheck: FactCheckAgent
    editor: EditorAgent
    publisher: PublisherAgent
    checkpointer: BaseCheckpointSaver | None = None
    _app: CompiledStateGraph | None = field(default=None, init=False, repr=False)

    @property
    def app(self) -> CompiledStateGraph:
        """The compiled LangGraph app (built on first use)."""
        if self._app is None:
            self._app = newsroom_graph.compile_graph(self, self.checkpointer)
        return self._app

    @classmethod
    def build(cls, settings: Settings, llm: LLMClient | None = None,
              db: Database | None = None, retrain: bool = False) -> "Newsroom":
        """Construct the newsroom from settings (``llm`` overrides the configured provider)."""
        db = db or Database(settings.database_path)
        if llm is None:
            llm = build_llm(settings, cache=db)
        elif not isinstance(llm, GuardedLLM):
            llm = GuardedLLM(llm, settings.llm_max_calls_per_run,
                             db if settings.llm_cache else None)
        embeddings = build_embeddings(settings)
        teams = TeamDirectory.from_file(settings.teams_path)
        lexicon = LexiconClassifier(teams)
        backend = LLMClassifier(llm, lexicon) if (
            settings.classifier_provider == "llm" and llm is not None) else lexicon
        research = ResearchIndex(build_vector_store(settings, embeddings), embeddings, llm=llm)
        label = results_label(settings.results_dir)
        verifier = LLMVerifier(llm) if (
            settings.factcheck_verifier == "llm" and llm is not None) else None
        return cls(
            settings=settings, db=db, llm=llm, research=research,
            ingest=IngestAgent(db, FeedClient(settings.sample_feed_dir,
                                              settings.request_timeout),
                               embeddings, settings.rss_feeds, settings.dedupe_threshold,
                               settings.offline, allow_fallback=settings.allow_sample_data),
            classifier=ClassifierAgent(db, backend),
            photo_tagger=PhotoTaggerAgent(
                db, ImageFetcher(str(DATA_DIR), settings.request_timeout,
                                 allow_local=settings.allow_sample_data),
                photo_tagger_loader(settings), settings.photo_max_per_run),
            analyst=AnalystAgent(db, FixturesClient(settings.fixtures_path,
                                                    settings.football_data_api_key,
                                                    settings.request_timeout),
                                 teams, settings.results_dir, settings.model_path,
                                 settings.offline, retrain,
                                 allow_fallback=settings.allow_sample_data),
            writer=WriterAgent(db, teams, ResultsStore(load_results(settings.results_dir), label),
                               research, llm, settings.max_articles_per_run),
            factcheck=FactCheckAgent(db, settings.max_revisions, teams=teams, verifier=verifier),
            editor=EditorAgent(db, max_revisions=settings.max_revisions),
            # Static mode: the export step publishes (commits to main), so drafts always queue.
            publisher=PublisherAgent(db, settings.auto_publish and not settings.is_static),
            checkpointer=newsroom_graph.make_checkpointer(settings.checkpoint_path),
        )

    def step(self, name: str, func: Callable[[NewsroomState], NewsroomState],
             state: NewsroomState) -> NewsroomState:
        """Run one step, timing it and isolating failures so one agent can't sink the run."""
        start = time.perf_counter()
        try:
            state = func(state)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            LOGGER.exception("step %s failed", name)
            state.log(name, "error", f"{type(exc).__name__}: {exc}")
            state.metrics.setdefault("errors", []).append(f"{name}: {exc}")
        state.metrics.setdefault("timings_s", {})[name] = round(
            state.metrics.get("timings_s", {}).get(name, 0) + time.perf_counter() - start, 4)
        return state

    def index_research(self, state: NewsroomState) -> NewsroomState:
        """Keep the vector store in sync with the stories table."""
        added = self.research.index_stories(self.db.all_stories())
        state.log("research", "indexed", f"{added} new chunks")
        return state

    def finalize(self, state: NewsroomState, rounds: int) -> NewsroomState:
        """Summarise the run and persist its log (before any human review)."""
        state.metrics["rounds"] = rounds
        state.metrics["orchestrator"] = self.settings.orchestrator
        state.metrics["drafts"] = {
            status: len(state.drafts_with_status(status)) for status in
            ("published", "pending_review", "rejected", "needs_revision")}
        if isinstance(self.llm, GuardedLLM):
            usage = self.llm.usage
            state.metrics["llm"] = {"provider": self.llm.provider, "calls": usage.calls,
                                    "cache_hits": usage.cache_hits,
                                    "cost_usd": round(usage.cost_usd, 6)}
        else:
            state.metrics["llm"] = {"provider": "offline", "calls": 0}
        state.metrics["duration_s"] = round(time.perf_counter() - state.started, 3)
        self.db.write_logs(state.run_id, state.logs)
        self.db.record_run(state.run_id, state.metrics.pop("started_at", utcnow_iso()),
                           state.metrics)
        return state

    # ------------------------------------------------------------------ human review
    def pending_in_run(self, state: NewsroomState) -> list[Draft]:
        """Drafts from this run still awaiting a human (the DB is the source of truth)."""
        pending = []
        for draft in state.drafts:
            stored = self.db.get_draft(draft.id)
            if stored is not None:
                draft.status = stored.status
            if draft.status == "pending_review":
                pending.append(draft)
        return pending

    def apply_decisions(self, state: NewsroomState, decisions: dict[str, dict]) -> None:
        """Publish or reject drafts as a human decided; persists the new log lines."""
        already = len(state.logs)
        for draft in self.pending_in_run(state):
            decision = decisions.get(draft.id)
            if not decision:
                continue
            if decision.get("action") == "approve":
                self.publisher.publish(draft, state)
            elif decision.get("action") == "reject":
                self.publisher.reject(draft, decision.get("reason", ""), state)
                state.log("human", "rejected", decision.get("reason", ""), draft.id)
        self.db.write_logs(state.run_id, state.logs[already:])

    def review(self, draft_id: str, action: str, reason: str = "") -> Draft | None:
        """Approve or reject one pending draft, resuming its paused graph run if there is one.

        Drafts from sequential runs (or whose checkpoint is gone) are handled directly.
        """
        draft = self.db.get_draft(draft_id)
        if draft is None or draft.status != "pending_review" or action not in (
                "approve", "reject"):
            return None
        decisions = {draft_id: {"action": action, "reason": reason}}
        run_id = self.db.draft_run_id(draft_id)
        if run_id and self.settings.orchestrator == "langgraph" and \
                newsroom_graph.paused_for_review(self.app, run_id):
            newsroom_graph.resume(self.app, run_id, decisions)
        else:
            state = NewsroomState(run_id=run_id or "manual", drafts=[draft])
            self.apply_decisions(state, decisions)
        return self.db.get_draft(draft_id)

    # ------------------------------------------------------------------ runs
    def _start(self) -> NewsroomState:
        state = NewsroomState()
        state.metrics["started_at"] = utcnow_iso()
        if isinstance(self.llm, GuardedLLM):
            self.llm.reset_budget()
        return state

    def run_once(self) -> NewsroomState:
        """One full pass of the newsroom (pauses at human review when approval is required)."""
        if self.settings.orchestrator == "sequential":
            return self.run_once_sequential()
        state = self._start()
        result = self.app.invoke({"newsroom": state, "rounds": 0},
                                 newsroom_graph.thread_config(state.run_id))
        return result["newsroom"]

    def run_once_sequential(self) -> NewsroomState:
        """The same agents in a plain loop (no checkpoints, no interrupts)."""
        state = self._start()
        for name, func in (("ingest", self.ingest.run), ("classifier", self.classifier.run),
                           ("photo_tagger", self.photo_tagger.run),
                           ("research", self.index_research), ("analyst", self.analyst.run)):
            state = self.step(name, func, state)
        rounds = 0
        for rounds in range(1, self.settings.max_revisions + 2):
            for name, func in (("writer", self.writer.run), ("factcheck", self.factcheck.run),
                               ("editor", self.editor.run)):
                state = self.step(name, func, state)
            if not state.drafts_with_status("needs_revision"):
                break
        state = self.step("publisher", self.publisher.run, state)
        return self.finalize(state, rounds)
