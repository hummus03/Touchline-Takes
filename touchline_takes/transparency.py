"""Numbers for the public "How we check" page, computed from the newsroom's own records.

* :func:`newsroom_stats`: what the pipeline read, wrote, checked, rejected and spent,
  from the run summaries and every draft's metrics.
* :func:`prediction_scorecard`: the Analyst's pre-match predictions against the real
  results, next to the bookmaker (Bet365 odds from the same Football-Data.co.uk files).
"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

from touchline_takes.db import Database
from touchline_takes.tools.teams import TeamDirectory

OUTCOMES = ("H", "D", "A")
SUFFIXES = {"United", "City", "Town", "FC", "AFC", "Albion", "Hotspur", "Wanderers", "Rovers",
            "County", "Athletic"}


def newsroom_stats(db: Database, articles: list[dict[str, Any]]) -> dict[str, Any]:
    """Totals across every recorded run and draft (``articles``: what is published)."""
    runs = db.recent_runs(1_000_000)
    ingest = {"fetched": 0, "new": 0, "skipped": 0, "duplicates": 0}
    calls, cost = 0, 0.0
    for run in runs:
        summary = run["summary"]
        for key in ingest:
            ingest[key] += int(summary.get("ingest", {}).get(key) or 0)
        calls += int(summary.get("llm", {}).get("calls") or 0)
        cost += float(summary.get("llm", {}).get("cost_usd") or 0.0)
    drafts = db.all_drafts()
    claims = sum(int(d.metrics.get("claims_checked", 0)) for d in drafts)
    unsupported = sum(int(d.metrics.get("claims_unsupported", 0)) for d in drafts)
    contradicted = sum(int(d.metrics.get("claims_contradicted", 0)) for d in drafts)
    published_ids = {a.get("draft_id") for a in articles}
    claude_published = sum(1 for a in articles if a.get("mode") == "llm")
    latest = runs[0]["summary"].get("analyst", {}) if runs else {}
    return {
        "since": min((r["started_at"] or "")[:10] for r in runs) if runs else "",
        "runs": len(runs),
        "stories_read": ingest["fetched"], "stories_new": ingest["new"],
        "stories_skipped": ingest["skipped"], "stories_duplicate": ingest["duplicates"],
        "drafts": len(drafts),
        "drafts_claude": sum(1 for d in drafts if d.mode == "llm"),
        "revisions": sum(d.revision for d in drafts),
        "rejected": sum(1 for d in drafts if d.status == "rejected"),
        "not_published": sum(1 for d in drafts if d.id not in published_ids),
        "published": len(articles), "published_claude": claude_published,
        "claims_checked": claims, "claims_unsupported": unsupported,
        "claims_contradicted": contradicted,
        "unsupported_rate": unsupported / claims if claims else 0.0,
        "llm_calls": calls, "llm_cost_usd": cost,
        "cost_per_claude_article": cost / claude_published if claude_published else None,
        "model_test_accuracy": latest.get("test_accuracy"),
        "model_test_roc_auc": latest.get("test_roc_auc"),
    }


def _data_name(name: str, teams: TeamDirectory, known: set[str]) -> str | None:
    """The results-file name for a fixture's club ("Leeds United" -> "Leeds")."""
    candidates = [teams.data_name(name), name]
    words = name.split()
    if len(words) > 1 and words[-1] in SUFFIXES:
        candidates += [teams.data_name(" ".join(words[:-1])), " ".join(words[:-1])]
    return next((c for c in candidates if c in known), None)


def _brier(probs: dict[str, float], outcome: str) -> float:
    """Multi-class Brier score: 0 is perfect, 2/3 is a uniform guess."""
    return sum((probs[o] - (1.0 if o == outcome else 0.0)) ** 2 for o in OUTCOMES)


def _book_probs(row: pd.Series) -> dict[str, float] | None:
    """Bookmaker probabilities from decimal odds, with the margin taken out."""
    odds = [row.get(f"B365{o}") for o in OUTCOMES]
    if any(o is None or not isinstance(o, (int, float)) or math.isnan(o) or o <= 1
           for o in odds):
        return None
    raw = [1 / o for o in odds]
    return {o: p / sum(raw) for o, p in zip(OUTCOMES, raw)}


def _find_result(results: pd.DataFrame, date: str, home: str, away: str) -> pd.Series | None:
    """The played match: same clubs, within a day of the fixture date (time zones)."""
    when = pd.Timestamp(date)
    rows = results[(results.HomeTeam == home) & (results.AwayTeam == away)
                   & ((results.Date - when).abs() <= pd.Timedelta(days=1))]
    return rows.iloc[-1] if len(rows) else None


def prediction_scorecard(db: Database, results: pd.DataFrame, teams: TeamDirectory,
                         today: str | None = None, recent: int = 10) -> dict[str, Any]:
    """How the pre-match predictions did, next to Bet365 and an always-home-win guess."""
    known = set(results.get("HomeTeam", [])) | set(results.get("AwayTeam", []))
    graded: list[dict[str, Any]] = []
    pending = 0
    for row in db.past_predictions(today):
        home = _data_name(row["home"], teams, known)
        away = _data_name(row["away"], teams, known)
        match = _find_result(results, row["date"], home, away) if home and away else None
        if match is None:
            pending += 1  # played, but not in the results file yet
            continue
        probs = {"H": row["home_win"], "D": row["draw"], "A": row["away_win"]}
        outcome = str(match["FTR"])
        book = _book_probs(match)
        graded.append({
            "date": row["date"], "home": row["home"], "away": row["away"],
            "score": f"{int(match['FTHG'])}-{int(match['FTAG'])}", "result": outcome,
            "pick": max(probs, key=probs.get), "probs": probs,
            "correct": max(probs, key=probs.get) == outcome,
            "brier": _brier(probs, outcome),
            "book_pick": max(book, key=book.get) if book else None,
            "book_correct": (max(book, key=book.get) == outcome) if book else None,
            "book_brier": _brier(book, outcome) if book else None,
        })
    with_book = [g for g in graded if g["book_brier"] is not None]
    count = len(graded)
    return {
        "graded": count, "pending": pending,
        "accuracy": sum(g["correct"] for g in graded) / count if count else None,
        "brier": sum(g["brier"] for g in graded) / count if count else None,
        "home_accuracy": sum(g["result"] == "H" for g in graded) / count if count else None,
        "book_graded": len(with_book),
        "book_accuracy": (sum(g["book_correct"] for g in with_book) / len(with_book)
                          if with_book else None),
        "book_brier": (sum(g["book_brier"] for g in with_book) / len(with_book)
                       if with_book else None),
        "model_brier_same": (sum(g["brier"] for g in with_book) / len(with_book)
                             if with_book else None),
        "recent": graded[:recent],
    }
