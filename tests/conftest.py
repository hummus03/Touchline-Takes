"""Shared fixtures. The whole suite runs offline: real HTTP is blocked."""
# pylint: disable=redefined-outer-name

from __future__ import annotations

from pathlib import Path

import pytest
import requests

from touchline_takes.config import DATA_DIR, Settings
from touchline_takes.db import Database
from touchline_takes.state import Story

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Fail loudly if any test tries to use the real network."""
    def _blocked(*_args, **_kwargs):
        raise requests.ConnectionError("network disabled in tests")
    monkeypatch.setattr(requests.sessions.Session, "request", _blocked)


@pytest.fixture
def settings(tmp_path) -> Settings:
    """Offline settings pointing at a temporary database."""
    return Settings(
        database_path=str(tmp_path / "test.db"), offline=True, vector_store="memory",
        chroma_dir=str(tmp_path / "chroma"), model_path=str(tmp_path / "model.joblib"),
        checkpoint_path=str(tmp_path / "checkpoints.db"),
        llm_provider="offline", secret_key="test", admin_password="secret",
        sample_feed_dir=str(DATA_DIR / "sample_feeds"))


@pytest.fixture
def db(settings) -> Database:
    """A fresh database."""
    database = Database(settings.database_path)
    yield database
    database.close()


class FakeResponse:
    """Minimal stand-in for ``requests.Response``."""

    def __init__(self, text: str = "", status: int = 200, json_data=None):
        self.text = text
        self.status_code = status
        self._json = json_data

    def raise_for_status(self):
        """Raise like requests does for HTTP errors."""
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        """Return the canned JSON body."""
        return self._json


class FakeSession:
    """Records requests and returns canned responses keyed by URL substring."""

    def __init__(self, routes: dict[str, FakeResponse | Exception]):
        self.routes = routes
        self.calls: list[tuple[str, str]] = []

    def _dispatch(self, method, url):
        self.calls.append((method, url))
        for key, resp in self.routes.items():
            if key in url:
                if isinstance(resp, Exception):
                    raise resp
                return resp
        raise requests.ConnectionError(f"no route for {url}")

    def get(self, url, **_kwargs):
        """Fake GET."""
        return self._dispatch("GET", url)

    def post(self, url, **_kwargs):
        """Fake POST."""
        return self._dispatch("POST", url)


def make_story(idx: int = 1, title: str = "Arsenal beat Chelsea 2-1 at the Emirates",
               summary: str = "Arsenal beat Chelsea 2-1 on Saturday. Leo Hartmann scored the "
               "winner in the 78th minute.", **kwargs) -> Story:
    """Build a story for tests."""
    return Story(id=f"s{idx}", title=title, summary=summary,
                 url=f"https://example.com/{idx}", source=kwargs.pop("source", "Test Wire"),
                 published="2026-11-08T17:00:00+00:00", **kwargs)
