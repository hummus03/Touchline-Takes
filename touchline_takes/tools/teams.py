"""Team directory: aliases, leagues and results-data names."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path


class TeamDirectory:
    """Resolves team mentions in text and maps between display and data names."""

    def __init__(self, teams: dict[str, dict]) -> None:
        self.teams = teams
        self._alias_to_team: dict[str, str] = {}
        for display, info in teams.items():
            for alias in [display, info.get("data_name", display), *info.get("aliases", [])]:
                self._alias_to_team[alias.lower()] = display
        aliases = sorted(self._alias_to_team, key=len, reverse=True)
        self._pattern = re.compile(
            r"(?<![\w'])(" + "|".join(re.escape(a) for a in aliases) + r")(?![\w])",
            re.IGNORECASE)

    @classmethod
    def from_file(cls, path: str | Path) -> "TeamDirectory":
        """Load ``teams.json``."""
        return _load(str(path))

    def find_teams(self, text: str) -> list[str]:
        """Display names of teams mentioned in ``text``, in order of first mention."""
        found: list[str] = []
        for match in self._pattern.finditer(text or ""):
            team = self._alias_to_team[match.group(1).lower()]
            if team not in found:
                found.append(team)
        return found

    def find_team_spans(self, text: str) -> list[tuple[str, int, int]]:
        """Every team mention as ``(display name, start, end)`` in order of appearance."""
        return [(self._alias_to_team[m.group(1).lower()], m.start(), m.end())
                for m in self._pattern.finditer(text or "")]

    def canonical(self, name: str) -> str:
        """Display name for any alias (or the input if unknown)."""
        return self._alias_to_team.get((name or "").lower(), name)

    def league_of(self, team: str) -> str | None:
        """League of a team."""
        info = self.teams.get(self.canonical(team))
        return info["league"] if info else None

    def data_name(self, team: str) -> str:
        """Name used in Football-Data CSVs."""
        info = self.teams.get(self.canonical(team))
        return info.get("data_name", team) if info else team

    def aliases(self, team: str) -> list[str]:
        """All known names for a team."""
        info = self.teams.get(self.canonical(team), {})
        return [team, info.get("data_name", team), *info.get("aliases", [])]


@lru_cache(maxsize=8)
def _load(path: str) -> TeamDirectory:
    return TeamDirectory(json.loads(Path(path).read_text(encoding="utf-8")))
