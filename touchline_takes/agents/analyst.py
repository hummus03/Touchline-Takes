"""Analyst agent: trains/loads the match-outcome model and predicts upcoming fixtures."""

from __future__ import annotations

import logging
from pathlib import Path

from touchline_takes.agents.base import Agent
from touchline_takes.db import Database
from touchline_takes.models.match_predictor import MatchPredictor
from touchline_takes.state import NewsroomState
from touchline_takes.tools.football_api import FixturesClient
from touchline_takes.tools.stats import load_results
from touchline_takes.tools.teams import TeamDirectory

LOGGER = logging.getLogger(__name__)
SUFFIXES = {"United", "City", "Town", "FC", "AFC", "Albion", "Hotspur", "Wanderers", "Rovers",
            "County", "Athletic"}


class AnalystAgent(Agent):
    """Keeps a trained model around and attaches predictions to fixtures."""

    name = "analyst"

    def __init__(self, db: Database, fixtures: FixturesClient, teams: TeamDirectory,
                 results_dir: str, model_path: str, offline: bool = False,
                 retrain: bool = False, allow_fallback: bool = True) -> None:
        super().__init__()
        self.db = db
        self.fixtures = fixtures
        self.teams = teams
        self.results_dir = results_dir
        self.model_path = model_path
        self.offline = offline
        self.retrain = retrain
        self.allow_fallback = allow_fallback
        self.model: MatchPredictor | None = None

    def ensure_model(self) -> MatchPredictor:
        """Load the persisted model or train a fresh one from the results CSVs."""
        if self.model is not None:
            return self.model
        if not self.retrain and Path(self.model_path).exists():
            try:
                self.model = MatchPredictor.load(self.model_path)
                return self.model
            except (OSError, KeyError, ValueError) as exc:
                LOGGER.warning("could not load model, retraining: %s", exc)
        model = MatchPredictor()
        model.fit_evaluate(load_results(self.results_dir))
        model.save(self.model_path)
        self.model = model
        return model

    def resolve(self, name: str) -> str | None:
        """The results-data name for a club, or ``None`` if the model doesn't know it.

        Tries the team directory first, then the name without a common suffix
        ("Leeds United" -> "Leeds", "Hull City" -> "Hull"), but only accepts a
        name the model was trained on, so it never guesses a different club.
        """
        model = self.ensure_model()
        candidates = [self.teams.data_name(name), name]
        words = name.split()
        if len(words) > 1 and words[-1] in SUFFIXES:
            stripped = " ".join(words[:-1])
            candidates += [self.teams.data_name(stripped), stripped]
        return next((c for c in candidates if model.knows(c)), None)

    def predict_fixture(self, home: str, away: str) -> dict[str, float] | None:
        """Probabilities for a fixture, or ``None`` if a team is unknown to the model."""
        home_data, away_data = self.resolve(home), self.resolve(away)
        if not (home_data and away_data):
            return None
        return self.ensure_model().predict(home_data, away_data)

    def run(self, state: NewsroomState) -> NewsroomState:
        model = self.ensure_model()
        fixtures, used_fallback = self.fixtures.upcoming(offline=self.offline,
                                                         allow_fallback=self.allow_fallback)
        if used_fallback:
            self.log(state, "fallback", "using bundled sample fixtures")
        predicted = 0
        for fixture in fixtures:
            fixture = dict(fixture)
            self.db.upsert_fixture(fixture)
            probs = self.predict_fixture(fixture["home"], fixture["away"])
            if probs is None:
                self.log(state, "skipped", f"no data for {fixture['home']} v {fixture['away']}",
                         fixture["id"])
            else:
                pick = max(probs, key=probs.get)
                self.db.upsert_prediction(fixture["id"], probs, pick, model.version)
                fixture["probs"] = probs
                predicted += 1
                self.log(state, "predicted", f"{fixture['home']} v {fixture['away']}: "
                         f"H {probs['H']:.0%} D {probs['D']:.0%} A {probs['A']:.0%}",
                         fixture["id"])
            state.fixtures.append(fixture)
        metrics = model.report.get("metrics", {})
        state.metrics["analyst"] = {
            "fixtures": len(fixtures), "predicted": predicted, "model": model.version,
            "test_accuracy": metrics.get("accuracy"), "test_roc_auc": metrics.get("roc_auc_ovr"),
        }
        return state
