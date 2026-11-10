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
