"""Tests for the Classifier agent and its back-ends."""
# pylint: disable=redefined-outer-name

import pytest

from touchline_takes.agents.classifier import (ClassifierAgent, LexiconClassifier,
                                               LLMClassifier)
from touchline_takes.config import Settings
from touchline_takes.state import NewsroomState
from touchline_takes.tools.llm import FakeLLM, RecordedLLM
from touchline_takes.tools.teams import TeamDirectory

from tests.conftest import FIXTURES, make_story


@pytest.fixture
def lexicon():
    """Offline classifier."""
    return LexiconClassifier(TeamDirectory.from_file(Settings().teams_path))


@pytest.mark.parametrize("title,summary,league,topic", [
    ("Arsenal beat Chelsea 2-1", "Arsenal won the derby.", "Premier League", "match_report"),
    ("Tottenham boss sacked", "The head coach was dismissed after a defeat.",
     "Premier League", "manager"),
    ("Newcastle in talks to sign Dortmund winger", "A fee is being discussed.",
     "Premier League", "transfer"),
    ("Captain ruled out with hamstring injury", "Aston Villa will miss him.",
     "Premier League", "injury"),
    ("VAR controversy at Brighton", "A late penalty was denied.", "Premier League",
     "discipline"),
    ("Celtic face Bayern in Champions League", "A big night ahead.", "Champions League",
     "general"),
])
def test_lexicon_topics_and_leagues(lexicon, title, summary, league, topic):
    """League and topic tagging on representative headlines."""
    result = lexicon.classify(make_story(title=title, summary=summary))
    assert result.league == league
    assert result.topic == topic


def test_lexicon_sentiment_and_emotion(lexicon):
    """Negative/angry and positive/joyful stories are told apart; negation flips."""
    angry = lexicon.classify(make_story(title="Fans furious at disgrace",
                                        summary="A row erupted after the defeat."))
    assert (angry.sentiment, angry.emotion) == ("negative", "anger")
    happy = lexicon.classify(make_story(title="Superb victory", summary="Fans celebrate."))
    assert (happy.sentiment, happy.emotion) == ("positive", "joy")
    assert lexicon.sentiment("They did not win")[0] == "negative"


def test_llm_classifier_uses_recorded_reply(lexicon):
    """A recorded hosted reply is validated and team aliases are canonicalised."""
    clf = LLMClassifier(RecordedLLM(FIXTURES / "recorded_llm.json"), lexicon)
    result = clf.classify(make_story(title="United v Fulham", summary="Preview."))
    assert result.teams == ["Manchester United", "Fulham"]
    assert (result.topic, result.emotion) == ("preview", "fear")


def test_llm_classifier_falls_back_on_bad_output(lexicon):
    """Invalid JSON or invalid labels fall back to the lexicon."""
    clf = LLMClassifier(FakeLLM(["not json at all"]), lexicon)
    result = clf.classify(make_story())
    assert result.topic == "match_report" and clf.failures == 1
    clf = LLMClassifier(FakeLLM(['{"topic": "astrology", "teams": []}']), lexicon)
    assert clf.classify(make_story()).topic == "match_report"


def test_classifier_agent_persists(db, lexicon):
    """The agent tags new stories and writes tags to the database."""
    story = make_story()
    db.insert_story(story)
    state = ClassifierAgent(db, lexicon).run(NewsroomState(new_stories=[story]))
    assert state.metrics["classifier"]["classified"] == 1
    stored = db.get_story(story.id)
    assert stored.teams == ["Arsenal", "Chelsea"] and stored.topic == "match_report"
    assert db.unclassified_stories() == []


@pytest.mark.parametrize("title,summary,topic", [
    ("Star reveals heart treatment at World Cup",
     "He had treatment two days before the World Cup win over Haiti.", "injury"),
    ("Arsenal had a long shortlist to build on title win",
     "Our correspondent looks at Arsenal's plan to strengthen the squad.", "transfer"),
    ("The part-timers who won three Wembley finals in a row",
     "Manchester City won four League Cups in a row, but another side did it first.",
     "general"),
    ("Players air views in World Cup review",
     "Players discussed their semi-final defeat in a team meeting.", "general"),
    ("Vote for the Footballer of the Year", "Five players are on the shortlist.", "general"),
    ("Coaches linked with Aberdeen job", "Early names in the frame for the job.", "manager"),
    ("Man City thrash Inter in Europe", "City came from behind to beat Inter Milan.",
     "match_report"),
    ("Chelsea play out goalless draw", "Chelsea stay unbeaten.", "match_report"),
])
def test_match_reports_need_a_score_or_result_headline(lexicon, title, summary, topic):
    """'title win', 'World Cup winner' or 'semi-final defeat' alone are not match reports."""
    assert lexicon.classify(make_story(title=title, summary=summary)).topic == topic


def test_ambiguous_nicknames_are_not_teams(lexicon):
    """'The Magpies' can be Notts County: nicknames don't identify a club."""
    story = make_story(title="Fog at the FA Cup tie",
                       summary="Fans could not see the Magpies' FA Cup win over Altrincham.")
    assert lexicon.classify(story).teams == []
    assert lexicon.classify(make_story(title="Man City thrash Wolves",
                                       summary="A big win.")).teams == ["Manchester City",
                                                                       "Wolves"]
