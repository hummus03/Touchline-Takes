"""Upcoming fixtures from football-data.org (optional key) with a bundled fallback."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import requests

LOGGER = logging.getLogger(__name__)
API_URL = "https://api.football-data.org/v4/competitions/{code}/matches"
COMPETITIONS = {"PL": "Premier League"}


class FixturesClient:
    """Loads upcoming fixtures. Uses the API only when a key is configured."""

    def __init__(self, sample_path: str, api_key: str = "", timeout: float = 10.0,
                 session: requests.Session | None = None) -> None:
        self.sample_path = Path(sample_path)
        self.api_key = api_key
        self.timeout = timeout
        self.session = session or requests.Session()

    def from_api(self) -> list[dict[str, Any]]:
        """Fetch scheduled matches from football-data.org."""
        fixtures = []
        for code, league in COMPETITIONS.items():
            resp = self.session.get(
                API_URL.format(code=code), params={"status": "SCHEDULED"},
                headers={"X-Auth-Token": self.api_key}, timeout=self.timeout)
            resp.raise_for_status()
            for match in resp.json().get("matches", [])[:10]:
                fixtures.append({
                    "id": f"fd-{match['id']}", "date": match["utcDate"][:10], "league": league,
                    "home": match["homeTeam"].get("shortName") or match["homeTeam"]["name"],
                    "away": match["awayTeam"].get("shortName") or match["awayTeam"]["name"],
                    "source": "football-data.org"})
        return fixtures

    def load_sample(self) -> list[dict[str, Any]]:
        """Bundled sample fixtures."""
        data = json.loads(self.sample_path.read_text(encoding="utf-8"))
        return [{**f, "source": f.get("source", "sample fixtures")} for f in data]

    def upcoming(self, offline: bool = False, allow_fallback: bool = True
                 ) -> tuple[list[dict[str, Any]], bool]:
        """Return ``(fixtures, used_fallback)``; no fixtures at all if fallback is disabled."""
        if self.api_key and not offline:
            try:
                return self.from_api(), False
            except (requests.RequestException, KeyError, ValueError) as exc:
                LOGGER.warning("fixtures API failed: %s", exc)
        if not allow_fallback:
            return [], False
        return self.load_sample(), True
