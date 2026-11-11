"""Tests for the match-outcome model and the Analyst agent."""
# pylint: disable=redefined-outer-name

import numpy as np
import pandas as pd
import pytest

from touchline_takes.agents.analyst import AnalystAgent
from touchline_takes.config import Settings
from touchline_takes.models.match_predictor import LABELS, MatchPredictor, build_features
from touchline_takes.state import NewsroomState
from touchline_takes.tools.football_api import FixturesClient
from touchline_takes.tools.stats import ResultsStore, load_results
from touchline_takes.tools.teams import TeamDirectory

from tests.conftest import FakeResponse, FakeSession


@pytest.fixture(scope="module")
def results():
    """Bundled sample results."""
    return load_results(Settings().results_dir)


def test_features_use_only_past_matches():
    """The first match of a team has default (prior) features: no leakage."""
    frame = pd.DataFrame({
        "Date": pd.to_datetime(["2024-01-01", "2024-01-08"]), "HomeTeam": ["A", "A"],
        "AwayTeam": ["B", "B"], "FTHG": [5, 0], "FTAG": [0, 0], "FTR": ["H", "D"]})
    table, state = build_features(frame, min_history=0)
    assert table.iloc[0]["elo_diff"] == pytest.approx(60.0)  # only home advantage
    assert table.iloc[1]["home_gf"] == 5.0  # second match sees the first only
    assert state.elo["A"] > state.elo["B"]


def test_model_beats_baselines(results):
    """Chronological evaluation reports all metrics and beats the baselines."""
    model = MatchPredictor()
    report = model.fit_evaluate(results)
    metrics, base = report["metrics"], report["baselines"]["majority_class"]
    for key in ("accuracy", "precision_macro", "recall_macro", "f1_macro", "roc_auc_ovr"):
        assert 0 <= metrics[key] <= 1
    assert np.array(metrics["confusion_matrix"]["matrix"]).sum() == report["n_test"]
    assert report["train_period"][1] <= report["test_period"][0]
    assert metrics["accuracy"] > base["accuracy"]
    assert metrics["roc_auc_ovr"] > 0.55 > base["roc_auc_ovr"] - 0.1
    probs = model.predict("Man City", "Southampton")
    assert set(probs) == set(LABELS) and abs(sum(probs.values()) - 1) < 1e-3
    assert probs["H"] > probs["A"]


def test_save_and_load(tmp_path, results):
    """A saved model predicts identically after loading."""
    model = MatchPredictor()
    model.fit_evaluate(results)
    model.save(tmp_path / "m.joblib")
    loaded = MatchPredictor.load(tmp_path / "m.joblib")
    assert loaded.predict("Arsenal", "Chelsea") == model.predict("Arsenal", "Chelsea")
    assert loaded.report["metrics"] == model.report["metrics"]


def test_results_store_form(results):
    """Form summaries are consistent."""
    form = ResultsStore(results).form("Arsenal", 5)
    assert form["played"] == 5 and form["points"] == 3 * form["wins"] + form["draws"]
    assert len(form["sequence"]) == 5


def test_analyst_agent_predicts_fixtures(settings, db):
    """Fixtures are stored with predictions; unknown teams are skipped."""
    client = FixturesClient(settings.fixtures_path)
    teams = TeamDirectory.from_file(settings.teams_path)
    agent = AnalystAgent(db, client, teams, settings.results_dir, settings.model_path,
                         offline=True)
    state = agent.run(NewsroomState())
    assert state.metrics["analyst"]["predicted"] == len(state.fixtures) > 0
    rows = db.fixtures_with_predictions()
    assert rows[0]["home_win"] is not None
    assert agent.predict_fixture("Real Madrid", "Arsenal") is None


def test_fixtures_api_with_key_and_fallback(settings):
    """The API is used when a key is set; errors fall back to samples."""
    payload = {"matches": [{"id": 7, "utcDate": "2026-11-21T15:00:00Z",
                            "homeTeam": {"name": "Arsenal FC", "shortName": "Arsenal"},
                            "awayTeam": {"name": "Chelsea FC", "shortName": "Chelsea"}}]}
    client = FixturesClient(settings.fixtures_path, api_key="k", session=FakeSession(
        {"competitions/PL": FakeResponse(json_data=payload)}))
    fixtures, fallback = client.upcoming()
    assert not fallback and fixtures[0]["home"] == "Arsenal" and fixtures[0]["id"] == "fd-7"
    broken = FixturesClient(settings.fixtures_path, api_key="k",
                            session=FakeSession({"x": FakeResponse()}))
    fixtures, fallback = broken.upcoming()
    assert fallback and len(fixtures) == 6


def test_fixture_team_names_are_resolved(settings, db):
    """API names like 'Leeds United' or 'Nottingham' reach the model's 'Leeds'/'Nott'm Forest'."""
    from touchline_takes.tools.football_api import _team_name  # pylint: disable=import-outside-toplevel
    assert _team_name({"shortName": "Nottingham", "name": "Nottingham Forest FC"}) == (
        "Nottingham Forest")
    assert _team_name({"shortName": "Brighton Hove", "name": "x"}) == "Brighton"
    agent = AnalystAgent(db, FixturesClient(settings.fixtures_path),
                         TeamDirectory.from_file(settings.teams_path), settings.results_dir,
                         settings.model_path, offline=True)
    assert agent.resolve("Nottingham Forest") == "Nott'm Forest"
    assert agent.resolve("Leicester City") == "Leicester"   # suffix fallback
    assert agent.resolve("Ipswich Town") == "Ipswich"
    assert agent.resolve("Manchester City") == "Man City"   # directory, not 'Manchester'
    assert agent.resolve("Notts County") is None            # unknown club: no guess
    assert agent.predict_fixture("Leicester City", "Nottingham Forest") is not None
