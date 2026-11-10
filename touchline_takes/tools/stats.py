"""Results data (Football-Data.co.uk CSV format) and form/head-to-head lookups."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

REQUIRED = ["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR"]


def load_results(results_dir: str | Path) -> pd.DataFrame:
    """Load and concatenate every CSV in ``results_dir``, sorted by date."""
    frames = []
    for path in sorted(Path(results_dir).glob("*.csv")):
        frame = pd.read_csv(path, encoding="latin-1")
        missing = [c for c in REQUIRED if c not in frame.columns]
        if missing:
            continue
        frame = frame[REQUIRED + (["Div"] if "Div" in frame.columns else [])].dropna(
            subset=REQUIRED)
        frame["Date"] = pd.to_datetime(frame["Date"], dayfirst=True, errors="coerce")
        frames.append(frame.dropna(subset=["Date"]))
    if not frames:
        return pd.DataFrame(columns=REQUIRED)
    data = pd.concat(frames, ignore_index=True)
    data[["FTHG", "FTAG"]] = data[["FTHG", "FTAG"]].astype(int)
    return data.sort_values("Date", kind="stable").reset_index(drop=True)


class ResultsStore:
    """Answers form and head-to-head questions; outputs are citable evidence text."""

    def __init__(self, results: pd.DataFrame, label: str = "results data") -> None:
        self.results = results
        self.label = label

    def team_matches(self, data_name: str) -> pd.DataFrame:
        """All matches involving a team."""
        res = self.results
        return res[(res.HomeTeam == data_name) | (res.AwayTeam == data_name)]

    def form(self, data_name: str, n: int = 5) -> dict | None:
        """Last ``n`` results for a team, or ``None`` if the team is not in the data."""
        matches = self.team_matches(data_name).tail(n)
        if matches.empty:
            return None
        wins = draws = losses = gf = ga = 0
        letters = []
        for row in matches.itertuples():
            home = row.HomeTeam == data_name
            scored, conceded = (row.FTHG, row.FTAG) if home else (row.FTAG, row.FTHG)
            gf, ga = gf + scored, ga + conceded
            if scored > conceded:
                wins, letters = wins + 1, letters + ["W"]
            elif scored == conceded:
                draws, letters = draws + 1, letters + ["D"]
            else:
                losses, letters = losses + 1, letters + ["L"]
        return {"played": len(matches), "wins": wins, "draws": draws, "losses": losses,
                "points": 3 * wins + draws, "goals_for": gf, "goals_against": ga,
                "sequence": "".join(letters)}

    def form_text(self, display: str, data_name: str, n: int = 5) -> str | None:
        """Evidence sentence describing recent form."""
        form = self.form(data_name, n)
        if not form:
            return None
        def _n(count: int, noun: str) -> str:
            return f"{count} {noun}" if count == 1 else f"{count} {noun}s"
        return (f"{display} last {form['played']} league matches in {self.label}: "
                f"{_n(form['wins'], 'win')}, {_n(form['draws'], 'draw')}, "
                f"{_n(form['losses'], 'defeat')}, {_n(form['points'], 'point')}, "
                f"{_n(form['goals_for'], 'goal')} scored, "
                f"{form['goals_against']} conceded (sequence {form['sequence']}).")

    def last_meeting(self, home: str, away: str) -> dict | None:
        """Most recent match between two teams (either venue)."""
        res = self.results
        mask = ((res.HomeTeam == home) & (res.AwayTeam == away)) | (
            (res.HomeTeam == away) & (res.AwayTeam == home))
        matches = res[mask]
        if matches.empty:
            return None
        row = matches.iloc[-1]
        return {"date": row.Date.strftime("%Y-%m-%d"), "home": row.HomeTeam,
                "away": row.AwayTeam, "home_goals": int(row.FTHG), "away_goals": int(row.FTAG)}
