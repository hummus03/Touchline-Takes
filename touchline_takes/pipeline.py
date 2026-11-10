"""Orchestrator: wires tools into agents and runs the newsroom once.

Flow::

    ingest -> classifier -> research index -> analyst
           -> [writer -> factcheck -> editor] (repeat while drafts need revision,
                                               max ``MAX_REVISIONS`` extra rounds)
           -> publisher
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from touchline_takes.agents.analyst import AnalystAgent
from touchline_takes.agents.classifier import ClassifierAgent, LexiconClassifier, LLMClassifier
from touchline_takes.agents.editor import EditorAgent
from touchline_takes.agents.factcheck import FactCheckAgent
from touchline_takes.agents.ingest import IngestAgent
from touchline_takes.agents.publisher import PublisherAgent
from touchline_takes.agents.writer import WriterAgent
from touchline_takes.config import Settings
from touchline_takes.db import Database
from touchline_takes.state import NewsroomState, utcnow_iso
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


@dataclass
class Newsroom:
    """All agents plus the shared tools for one deployment."""

    settings: Settings
    db: Database
    llm: LLMClient | None
    research: ResearchIndex
    ingest: IngestAgent
    classifier: ClassifierAgent
    analyst: AnalystAgent
    writer: WriterAgent
    factcheck: FactCheckAgent
    editor: EditorAgent
    publisher: PublisherAgent

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
        return cls(
            settings=settings, db=db, llm=llm, research=research,
            ingest=IngestAgent(db, FeedClient(settings.sample_feed_dir,
                                              settings.request_timeout),
                               embeddings, settings.rss_feeds, settings.dedupe_threshold,
                               settings.offline),
            classifier=ClassifierAgent(db, backend),
            analyst=AnalystAgent(db, FixturesClient(settings.fixtures_path,
                                                    settings.football_data_api_key,
                                                    settings.request_timeout),
                                 teams, settings.results_dir, settings.model_path,
                                 settings.offline, retrain),
            writer=WriterAgent(db, teams, ResultsStore(load_results(settings.results_dir), label),
                               research, llm, settings.max_articles_per_run),
            factcheck=FactCheckAgent(db, settings.max_revisions),
            editor=EditorAgent(db, max_revisions=settings.max_revisions),
            publisher=PublisherAgent(db, settings.auto_publish),
        )

    def _step(self, name: str, func: Callable[[NewsroomState], NewsroomState],
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

    def run_once(self) -> NewsroomState:
        """One full pass of the newsroom."""
        state = NewsroomState()
        started = utcnow_iso()
        if isinstance(self.llm, GuardedLLM):
            self.llm.reset_budget()
        for name, func in (("ingest", self.ingest.run), ("classifier", self.classifier.run),
                           ("research", self.index_research), ("analyst", self.analyst.run)):
            state = self._step(name, func, state)
        rounds = 0
        for rounds in range(1, self.settings.max_revisions + 2):
            for name, func in (("writer", self.writer.run), ("factcheck", self.factcheck.run),
                               ("editor", self.editor.run)):
                state = self._step(name, func, state)
            if not state.drafts_with_status("needs_revision"):
                break
        state = self._step("publisher", self.publisher.run, state)
        state.metrics["rounds"] = rounds
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
        self.db.record_run(state.run_id, started, state.metrics)
        return state
