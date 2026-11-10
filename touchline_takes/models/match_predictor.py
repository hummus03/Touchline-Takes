"""Match-outcome model: multinomial logistic regression on pre-match form and Elo.

Features are computed strictly from matches *before* each fixture (no leakage),
the split is chronological (train on the past, test on the future), and the
model is compared against a majority-class and a class-prior baseline.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.dummy import DummyClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (accuracy_score, confusion_matrix, f1_score, log_loss,
                             precision_score, recall_score, roc_auc_score)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

LABELS = ["H", "D", "A"]
FEATURES = ["elo_diff", "home_ppg", "away_ppg", "home_gf", "home_ga", "away_gf", "away_ga",
            "ppg_diff", "gd_diff"]
MODEL_VERSION = "logreg-v1"


@dataclass
class FormState:
    """Rolling per-team history used to build features."""

    window: int = 5
    k_factor: float = 20.0
    home_adv: float = 60.0
    elo: dict[str, float] = field(default_factory=lambda: defaultdict(lambda: 1500.0))
    history: dict[str, deque] = field(default_factory=dict)

    def _hist(self, team: str) -> deque:
        if team not in self.history:
            self.history[team] = deque(maxlen=self.window)
        return self.history[team]

    def features(self, home: str, away: str) -> dict[str, float]:
        """Pre-match features for a fixture."""
        out = {"elo_diff": self.elo[home] + self.home_adv - self.elo[away]}
        for side, team in (("home", home), ("away", away)):
            hist = self._hist(team)
            if hist:
                out[f"{side}_ppg"] = float(np.mean([h[2] for h in hist]))
                out[f"{side}_gf"] = float(np.mean([h[0] for h in hist]))
                out[f"{side}_ga"] = float(np.mean([h[1] for h in hist]))
            else:
                out[f"{side}_ppg"], out[f"{side}_gf"], out[f"{side}_ga"] = 1.35, 1.4, 1.4
        out["ppg_diff"] = out["home_ppg"] - out["away_ppg"]
        out["gd_diff"] = (out["home_gf"] - out["home_ga"]) - (out["away_gf"] - out["away_ga"])
        return out

    def played(self, team: str) -> int:
        """Matches in the rolling window."""
        return len(self._hist(team))

    def update(self, home: str, away: str, hg: int, ag: int) -> None:
        """Fold a result into Elo and rolling form."""
        expected = 1 / (1 + 10 ** ((self.elo[away] - self.elo[home] - self.home_adv) / 400))
        actual = 1.0 if hg > ag else 0.5 if hg == ag else 0.0
        margin = np.log1p(abs(hg - ag)) + 1
        delta = self.k_factor * margin * (actual - expected)
        self.elo[home] += delta
        self.elo[away] -= delta
        hp, ap = (3, 0) if hg > ag else (1, 1) if hg == ag else (0, 3)
        self._hist(home).append((hg, ag, hp))
        self._hist(away).append((ag, hg, ap))


def build_features(results: pd.DataFrame, min_history: int = 3
                   ) -> tuple[pd.DataFrame, FormState]:
    """Chronological feature table (one row per match) plus the final form state."""
    state = FormState()
    rows = []
    for match in results.sort_values("Date", kind="stable").itertuples():
        feats = state.features(match.HomeTeam, match.AwayTeam)
        if min(state.played(match.HomeTeam), state.played(match.AwayTeam)) >= min_history:
            rows.append({**feats, "Date": match.Date, "HomeTeam": match.HomeTeam,
                         "AwayTeam": match.AwayTeam, "FTR": match.FTR})
        state.update(match.HomeTeam, match.AwayTeam, int(match.FTHG), int(match.FTAG))
    return pd.DataFrame(rows), state


def _clip_normalise(proba: np.ndarray) -> np.ndarray:
    """Keep probabilities away from 0 (finite log-loss) while summing to one."""
    clipped = np.clip(proba, 1e-6, 1)
    return clipped / clipped.sum(axis=1, keepdims=True)


def _metrics(y_true, y_pred, proba) -> dict[str, Any]:
    """Classification metrics for the H/D/A problem."""
    # sklearn expects probability columns in sorted label order for AUC/log-loss.
    order = sorted(LABELS)
    sorted_proba = proba[:, [LABELS.index(label) for label in order]]
    return {
        "accuracy": round(float(accuracy_score(y_true, y_pred)), 4),
        "precision_macro": round(float(precision_score(y_true, y_pred, labels=LABELS,
                                                       average="macro", zero_division=0)), 4),
        "recall_macro": round(float(recall_score(y_true, y_pred, labels=LABELS,
                                                 average="macro", zero_division=0)), 4),
        "f1_macro": round(float(f1_score(y_true, y_pred, labels=LABELS, average="macro",
                                         zero_division=0)), 4),
        "roc_auc_ovr": round(float(roc_auc_score(y_true, sorted_proba, multi_class="ovr",
                                                 labels=order)), 4),
        "log_loss": round(float(log_loss(y_true, _clip_normalise(sorted_proba),
                                         labels=order)), 4),
        "confusion_matrix": {"labels": LABELS, "matrix": confusion_matrix(
            y_true, y_pred, labels=LABELS).tolist()},
    }


def _ordered_proba(model, x) -> np.ndarray:
    """Predicted probabilities with columns in LABELS order."""
    proba = model.predict_proba(x)
    classes = list(model.classes_)
    return np.column_stack([proba[:, classes.index(c)] if c in classes
                            else np.zeros(len(x)) for c in LABELS])


class MatchPredictor:
    """Trains, evaluates, persists and serves the match-outcome model."""

    def __init__(self, c_value: float = 0.5) -> None:
        self.pipeline = Pipeline([
            ("scale", StandardScaler()),
            ("logreg", LogisticRegression(C=c_value, max_iter=2000)),
        ])
        self.state: FormState | None = None
        self.report: dict[str, Any] = {}
        self.version = MODEL_VERSION

    def fit_evaluate(self, results: pd.DataFrame, test_size: float = 0.25) -> dict[str, Any]:
        """Chronological train/test split, fit, evaluate vs baselines, then refit on all data."""
        table, state = build_features(results)
        if len(table) < 40:
            raise ValueError("not enough matches to train the model")
        split = int(len(table) * (1 - test_size))
        train, test = table.iloc[:split], table.iloc[split:]
        x_train, y_train = train[FEATURES], train["FTR"]
        x_test, y_test = test[FEATURES], test["FTR"]
        self.pipeline.fit(x_train, y_train)
        proba = _ordered_proba(self.pipeline, x_test)
        model_metrics = _metrics(y_test, np.array(LABELS)[proba.argmax(axis=1)], proba)
        baselines = {}
        for name, strategy in (("majority_class", "most_frequent"), ("class_prior", "prior")):
            dummy = DummyClassifier(strategy=strategy).fit(x_train, y_train)
            base_proba = _ordered_proba(dummy, x_test)
            baselines[name] = _metrics(y_test, dummy.predict(x_test), base_proba)
        coefs = self.pipeline.named_steps["logreg"]
        self.report = {
            "model": self.version, "n_train": len(train), "n_test": len(test),
            "train_period": [str(train.Date.min().date()), str(train.Date.max().date())],
            "test_period": [str(test.Date.min().date()), str(test.Date.max().date())],
            "class_balance_test": {k: round(float(v), 3) for k, v in
                                   y_test.value_counts(normalize=True).items()},
            "metrics": model_metrics, "baselines": baselines,
            "coefficients": {str(cls): dict(zip(FEATURES, np.round(row, 3).tolist()))
                             for cls, row in zip(coefs.classes_, coefs.coef_)},
        }
        self.pipeline.fit(table[FEATURES], table["FTR"])  # final model uses all data
        self.state = state
        return self.report

    def predict(self, home: str, away: str) -> dict[str, float]:
        """Probabilities ``{"H", "D", "A"}`` for a fixture, using the latest form."""
        if self.state is None:
            raise RuntimeError("model is not trained")
        feats = pd.DataFrame([self.state.features(home, away)])[FEATURES]
        proba = _ordered_proba(self.pipeline, feats)[0]
        return {label: round(float(p), 4) for label, p in zip(LABELS, proba)}

    def knows(self, team: str) -> bool:
        """True if the team appears in the training data."""
        return self.state is not None and team in self.state.history

    def save(self, path: str | Path) -> None:
        """Persist with joblib."""
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"pipeline": self.pipeline, "state": _freeze(self.state),
                     "report": self.report, "version": self.version}, path)

    @classmethod
    def load(cls, path: str | Path) -> "MatchPredictor":
        """Load a persisted model."""
        data = joblib.load(path)
        model = cls()
        model.pipeline, model.report = data["pipeline"], data["report"]
        model.version, model.state = data["version"], _thaw(data["state"])
        return model


def _freeze(state: FormState | None) -> dict | None:
    if state is None:
        return None
    return {"elo": dict(state.elo), "history": {k: list(v) for k, v in state.history.items()},
            "window": state.window}


def _thaw(data: dict | None) -> FormState | None:
    if data is None:
        return None
    state = FormState(window=data["window"])
    state.elo.update(data["elo"])
    for team, hist in data["history"].items():
        state.history[team] = deque(hist, maxlen=state.window)
    return state
