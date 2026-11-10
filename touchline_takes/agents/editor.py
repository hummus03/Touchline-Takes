"""Editor agent: style, tone, length and originality checks; approve or send back."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

from touchline_takes.agents.base import Agent
from touchline_takes.agents.factcheck import check_draft
from touchline_takes.db import Database
from touchline_takes.state import Draft, NewsroomState
from touchline_takes.tools.text import (shared_ngram, strip_citations, without_quotes,
                                        word_count)

BANNED_PHRASES = ("as an ai", "in conclusion", "delve", "it is important to note",
                  "game-changer", "at the end of the day", "lorem ipsum")
ACRONYMS = {"VAR", "UEFA", "FIFA", "PSG", "PGMOL", "EFL", "FA", "TV"}


@dataclass
class StyleGuide:
    """House style limits."""

    min_words: int = 90
    max_words: int = 450
    min_title: int = 12
    max_title: int = 90
    max_exclamations: int = 2
    min_sourced_claims: int = 3
    copy_ngram: int = 10


class EditorAgent(Agent):
    """Approves drafts that meet the style guide; otherwise sends them back (bounded)."""

    name = "editor"

    def __init__(self, db: Database, style: StyleGuide | None = None,
                 max_revisions: int = 2) -> None:
        super().__init__()
        self.db = db
        self.style = style or StyleGuide()
        self.max_revisions = max_revisions

    def review(self, draft: Draft) -> list[str]:
        """Return a list of problems (empty means approved)."""
        style = self.style
        problems = []
        words = word_count(draft.body)
        if words < style.min_words:
            problems.append(f"too short: {words} words (minimum {style.min_words})")
        if words > style.max_words:
            problems.append(f"too long: {words} words (maximum {style.max_words})")
        if not style.min_title <= len(draft.title) <= style.max_title:
            problems.append(f"title length {len(draft.title)} outside "
                            f"{style.min_title}-{style.max_title} characters")
        lower = draft.body.lower()
        problems += [f"banned phrase: '{p}'" for p in BANNED_PHRASES if p in lower]
        if draft.body.count("!") > style.max_exclamations:
            problems.append("tone: too many exclamation marks")
        shouting = [w for w in re.findall(r"\b[A-Z]{4,}\b", strip_citations(draft.body))
                    if w not in ACRONYMS]
        if shouting:
            problems.append(f"tone: avoid shouting ({', '.join(shouting[:3])})")
        checks = check_draft(draft)
        if not any(not c.is_claim for c in checks):
            problems.append("tone: no opinion; a Touchline Take needs a take")
        if "touchline take:" not in lower:
            problems.append("structure: missing 'The Touchline Take:' verdict line")
        unsupported = [c for c in checks if c.is_claim and not c.supported]
        if unsupported:
            problems.append(f"{len(unsupported)} unsupported claim(s) remain")
        sourced = sum(1 for c in checks if c.is_claim and c.supported)
        if sourced < style.min_sourced_claims:
            problems.append(f"too thin: {sourced} sourced claims "
                            f"(minimum {style.min_sourced_claims})")
        body = without_quotes(strip_citations(draft.body))
        for ev in draft.evidence:
            if ev.kind == "story":
                copied = shared_ngram(body, ev.text, style.copy_ngram)
                if copied:
                    problems.append(f"originality: copies source text '{copied}'")
        if not any(s["url"] for s in draft.sources):
            problems.append("attribution: no linked source")
        return problems

    def run(self, state: NewsroomState) -> NewsroomState:
        for draft in state.drafts_with_status("checked"):
            start = time.perf_counter()
            problems = self.review(draft)
            if not problems:
                draft.status, draft.feedback = "approved", []
                self.log(state, "approved", draft.title, draft.id)
            else:
                self.db.log_rejection(state.run_id, draft, self.name, problems)
                draft.rejection_history.append({"agent": self.name,
                                                "revision": draft.revision,
                                                "reasons": problems})
                if draft.revision < self.max_revisions:
                    draft.status, draft.feedback = "needs_revision", problems
                    self.log(state, "sent_back", "; ".join(problems), draft.id)
                else:
                    draft.status = "rejected"
                    self.log(state, "rejected", "; ".join(problems), draft.id)
            draft.add_metrics(latency_s=time.perf_counter() - start)
            self.db.save_draft(draft, state.run_id)
        return state
