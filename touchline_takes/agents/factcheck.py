"""Fact-check agent: every claim must trace to a cited source story or stats record.

A sentence is a *claim* if it contains numbers or proper nouns (or cites
evidence). A claim is *supported* when it cites at least one known evidence id
and every number/proper noun in it appears in the cited evidence. Unsupported
claims are removed; if too many are found (or the lead claim fails) the draft
goes back to the Writer instead.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from touchline_takes.agents.base import Agent
from touchline_takes.db import Database
from touchline_takes.state import Draft, NewsroomState
from touchline_takes.tools.text import (citations, factual_tokens, split_paragraphs,
                                        split_sentences, word_tokens)


@dataclass
class ClaimCheck:
    """Verdict on one sentence."""

    sentence: str
    is_claim: bool
    supported: bool
    cited: list[str]
    missing: list[str]
    reason: str = ""

    def to_dict(self) -> dict:
        """Plain-dict form stored on the draft."""
        return {"sentence": self.sentence, "is_claim": self.is_claim,
                "supported": self.supported, "cited": self.cited, "missing": self.missing,
                "reason": self.reason}


def check_sentence(sentence: str, evidence_tokens: dict[str, set[str]]) -> ClaimCheck:
    """Check one sentence against tokenised evidence."""
    tokens = factual_tokens(sentence)
    cited = citations(sentence)
    if not tokens and not cited:
        return ClaimCheck(sentence, False, True, [], [], "opinion")
    if not cited:
        return ClaimCheck(sentence, True, False, [], tokens, "no source cited")
    unknown = [c for c in cited if c not in evidence_tokens]
    if unknown:
        return ClaimCheck(sentence, True, False, cited, tokens,
                          f"cites unknown evidence {', '.join(unknown)}")
    pool: set[str] = set().union(*(evidence_tokens[c] for c in cited))
    missing = [t for t in tokens if t not in pool]
    if missing:
        return ClaimCheck(sentence, True, False, cited, missing,
                          f"not in cited evidence: {', '.join(missing)}")
    return ClaimCheck(sentence, True, True, cited, [], "supported")


def check_draft(draft: Draft) -> list[ClaimCheck]:
    """Check every sentence of a draft."""
    evidence_tokens = {e.id: word_tokens(e.text) for e in draft.evidence}
    return [check_sentence(s, evidence_tokens)
            for para in split_paragraphs(draft.body) for s in split_sentences(para)]


def unsupported_claims(draft: Draft) -> list[str]:
    """Sentences in a draft that are claims without support (used as a publish guardrail)."""
    return [c.sentence for c in check_draft(draft) if c.is_claim and not c.supported]


class FactCheckAgent(Agent):
    """Strips or bounces unsupported claims."""

    name = "factcheck"

    def __init__(self, db: Database, max_revisions: int = 2,
                 max_unsupported_ratio: float = 0.25) -> None:
        super().__init__()
        self.db = db
        self.max_revisions = max_revisions
        self.max_unsupported_ratio = max_unsupported_ratio

    @staticmethod
    def remove_sentences(body: str, bad: set[str]) -> str:
        """Drop flagged sentences, keeping paragraph structure."""
        paragraphs = []
        for para in split_paragraphs(body):
            kept = [s for s in split_sentences(para) if s not in bad]
            if kept:
                paragraphs.append(" ".join(kept))
        return "\n\n".join(paragraphs)

    def check(self, draft: Draft, state: NewsroomState) -> Draft:
        """Fact-check one draft and set its status."""
        start = time.perf_counter()
        checks = check_draft(draft)
        claims = [c for c in checks if c.is_claim]
        bad = [c for c in claims if not c.supported]
        draft.claims = [c.to_dict() for c in checks]
        ratio = len(bad) / len(claims) if claims else 1.0
        lead_bad = bool(claims) and not claims[0].supported
        if not claims:
            reasons = ["no sourced claims at all: the piece needs grounded facts"]
        elif ratio > self.max_unsupported_ratio or lead_bad:
            reasons = [f"unsupported claim ({c.reason}): {c.sentence}" for c in bad]
        else:
            reasons = []
        if reasons:
            self.db.log_rejection(state.run_id, draft, self.name, reasons)
            draft.rejection_history.append({"agent": self.name, "revision": draft.revision,
                                            "reasons": reasons})
            if draft.revision < self.max_revisions:
                draft.status, draft.feedback = "needs_revision", reasons
                self.log(state, "sent_back", f"{len(bad)}/{len(claims)} claims unsupported",
                         draft.id)
            else:
                draft.status = "rejected"
                self.log(state, "rejected", "unsupported claims after max revisions", draft.id)
        else:
            if bad:
                draft.body = self.remove_sentences(draft.body, {c.sentence for c in bad})
                for c in bad:
                    self.log(state, "removed_claim", f"{c.reason}: {c.sentence}", draft.id)
            draft.status = "checked"
            self.log(state, "checked", f"{len(claims) - len(bad)}/{len(claims)} claims "
                     "supported", draft.id)
        draft.add_metrics(latency_s=time.perf_counter() - start)
        return draft

    def run(self, state: NewsroomState) -> NewsroomState:
        for draft in state.drafts_with_status("drafted"):
            self.check(draft, state)
            self.db.save_draft(draft, state.run_id)
        return state
