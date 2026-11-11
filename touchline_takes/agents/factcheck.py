"""Fact-check agent: every claim must trace to cited evidence, and must not contradict it.

A sentence is a *claim* if it contains numbers or proper nouns (or cites
evidence). Checks run in order, and the first failure decides the verdict:

1. **Citation**: the claim cites at least one known evidence id.
2. **Tokens**: every number and proper noun in the claim appears in the cited evidence.
3. **Relations** (see :mod:`touchline_takes.tools.relations`):
   * a scoreline's winner/score/draw matches what the source says about that fixture;
   * a number pinned on a team matches the cited stats/model record for that team;
   * a number with a unit ("6 weeks", "45%") appears with the same unit in the evidence.
4. **LLM verifier** (optional, ``FACTCHECK_VERIFIER=llm``): an LLM judges whether the
   rule-passing claims are entailed by their evidence.

Unsupported claims are removed when they are a small minority. A draft goes back to
the Writer if too many claims fail, if the lead claim fails, or if any claim
*contradicts* its source (a confused draft is rewritten, not patched).
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from functools import lru_cache

from touchline_takes.agents.base import Agent
from touchline_takes.config import Settings
from touchline_takes.db import Database
from touchline_takes.state import Draft, Evidence, NewsroomState
from touchline_takes.tools.llm import LLMClient, LLMError, parse_json_object
from touchline_takes.tools.relations import (attribution_matches, extract_results,
                                             headline_winner, number_units, result_conflict,
                                             team_number_pairs)
from touchline_takes.tools.teams import TeamDirectory
from touchline_takes.tools.text import (citations, factual_tokens, split_paragraphs,
                                        split_sentences, strip_citations, word_tokens)

STRUCTURED_KINDS = {"stats", "model", "fixture"}


@dataclass
class ClaimCheck:
    """Verdict on one sentence."""

    sentence: str
    is_claim: bool
    supported: bool
    cited: list[str]
    missing: list[str]
    reason: str = ""
    kind: str = ""  # opinion | ok | no_citation | unknown_citation | missing_token |
    #                 result_conflict | attribution | unit | verifier

    @property
    def contradiction(self) -> bool:
        """True when the claim contradicts its evidence (not merely lacks support)."""
        return self.kind in {"result_conflict", "attribution", "unit"} or (
            self.kind == "verifier" and "contradict" in self.reason)

    def to_dict(self) -> dict:
        """Plain-dict form stored on the draft."""
        return {"sentence": self.sentence, "is_claim": self.is_claim,
                "supported": self.supported, "cited": self.cited, "missing": self.missing,
                "reason": self.reason, "kind": self.kind}


@lru_cache(maxsize=1)
def default_teams() -> TeamDirectory:
    """Team directory from the default settings (used when none is injected)."""
    return TeamDirectory.from_file(Settings().teams_path)


@dataclass
class ClaimChecker:
    """Checks sentences against a fixed set of evidence records."""

    evidence: list[Evidence]
    teams: TeamDirectory | None = None
    relations: bool = True
    _tokens: dict[str, set[str]] = field(init=False, default_factory=dict)

    def __post_init__(self) -> None:
        self.teams = self.teams or default_teams()
        self._by_id = {e.id: e for e in self.evidence}
        self._tokens = {e.id: word_tokens(e.text) for e in self.evidence}

    def _relation_problem(self, sentence: str, cited: list[str]) -> tuple[str, str] | None:
        """``(kind, reason)`` for the first relation-level contradiction, if any."""
        records = [self._by_id[c] for c in cited]
        claim_text = strip_citations(sentence)
        evidence_results = [r for e in records for r in extract_results(e.text, self.teams)]
        claimed_results = extract_results(claim_text, self.teams)
        for claimed in claimed_results:
            conflict = result_conflict(claimed, evidence_results)
            if conflict:
                return "result_conflict", conflict
        if not claimed_results:  # "X beat Y" with no scoreline
            conflict = self._winner_conflict(claim_text, records, evidence_results)
            if conflict:
                return "result_conflict", conflict
        attribution = self._attribution_problem(claim_text, records)
        if attribution:
            return "attribution", attribution
        ev_units = set().union(*(number_units(e.text) for e in records))
        ev_numbers = {n for n, _ in ev_units}
        for number, unit in sorted(number_units(claim_text)):
            if number in ev_numbers and (number, unit) not in ev_units:
                units = sorted(u for n, u in ev_units if n == number)
                return "unit", f"unit mismatch: '{number} {unit}' but evidence has " \
                               f"{', '.join(f'{number} {u}' for u in units)}"
        return None

    def _accept_team_aliases(self, sentence: str, cited: list[str],
                             missing: list[str]) -> list[str]:
        """Allow a team's formal names to stand in for each other.

        "Manchester City" in a claim is supported by "Man City" in the source. Only the
        directory's formal aliases count (ambiguous nicknames like "the Magpies" were
        removed from it), so this can't attach a claim to the wrong club.
        """
        if not missing:
            return missing
        claim = strip_citations(sentence)
        evidence = " ".join(self._by_id[c].text for c in cited).lower()
        accepted: set[str] = set()
        for team, start, end in self.teams.find_team_spans(claim):
            if any(re.search(rf"(?<![\w'])({re.escape(alias.lower())})(?!\w)", evidence)
                   for alias in self.teams.aliases(team)):
                accepted |= word_tokens(claim[start:end])
        return [t for t in missing if t not in accepted]

    def _attribution_problem(self, claim_text: str, records: list[Evidence]) -> str | None:
        """A number pinned on the wrong team, judged against cited stats/model records."""
        structured = [e for e in records if e.kind in STRUCTURED_KINDS]
        if not structured:
            return None
        ev_triples = set().union(*(team_number_pairs(e.text, self.teams) for e in structured))
        covered = {team for _, _, team in ev_triples}
        story_tokens = set().union(set(), *(self._tokens[e.id] for e in records
                                            if e.kind not in STRUCTURED_KINDS))
        for triple in sorted(team_number_pairs(claim_text, self.teams)):
            number, unit, team = triple
            if team in covered and number not in story_tokens \
                    and not attribution_matches(triple, ev_triples):
                owners = sorted({t for n, u, t in ev_triples
                                 if n == number and (not unit or u == unit)})
                where = f" (the evidence gives it to {', '.join(owners)})" if owners else ""
                return f"wrong team for {f'{number} {unit}'.strip()}: {team}{where}"
        return None

    def _winner_conflict(self, claim_text: str, records: list[Evidence],
                         evidence_results: list) -> str | None:
        """Who-beat-whom stated without a score, checked against the sources."""
        claimed = headline_winner(claim_text, self.teams)
        if not claimed:
            return None
        pair = frozenset(claimed)
        stated = [(r.winner, next(iter(r.teams - {r.winner}))) for r in evidence_results
                  if r.teams == pair and r.winner]
        for record in records:
            record_teams = self.teams.find_teams(record.text)
            for sentence in re.split(r"(?<=[.!?:])\s+", record.text):
                found = headline_winner(sentence, self.teams, record_teams)
                if found and frozenset(found) == pair:
                    stated.append(found)
        if stated and claimed not in stated:
            return (f"contradicts source: claim says {claimed[0]} beat {claimed[1]}, source says "
                    f"{stated[0][0]} beat {stated[0][1]}")
        return None

    def check(self, sentence: str) -> ClaimCheck:
        """Check one sentence."""
        tokens = factual_tokens(sentence)
        cited = citations(sentence)
        if not tokens and not cited:
            return ClaimCheck(sentence, False, True, [], [], "opinion", "opinion")
        if not cited:
            return ClaimCheck(sentence, True, False, [], tokens, "no source cited",
                              "no_citation")
        unknown = [c for c in cited if c not in self._tokens]
        if unknown:
            return ClaimCheck(sentence, True, False, cited, tokens,
                              f"cites unknown evidence {', '.join(unknown)}",
                              "unknown_citation")
        pool: set[str] = set().union(*(self._tokens[c] for c in cited))
        missing = self._accept_team_aliases(sentence, cited,
                                            [t for t in tokens if t not in pool])
        if missing:
            return ClaimCheck(sentence, True, False, cited, missing,
                              f"not in cited evidence: {', '.join(missing)}", "missing_token")
        if self.relations:
            problem = self._relation_problem(sentence, cited)
            if problem:
                return ClaimCheck(sentence, True, False, cited, [], problem[1], problem[0])
        return ClaimCheck(sentence, True, True, cited, [], "supported", "ok")


def check_draft(draft: Draft, teams: TeamDirectory | None = None,
                relations: bool = True) -> list[ClaimCheck]:
    """Check every sentence of a draft with the deterministic rules."""
    checker = ClaimChecker(draft.evidence, teams, relations)
    return [checker.check(s) for para in split_paragraphs(draft.body)
            for s in split_sentences(para)]


def unsupported_claims(draft: Draft) -> list[str]:
    """Sentences in a draft that are claims without support (used as a publish guardrail)."""
    return [c.sentence for c in check_draft(draft) if c.is_claim and not c.supported]


class LLMVerifier:
    """Asks an LLM whether each rule-passing claim is entailed by its cited evidence.

    One call per draft (claims are batched) so it fits the per-run LLM budget.
    """

    SYSTEM = ("You are a strict football fact-checker. For each claim, decide whether the "
              "quoted evidence fully supports it. Treat opinion as out of scope. Reply with "
              "JSON only.")

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    def prompt(self, claims: list[ClaimCheck], evidence: dict[str, Evidence]) -> str:
        """Batched verification prompt."""
        lines = ["Evidence:"]
        used = sorted({c for claim in claims for c in claim.cited})
        lines += [f"[{eid}] {evidence[eid].text}" for eid in used]
        lines += ["", "Claims:"]
        lines += [f"{i}. {strip_citations(c.sentence)} (cites {', '.join(c.cited)})"
                  for i, c in enumerate(claims, 1)]
        lines += ["", 'Return {"results": [{"id": <claim number>, "verdict": "supported" | '
                  '"contradicted" | "not_enough_info", "reason": "<short>"}]}']
        return "\n".join(lines)

    def verify(self, claims: list[ClaimCheck], evidence: dict[str, Evidence]
               ) -> dict[int, tuple[str, str]]:
        """``{claim index: (verdict, reason)}`` for claims that are not supported."""
        if not claims:
            return {}
        data = parse_json_object(self.llm.complete(self.prompt(claims, evidence),
                                                   self.SYSTEM, max_tokens=800).text)
        verdicts = {}
        try:
            for item in data.get("results", []):
                idx, verdict = int(item["id"]) - 1, str(item["verdict"])
                if 0 <= idx < len(claims) and verdict in {"contradicted", "not_enough_info"}:
                    verdicts[idx] = (verdict, str(item.get("reason", ""))[:200])
        except (KeyError, TypeError, ValueError) as exc:
            raise LLMError(f"bad verifier output: {exc}") from exc
        return verdicts


class FactCheckAgent(Agent):
    """Strips or bounces unsupported and contradicted claims."""

    name = "factcheck"

    def __init__(self, db: Database, max_revisions: int = 2,
                 max_unsupported_ratio: float = 0.25, teams: TeamDirectory | None = None,
                 verifier: LLMVerifier | None = None, relations: bool = True) -> None:
        super().__init__()
        self.db = db
        self.max_revisions = max_revisions
        self.max_unsupported_ratio = max_unsupported_ratio
        self.teams = teams
        self.verifier = verifier
        self.relations = relations

    @staticmethod
    def remove_sentences(body: str, bad: set[str]) -> str:
        """Drop flagged sentences, keeping paragraph structure."""
        paragraphs = []
        for para in split_paragraphs(body):
            kept = [s for s in split_sentences(para) if s not in bad]
            if kept:
                paragraphs.append(" ".join(kept))
        return "\n\n".join(paragraphs)

    def _apply_verifier(self, draft: Draft, checks: list[ClaimCheck],
                        state: NewsroomState) -> None:
        """Downgrade rule-passing claims the LLM verifier rejects (in place)."""
        passing = [c for c in checks if c.is_claim and c.supported]
        try:
            verdicts = self.verifier.verify(passing, {e.id: e for e in draft.evidence})
        except LLMError as exc:
            self.log(state, "verifier_fallback", str(exc), draft.id)
            return
        for idx, (verdict, reason) in verdicts.items():
            claim = passing[idx]
            claim.supported, claim.kind = False, "verifier"
            claim.reason = f"LLM verifier: {verdict.replace('_', ' ')} ({reason})"

    def check(self, draft: Draft, state: NewsroomState) -> Draft:
        """Fact-check one draft and set its status."""
        start = time.perf_counter()
        checks = check_draft(draft, self.teams, self.relations)
        if self.verifier is not None:
            self._apply_verifier(draft, checks, state)
        claims = [c for c in checks if c.is_claim]
        bad = [c for c in claims if not c.supported]
        contradictions = [c for c in bad if c.contradiction]
        draft.claims = [c.to_dict() for c in checks]
        draft.add_metrics(claims_checked=len(claims), claims_unsupported=len(bad),
                          claims_contradicted=len(contradictions))
        ratio = len(bad) / len(claims) if claims else 1.0
        lead_bad = bool(claims) and not claims[0].supported
        if not claims:
            reasons = ["no sourced claims at all: the piece needs grounded facts"]
        elif ratio > self.max_unsupported_ratio or lead_bad or contradictions:
            reasons = [f"{'contradicted' if c.contradiction else 'unsupported'} claim "
                       f"({c.reason}): {c.sentence}" for c in bad]
        else:
            reasons = []
        if reasons:
            self._bounce(draft, state, reasons, f"{len(bad)}/{len(claims)} claims failed "
                         f"({len(contradictions)} contradicted)")
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

    def _bounce(self, draft: Draft, state: NewsroomState, reasons: list[str],
                summary: str) -> None:
        """Send a draft back to the Writer, or reject it after the last revision."""
        self.db.log_rejection(state.run_id, draft, self.name, reasons)
        draft.rejection_history.append({"agent": self.name, "revision": draft.revision,
                                        "reasons": reasons})
        if draft.revision < self.max_revisions:
            draft.status, draft.feedback = "needs_revision", reasons
            self.log(state, "sent_back", summary, draft.id)
        else:
            draft.status = "rejected"
            self.log(state, "rejected", f"{summary} after max revisions", draft.id)

    def run(self, state: NewsroomState) -> NewsroomState:
        for draft in state.drafts_with_status("drafted"):
            self.check(draft, state)
            self.db.save_draft(draft, state.run_id)
        return state
