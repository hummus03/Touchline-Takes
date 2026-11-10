"""Generate the bundled *synthetic* results data and sample fixtures.

The real Football-Data.co.uk CSVs cannot be downloaded in every sandbox, so the
repo ships a small synthetic dataset in exactly the same column format
(Div, Date, HomeTeam, AwayTeam, FTHG, FTAG, FTR). Goals are drawn from Poisson
distributions driven by per-team attack/defence strengths plus home advantage,
so the data has realistic structure for the match-outcome model to learn.

Replace it with real data via ``python scripts/download_football_data.py``.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
TEAMS = {  # data name: (attack, defence) baseline strengths
    "Man City": (0.45, 0.40), "Arsenal": (0.40, 0.42), "Liverpool": (0.42, 0.35),
    "Chelsea": (0.20, 0.15), "Newcastle": (0.18, 0.18), "Aston Villa": (0.15, 0.08),
    "Tottenham": (0.18, 0.00), "Man United": (0.08, 0.05), "Brighton": (0.10, 0.02),
    "West Ham": (0.02, -0.05), "Crystal Palace": (-0.02, 0.02), "Brentford": (0.02, -0.08),
    "Fulham": (-0.02, -0.02), "Bournemouth": (0.00, -0.08), "Wolves": (-0.08, -0.08),
    "Everton": (-0.15, 0.02), "Nott'm Forest": (-0.08, -0.05), "Leicester": (-0.15, -0.20),
    "Ipswich": (-0.20, -0.22), "Southampton": (-0.28, -0.25),
}
SEASONS = {"2223": date(2022, 8, 6), "2324": date(2023, 8, 12), "2425": date(2024, 8, 17)}
BASE_GOALS = 0.28
HOME_ADVANTAGE = 0.22


def round_robin(teams: list[str], rng: np.random.Generator) -> list[list[tuple[str, str]]]:
    """Double round-robin schedule (circle method), returned as a list of matchdays."""
    teams = list(teams)
    rng.shuffle(teams)
    n = len(teams)
    rounds = []
    for r in range(n - 1):
        pairs = []
        for i in range(n // 2):
            home, away = teams[i], teams[n - 1 - i]
            pairs.append((home, away) if r % 2 == 0 else (away, home))
        rounds.append(pairs)
        teams = [teams[0]] + [teams[-1]] + teams[1:-1]
    return rounds + [[(a, h) for h, a in rnd] for rnd in rounds]


def simulate_season(code: str, start: date, rng: np.random.Generator) -> pd.DataFrame:
    """Simulate one Premier League season."""
    drift = {t: rng.normal(0, 0.06, size=2) for t in TEAMS}
    rows = []
    for day_index, matchday in enumerate(round_robin(list(TEAMS), rng)):
        match_date = start + timedelta(days=7 * day_index + (day_index // 10))
        for home, away in matchday:
            att_h, def_h = np.add(TEAMS[home], drift[home])
            att_a, def_a = np.add(TEAMS[away], drift[away])
            lam_h = np.exp(BASE_GOALS + att_h - def_a + HOME_ADVANTAGE)
            lam_a = np.exp(BASE_GOALS + att_a - def_h)
            fthg, ftag = int(rng.poisson(lam_h)), int(rng.poisson(lam_a))
            ftr = "H" if fthg > ftag else "A" if ftag > fthg else "D"
            rows.append({"Div": "E0", "Date": match_date.strftime("%d/%m/%Y"),
                         "HomeTeam": home, "AwayTeam": away, "FTHG": fthg, "FTAG": ftag,
                         "FTR": ftr, "Season": code})
    return pd.DataFrame(rows)


def main() -> None:
    """Write results CSVs and sample fixtures."""
    rng = np.random.default_rng(20260801)
    out_dir = ROOT / "data" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    for code, start in SEASONS.items():
        frame = simulate_season(code, start, rng)
        frame.drop(columns=["Season"]).to_csv(out_dir / f"sample_E0_{code}.csv", index=False)
        print(f"wrote {len(frame)} synthetic matches for {code}")
    fixtures = [
        ("2026-11-21", "Arsenal", "Liverpool"), ("2026-11-21", "Manchester City", "Newcastle"),
        ("2026-11-22", "Manchester United", "Fulham"), ("2026-11-22", "Chelsea", "Tottenham"),
        ("2026-11-22", "Everton", "Brighton"), ("2026-11-23", "Aston Villa", "West Ham"),
    ]
    data = [{"id": f"sample-{i + 1}", "date": d, "league": "Premier League", "home": h,
             "away": a, "source": "sample fixtures"} for i, (d, h, a) in enumerate(fixtures)]
    fixtures_path = ROOT / "data" / "fixtures" / "sample_fixtures.json"
    fixtures_path.parent.mkdir(parents=True, exist_ok=True)
    fixtures_path.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {len(data)} sample fixtures")


if __name__ == "__main__":
    main()
