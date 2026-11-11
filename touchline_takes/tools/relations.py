"""Relation-level fact checks that go beyond "the same words appear in the source".

Token matching confirms *what* a claim mentions, not *how* the facts relate.
These helpers catch three kinds of error that token matching misses:

* **Result direction and score**: "Chelsea beat Arsenal 2-1" against a source saying
  Arsenal won 2-1 (or 3-1, or that it was a draw).
* **Team-number attribution**: a stat or probability pinned on the wrong team when
  the cited stats/model evidence covers both teams.
* **Number-unit pairing**: "out for 6 months" when the source says "6 weeks".
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from touchline_takes.tools.teams import TeamDirectory

SCORE_RE = re.compile(r"(?<![\d\-–])(\d{1,2})\s?[-–]\s?(\d{1,2})(?![\d\-–])")
DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
DRAW_RE = re.compile(r"\b(draw|drew|drawn|goalless|stalemate|level|all square)\b", re.I)
PASSIVE_RE = re.compile(r"\b(stunned|beaten|thrashed|defeated|humbled|edged|hammered|"
                        r"routed|swept aside|knocked out)\b.*\bby\b", re.I)
LOSS_RE = re.compile(r"\b(lost|lose|loses|losing|fell|slumped|crashed|succumbed|"
                     r"defeat (?:at|to|away|against|by|in)|defeat\b(?! of))", re.I)
WIN_RE = re.compile(r"\b(beat|beats|thrash\w*|win|wins|won|victory|come from behind|"
                    r"came from behind|edged|overcame|saw off|hammered|routed|defeat of|"
                    r"defeated|outclassed)\b", re.I)
UNITS = {"win", "draw", "defeat", "loss", "point", "goal", "minute", "week", "month",
         "year", "day", "match", "game", "save", "shot", "appearance", "million", "billion",
         "assist", "card", "season", "trophy", "title", "cap", "start", "chance", "percent",
         "second", "hour"}
NUMBER_UNIT_RE = re.compile(r"(?<![\d\-])(\d+(?:\.\d+)?)(?:st|nd|rd|th)?(%|[\s\-]+([A-Za-z]+))")


def lemma(word: str) -> str:
    """Crude singular form ('matches' -> 'match', 'goals' -> 'goal')."""
    word = word.lower()
    for suffix, repl in (("ches", "ch"), ("shes", "sh"), ("sses", "ss"), ("ies", "y")):
        if word.endswith(suffix):
            return word[: -len(suffix)] + repl
    return word[:-1] if word.endswith("s") and not word.endswith("ss") else word


@dataclass(frozen=True)
class MatchResult:
    """A result between two teams, with the winner if the text makes it clear."""

    teams: frozenset[str]
    score: tuple[int, int]  # (high, low)
    winner: str | None
    draw: bool

    def describe(self) -> str:
        """Human-readable form for rejection reasons."""
        high, low = self.score
        if self.draw:
            return f"{' and '.join(sorted(self.teams))} drew {high}-{low}"
        if self.winner:
            loser = next(iter(self.teams - {self.winner}))
            return f"{self.winner} beat {loser} {high}-{low}"
        return f"{' and '.join(sorted(self.teams))} finished {high}-{low}"


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+|\n+", text or "") if s.strip()]


def extract_results(text: str, teams: TeamDirectory) -> list[MatchResult]:
    """Results stated in ``text`` (one per sentence that names two teams and a score)."""
    results = []
    for sentence in _sentences(DATE_RE.sub(" ", text)):
        spans, seen = [], set()
        for team, start, end in teams.find_team_spans(sentence):
            if team not in seen:
                seen.add(team)
                spans.append((team, start, end))
        score = SCORE_RE.search(sentence)
        if len(spans) < 2 or not score:
            continue
        (first, _, first_end), (second, second_start, _) = spans[0], spans[1]
        goals = int(score.group(1)), int(score.group(2))
        high, low = max(goals), min(goals)
        pair = frozenset({first, second})
        between = sentence[first_end:second_start]
        if high == low and not DRAW_RE.search(sentence) and WIN_RE.search(sentence):
            # "Liverpool beat Everton 0-0" asserts a win at a level score: keep it as a win
            # so it conflicts with a source that reports a draw.
            results.append(MatchResult(pair, (high, low), first, False))
        elif high == low:
            results.append(MatchResult(pair, (high, low), None, True))
        elif SCORE_RE.fullmatch(between.strip()):  # "Newcastle 0-2 Manchester City"
            results.append(MatchResult(pair, (high, low),
                                       first if goals[0] > goals[1] else second, False))
        elif PASSIVE_RE.search(between) or PASSIVE_RE.search(sentence[:second_start]):
            results.append(MatchResult(pair, (high, low), second, False))
        elif LOSS_RE.search(between):
            results.append(MatchResult(pair, (high, low), second, False))
        elif WIN_RE.search(between) or WIN_RE.search(sentence[:first_end + 40]):
            results.append(MatchResult(pair, (high, low), first, False))
        elif DRAW_RE.search(sentence):
            results.append(MatchResult(pair, (high, low), None, True))
        else:
            results.append(MatchResult(pair, (high, low), None, False))
    return results


def headline_winner(title: str, teams: TeamDirectory, story_teams: list[str] | None = None
                    ) -> tuple[str, str] | None:
    """``(winner, loser)`` when a headline states a result without a scoreline.

    "Man City thrash Wolves" -> (Manchester City, Wolves); "Real Madrid stunned by
    Sevilla" -> (Sevilla, Real Madrid). If the headline names only one known club
    ("Man City thrash Inter") and the story involves exactly two, the other one is
    taken from ``story_teams``. ``None`` whenever it isn't clear.
    """
    spans, seen = [], set()
    for team, start, end in teams.find_team_spans(title):
        if team not in seen:
            seen.add(team)
            spans.append((team, start, end))
    if not spans or DRAW_RE.search(title):
        return None
    first, _, first_end = spans[0]
    # The second club in the headline is only the opponent if nothing else is named in
    # between ("Man City thrash Inter as Liverpool watch" is not City v Liverpool).
    if len(spans) >= 2 and not re.search(r"\b[A-Z]", title[first_end:spans[1][1]]):
        second, second_start = spans[1][0], spans[1][1]
        between = title[first_end:second_start]
    elif story_teams and len(story_teams) == 2 and first in story_teams:
        second = next(t for t in story_teams if t != first)
        between = title[first_end:first_end + 40]
    else:
        return None
    if PASSIVE_RE.search(between) or LOSS_RE.search(between):
        return second, first
    if WIN_RE.search(between):
        return first, second
    return None


def result_conflict(claim: MatchResult, evidence: list[MatchResult]) -> str | None:
    """Explain how ``claim`` contradicts the evidence, or ``None`` if it doesn't.

    Evidence that never mentions this pair of teams cannot contradict the claim.
    """
    same_pair = [e for e in evidence if e.teams == claim.teams]
    if not same_pair:
        return None
    for ev in same_pair:
        if ev.score != claim.score:
            continue
        if ev.draw != claim.draw:
            continue
        if claim.winner and ev.winner and claim.winner != ev.winner:
            continue
        return None
    return f"contradicts source: claim says {claim.describe()}, source says " + "; ".join(
        dict.fromkeys(e.describe() for e in same_pair))


def team_number_pairs(text: str, teams: TeamDirectory) -> set[tuple[str, str, str]]:
    """``(number, unit, team)`` triples; each number goes to the nearest preceding team.

    ``unit`` is the following unit word (lemmatised, ``%`` for percentages) or ``""``.
    Dates and scorelines are ignored (they are checked elsewhere).
    """
    triples = set()
    for sentence in _sentences(text):
        cleaned = SCORE_RE.sub(" ", DATE_RE.sub(" ", sentence))
        spans = teams.find_team_spans(cleaned)
        for match in re.finditer(r"(?<![\w.])(\d+(?:\.\d+)?)(%|\s+([A-Za-z]+))?", cleaned):
            before = [t for t, start, _ in spans if start < match.start()]
            if not before:
                continue
            unit = "%" if match.group(2) == "%" else lemma(match.group(3) or "")
            triples.add((match.group(1), unit if unit in UNITS or unit == "%" else "",
                         before[-1]))
    return triples


def attribution_matches(claim: tuple[str, str, str], evidence: set[tuple[str, str, str]]
                        ) -> bool:
    """True if the evidence gives the same number (and unit, when both have one) to the team."""
    number, unit, team = claim
    return any(n == number and t == team and (not unit or not u or u == unit)
               for n, u, t in evidence)


def number_units(text: str) -> set[tuple[str, str]]:
    """``(number, unit)`` pairs such as ``("6", "week")``, ``("45", "%")``."""
    out = set()
    for match in NUMBER_UNIT_RE.finditer(text or ""):
        if match.group(2) == "%":
            out.add((match.group(1), "%"))
            out.add((match.group(1), "percent"))
        elif match.group(3) and lemma(match.group(3)) in UNITS:
            out.add((match.group(1), lemma(match.group(3))))
    return out
