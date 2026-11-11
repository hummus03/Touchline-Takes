"""Tests for the "How we check" numbers: newsroom stats and the prediction scorecard."""
# pylint: disable=redefined-outer-name

import pandas as pd
import pytest

from touchline_takes.config import Settings
from touchline_takes.state import Draft
from touchline_takes.tools.teams import TeamDirectory
from touchline_takes.transparency import newsroom_stats, prediction_scorecard


@pytest.fixture
def teams():
    """The real team directory."""
    return TeamDirectory.from_file(Settings().teams_path)


def add_fixture(db, fid, date, home, away, probs):
    """A fixture with a stored prediction."""
    db.upsert_fixture({"id": fid, "date": date, "league": "Premier League", "home": home,
                       "away": away, "source": "test"})
    db.upsert_prediction(fid, probs, max(probs, key=probs.get), "logreg-v1")


def results(rows):
    """A results table in the Football-Data.co.uk shape, with Bet365 odds."""
    return pd.DataFrame([{"Date": pd.Timestamp(d), "HomeTeam": h, "AwayTeam": a, "FTHG": hg,
                          "FTAG": ag, "FTR": r, "B365H": oh, "B365D": od, "B365A": oa}
                         for d, h, a, hg, ag, r, oh, od, oa in rows])


def test_scorecard_grades_frozen_predictions_against_results_and_the_bookmaker(db, teams):
    """Played fixtures are matched to results (fixture names to results-file names, a day
    either side for time zones), scored, and compared with Bet365's margin-free odds."""
    add_fixture(db, "f1", "2026-11-21", "Man City", "Fulham", {"H": .69, "D": .2, "A": .11})
    add_fixture(db, "f2", "2026-11-22", "Liverpool", "Man United", {"H": .47, "D": .29,
                                                                    "A": .24})
    add_fixture(db, "f3", "2026-11-22", "Leeds United", "Everton", {"H": .4, "D": .3, "A": .3})
    add_fixture(db, "f4", "2026-12-20", "Arsenal", "Chelsea", {"H": .5, "D": .3, "A": .2})
    table = results([
        ("2026-11-21", "Man City", "Fulham", 3, 1, "H", 1.3, 6.0, 9.0),
        ("2026-11-23", "Liverpool", "Man United", 1, 2, "A", 1.8, 3.8, 4.2),  # next day (UTC)
    ])
    card = prediction_scorecard(db, table, teams, today="2026-11-25")
    assert card["graded"] == 2 and card["pending"] == 1  # Leeds v Everton: no result yet
    assert card["accuracy"] == pytest.approx(0.5) and card["home_accuracy"] == pytest.approx(.5)
    city = next(g for g in card["recent"] if g["home"] == "Man City")
    assert city["correct"] and city["score"] == "3-1"
    assert city["brier"] == pytest.approx(.31 ** 2 + .2 ** 2 + .11 ** 2)
    assert card["book_graded"] == 2 and card["book_accuracy"] == pytest.approx(0.5)
    raw = [1 / 1.3, 1 / 6.0, 1 / 9.0]
    book_h = raw[0] / sum(raw)
    assert card["book_brier"] < 1 and 0 < book_h < 1
    assert all(g["date"] < "2026-11-25" for g in card["recent"])  # the December game waits


def test_played_fixtures_leave_the_upcoming_list(db):
    """The home page shows upcoming fixtures only; the scorecard sees the played ones."""
    add_fixture(db, "old", "2026-11-01", "Arsenal", "Chelsea", {"H": .5, "D": .3, "A": .2})
    add_fixture(db, "new", "2026-12-01", "Arsenal", "Fulham", {"H": .6, "D": .2, "A": .2})
    upcoming = db.fixtures_with_predictions(10, upcoming=True, today="2026-11-20")
    assert [f["id"] for f in upcoming] == ["new"]
    assert [f["id"] for f in db.past_predictions("2026-11-20")] == ["old"]


def test_newsroom_stats_add_up_runs_drafts_and_cost(db):
    """Totals come from the run summaries and every draft's fact-check metrics."""
    for i, (new, skipped, calls, cost) in enumerate([(10, 4, 6, .01), (3, 1, 2, .004)]):
        db.record_run(f"r{i}", f"2026-11-1{i}T07:23:00+00:00", {
            "ingest": {"fetched": 160, "new": new, "skipped": skipped, "duplicates": 0},
            "llm": {"calls": calls, "cost_usd": cost},
            "analyst": {"test_accuracy": .45, "test_roc_auc": .62}})
    good = Draft(id="d1", article_type="explainer", title="A", body="b", evidence=[],
                 status="in_review", mode="llm", revision=1,
                 metrics={"claims_checked": 8, "claims_unsupported": 2, "claims_contradicted": 1})
    bad = Draft(id="d2", article_type="explainer", title="B", body="b", evidence=[],
                status="rejected", mode="llm", revision=2,
                metrics={"claims_checked": 4, "claims_unsupported": 4})
    for draft in (good, bad):
        db.save_draft(draft, "r0")
    stats = newsroom_stats(db, [{"draft_id": "d1", "mode": "llm"}])
    assert stats["runs"] == 2 and stats["since"] == "2026-11-10"
    assert stats["stories_new"] == 13 and stats["stories_skipped"] == 5
    assert stats["drafts"] == 2 and stats["published"] == 1 and stats["not_published"] == 1
    assert stats["claims_checked"] == 12 and stats["claims_unsupported"] == 6
    assert stats["unsupported_rate"] == pytest.approx(.5) and stats["rejected"] == 1
    assert stats["llm_calls"] == 8 and stats["cost_per_claude_article"] == pytest.approx(.014)
    assert stats["model_test_roc_auc"] == pytest.approx(.62)
