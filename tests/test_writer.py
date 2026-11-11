"""Tests for the Writer agent."""
# pylint: disable=redefined-outer-name

import pandas as pd
import pytest

from touchline_takes.agents.writer import (DRAW_VERDICT, TAKES, TOPIC_VERDICTS, VERDICTS,
                                           Assignment, WriterAgent)
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
    for line in [*VERDICTS.values(), *TOPIC_VERDICTS.values(), DRAW_VERDICT]:
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


def test_result_fact_uses_relations_and_hyphenated_names(db, teams):
    """The lede names the winner from any phrasing; hyphenated names stay whole."""
    story = make_story(3, title="Paris Saint-Germain beaten 1-0 by Marseille",
                       summary="Paris Saint-Germain were beaten 1-0 by Marseille. Yanis "
                       "Belkacem scored.", league="Ligue 1",
                       teams=["Paris Saint-Germain", "Marseille"], topic="match_report")
    comp = make_writer(db, teams).compose(Assignment("match_report", story=story))
    assert comp.facts[0].startswith("Marseille beat Paris Saint-Germain 1-0")
    assert "The names in the frame: Yanis Belkacem [S1]." in comp.facts


# --- Patterns from the first live run on BBC Sport (paraphrased, not BBC's text) -------------

def story_with(summary, title="Headline", teams=(), topic="general", idx=9):
    """A classified story for writer tests."""
    return make_story(idx, title=title, summary=summary, teams=list(teams), topic=topic)


def test_names_cases(db, teams):
    """Run the byline/possessive cases (kept separate to keep parametrize readable)."""
    writer = make_writer(db, teams)
    cases = [
        ("Senior football correspondent Jo Bloggs looks inside Arsenal's summer plans.",
         ["Arsenal"], []),
        ("By Jo Bloggs. Arsenal want Leo Hartmann.", ["Arsenal"], ["Leo Hartmann"]),
        ("Chief football writer Sam Penn says Arsenal are favourites.", ["Arsenal"], []),
        ("The winner was scored by Leo Hartmann late on.", [], ["Leo Hartmann"]),
        ("Everyone remembers Pep Guardiola's Manchester City winning the cup four times.",
         ["Manchester City"], ["Pep Guardiola"]),
        ("Scott McTominay opens up about his recovery.", [], ["Scott McTominay"]),
    ]
    for summary, story_teams, expected in cases:
        assert writer._names(story_with(summary, teams=story_teams)) == expected, summary  # pylint: disable=protected-access


def test_detail_quotes_whole_phrases_only(db, teams):
    """A quote never stops mid-phrase ('...won four cups on the')."""
    writer = make_writer(db, teams)
    cut = story_with("You may know the club won four League Cups on the bounce between two "
                     "dates in a row back then, a run nobody has matched")
    frag = writer._detail(cut)  # pylint: disable=protected-access
    assert frag is None or frag.split()[-1].lower() not in {"the", "on", "of", "a"}
    whole = story_with("Arsenal were beaten at home. The keeper made seven saves in the game.")
    assert writer._detail(whole) == "The keeper made seven saves in the game"  # pylint: disable=protected-access


def test_headline_result_without_score(db, teams):
    """'Man City thrash Inter' names the winner in the lede and the verdict, with a citation."""
    story = story_with("Manchester City came from behind to beat Inter Milan in Europe.",
                       title="Man City thrash Inter in the Champions League",
                       teams=["Manchester City", "Inter Milan"], topic="match_report")
    comp = make_writer(db, teams).compose(Assignment("match_report", story=story))
    assert comp.facts[0] == "Manchester City beat Inter Milan, as reported by Test Wire [S1]."
    assert comp.takes[-1].startswith("The Touchline Take: Manchester City earned this one [S1]")


def test_topic_headlines_and_verdicts(db, teams):
    """No 'what the result story really means'; verdicts fit the topic."""
    story = story_with("Arsenal have a long shortlist of targets this summer.",
                       title="Arsenal draw up a shortlist", teams=["Arsenal"], topic="transfer")
    comp = make_writer(db, teams).compose(Assignment("explainer", story=story))
    assert comp.title == "Arsenal: the Touchline Take on the transfer talk"
    assert comp.facts[0] == "Test Wire has a transfer story involving Arsenal [S1]."
    assert comp.takes[-1] == TOPIC_VERDICTS["transfer"]


def test_one_article_per_team_and_topic(db, teams):
    """Several stories on the same club saga become one article; the rest are related."""
    stories = [make_story(i, title=f"Manager news {i}", summary="Manchester United boss talk.",
                          teams=["Manchester United"], topic="manager") for i in (20, 21, 22)]
    for story in stories:
        db.insert_story(story)
        db.update_classification(story)
    state = NewsroomState(stories=stories)
    plan = make_writer(db, teams).plan(state)
    assert len(plan) == 1
    assert sum(log.action == "merged" for log in state.logs) == 2
    assert db.unused_stories() == [s for s in db.unused_stories() if s.id == plan[0].story.id]


def test_nations_are_not_people(db, teams):
    """'Northern Ireland' is a national team, not a name in the frame."""
    writer = make_writer(db, teams)
    story = story_with("Dominik Szoboszlai faces a late fitness test before Hungary play "
                       "Northern Ireland.", teams=["Liverpool"])
    assert writer._names(story) == ["Dominik Szoboszlai"]  # pylint: disable=protected-access


def test_related_coverage_must_name_a_club_in_its_headline(db, teams):
    """A story that only mentions a club in passing isn't related coverage for it."""
    passing = make_story(30, title="Four mistakes that show Man Utd's defensive problems",
                         summary="United's defending was poor before they face Sunderland.",
                         teams=["Manchester United", "Sunderland"], topic="general")
    about = make_story(31, title="Sunderland sweat on striker's fitness",
                       summary="Sunderland's top scorer is a doubt.", teams=["Sunderland"],
                       topic="injury")
    for story in (passing, about):
        db.insert_story(story)
        db.update_classification(story)
    writer = make_writer(db, teams)
    related = writer._related("Aston Villa Sunderland", (), ["Aston Villa", "Sunderland"], 3)  # pylint: disable=protected-access
    assert [r["title"] for r in related] == ["Sunderland sweat on striker's fitness"]
