"""Tests for relation-level fact checks (result direction, attribution, units)."""
# pylint: disable=redefined-outer-name

import pytest

from touchline_takes.config import Settings
from touchline_takes.tools.relations import (MatchResult, attribution_matches, extract_results,
                                             lemma, number_units, result_conflict,
                                             team_number_pairs)
from touchline_takes.tools.teams import TeamDirectory


@pytest.fixture(scope="module")
def teams():
    """Team directory."""
    return TeamDirectory.from_file(Settings().teams_path)


@pytest.mark.parametrize("text,expected", [
    ("Arsenal beat Chelsea 2-1 in tense London derby", "Arsenal beat Chelsea 2-1"),
    ("Chelsea were beaten 2-1 by Arsenal", "Arsenal beat Chelsea 2-1"),
    ("Real Madrid stunned 2-0 by Sevilla", "Sevilla beat Real Madrid 2-0"),
    ("Real Madrid suffered a shock 2-0 defeat away at Sevilla.", "Sevilla beat Real Madrid 2-0"),
    ("Tottenham boss sacked after 3-0 defeat at Brentford", "Brentford beat Tottenham 3-0"),
    ("Manchester United lost 2-1 to Fulham", "Fulham beat Manchester United 2-1"),
    ("Celtic extend lead with 3-1 win over Rangers", "Celtic beat Rangers 3-1"),
    ("Liverpool were held to a 0-0 draw by Everton.", "Everton and Liverpool drew 0-0"),
    ("Liverpool beat Everton 0-0", "Liverpool beat Everton 0-0"),
    ("Last meeting: 2025-03-10, Newcastle 0-2 Manchester City.",
     "Manchester City beat Newcastle 2-0"),
    ("The game between Arsenal and Chelsea ended 2-1", "Arsenal and Chelsea finished 2-1"),
])
def test_extract_results(teams, text, expected):
    """Winner, score and draws are read from many phrasings (dates are not scores)."""
    assert [r.describe() for r in extract_results(text, teams)] == [expected]


def test_no_result_without_two_teams_and_score(teams):
    """A single team or no score yields nothing."""
    assert not extract_results("Arsenal won 2-1 last night.", teams)
    assert not extract_results("Arsenal and Chelsea meet on 2026-11-21.", teams)


def test_result_conflict(teams):
    """Flipped winners, wrong scores and win-vs-draw conflict; unrelated pairs don't."""
    source = extract_results("Arsenal beat Chelsea 2-1.", teams)
    flip = extract_results("Chelsea beat Arsenal 2-1.", teams)[0]
    assert "source says Arsenal beat Chelsea 2-1" in result_conflict(flip, source)
    wrong = extract_results("Arsenal beat Chelsea 3-1.", teams)[0]
    assert result_conflict(wrong, source)
    unknown = MatchResult(frozenset({"Arsenal", "Chelsea"}), (2, 1), None, False)
    assert result_conflict(unknown, source) is None
    other = extract_results("Spurs beat Fulham 2-1.", teams)[0]
    assert result_conflict(other, source) is None
    draw = extract_results("Liverpool and Everton drew 0-0.", teams)
    assert result_conflict(extract_results("Everton beat Liverpool 0-0.", teams)[0], draw)


def test_team_number_attribution(teams):
    """Numbers go to the nearest preceding team, with their unit."""
    text = "Touchline Takes Analyst model: Arsenal win 45%, draw 27%, Liverpool win 28%."
    triples = team_number_pairs(text, teams)
    assert ("45", "%", "Arsenal") in triples and ("28", "%", "Liverpool") in triples
    assert attribution_matches(("45", "", "Arsenal"), triples)
    assert not attribution_matches(("45", "%", "Liverpool"), triples)


def test_number_units_and_lemma():
    """Number-unit pairs, including ordinals, hyphenated ages and percentages."""
    units = number_units("out for 6 weeks, the 78th minute, a 23-year-old, a 45% chance")
    assert {("6", "week"), ("78", "minute"), ("23", "year"), ("45", "%")} <= units
    assert lemma("matches") == "match" and lemma("goals") == "goal" and lemma("loss") == "loss"
