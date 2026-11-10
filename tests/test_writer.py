"""Tests for the Writer agent."""
# pylint: disable=redefined-outer-name

import pandas as pd
import pytest

from touchline_takes.agents.writer import TAKES, VERDICTS, Assignment, WriterAgent
from touchline_takes.config import Settings
from touchline_takes.state import NewsroomState
from touchline_takes.tools.llm import FakeLLM, GuardedLLM, ScriptedWriterLLM
from touchline_takes.tools.stats import ResultsStore
from touchline_takes.tools.teams import TeamDirectory
from touchline_takes.tools.text import citations, is_claim

from tests.conftest import make_story

RESULTS = pd.DataFrame({
    "Date": pd.to_datetime(["2025-01-04", "2025-01-11", "2025-01-18"]),
    "HomeTeam": ["Arsenal", "Chelsea", "Arsenal"], "AwayTeam": ["Chelsea", "Wolves", "Wolves"],
    "FTHG": [2, 1, 3], "FTAG": [0, 1, 1], "FTR": ["H", "D", "H"]})


@pytest.fixture
def teams():
    """Team directory."""
    return TeamDirectory.from_file(Settings().teams_path)


@pytest.fixture
def story(db):
    """A stored, classified match-report story."""
    item = make_story(league="Premier League", teams=["Arsenal", "Chelsea"],
                      topic="match_report", sentiment="positive", emotion="joy")
    db.insert_story(item)
    db.update_classification(item)
    return item


def make_writer(db, teams, llm=None):
    """Writer with a tiny results table."""
    return WriterAgent(db, teams, ResultsStore(RESULTS, "test results"), llm=llm)


def test_takes_are_opinion_not_claims():
    """House opinion lines must never contain checkable facts."""
    for lines in TAKES.values():
        for line in lines:
            assert not is_claim(line), line
    for line in VERDICTS.values():
        assert not is_claim(line), line


def test_template_match_report_is_grounded(db, teams, story):
    """Every factual sentence carries a citation; stats evidence is attached."""
    state = make_writer(db, teams).run(NewsroomState(stories=[story]))
    draft = state.drafts[0]
    assert draft.article_type == "match_report" and draft.mode == "template"
    assert draft.title == "Arsenal v Chelsea: the Touchline Take"
    assert "Arsenal beat Chelsea 2-1" in draft.body
    assert {"S1", "ST1", "ST2"} <= {e.id for e in draft.evidence}
    assert set(citations(draft.body)) <= {e.id for e in draft.evidence}
    assert draft.sources[0]["url"] == story.url
    assert db.unused_stories() == []  # story marked as used


def test_preview_uses_model_and_stats(db, teams):
    """Previews cite the fixture, the Analyst model and form data."""
    fixture = {"id": "fx1", "date": "2026-11-21", "league": "Premier League",
               "home": "Arsenal", "away": "Chelsea", "probs": {"H": 0.5, "D": 0.3, "A": 0.2}}
    comp = make_writer(db, teams).compose(Assignment("preview", fixture=fixture))
    text = " ".join(comp.facts)
    assert "50% chance" in text and "[M1]" in text and "[F1]" in text
    assert "2025-01-04" in text  # last meeting from results data
    assert "back Arsenal [M1]" in comp.takes[-1]


def test_llm_path_and_budget_fallback(db, teams, story):
    """The LLM restyles facts; when the budget is spent the template is used."""
    state = make_writer(db, teams, ScriptedWriterLLM()).run(NewsroomState(stories=[story]))
    draft = state.drafts[0]
    assert draft.mode == "llm" and draft.metrics["llm_calls"] == 1
    assert draft.title == "Arsenal v Chelsea: the Touchline Take"

    other = make_story(2, title="Spurs boss sacked", summary="Tottenham sacked their coach.",
                       teams=["Tottenham"], topic="manager", sentiment="negative")
    broke = GuardedLLM(FakeLLM(["unused"]), max_calls=0)
    state = make_writer(db, teams, broke).run(NewsroomState(stories=[other]))
    assert state.drafts[0].mode == "template"
    assert any(log.action == "llm_fallback" for log in state.logs)


def test_revise_increments_and_skips_known(db, teams, story):
    """Revisions bump the counter; already-drafted assignments are not re-planned."""
    writer = make_writer(db, teams)
    state = writer.run(NewsroomState(stories=[story]))
    draft = state.drafts[0]
    draft.status, draft.feedback = "needs_revision", ["too short: 50 words"]
    writer.run(state)
    assert draft.revision == 1 and draft.status == "drafted"
    assert writer.plan(NewsroomState(stories=[story])) == []
