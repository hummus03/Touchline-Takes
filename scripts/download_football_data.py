"""Download real Football-Data.co.uk results CSVs into ``RESULTS_DIR``.

Usage::

    python scripts/download_football_data.py --league E0 --seasons 2223 2324 2425 [--replace]

Files go to ``RESULTS_DIR`` (default ``data/results``; in the Docker image
``/data/results`` on the persistent volume). ``--replace`` removes any synthetic
``sample_*.csv`` files there so the model trains only on real data.
Then retrain: ``python -m touchline_takes.run --retrain``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from touchline_takes.config import Settings  # pylint: disable=wrong-import-position
URL = "https://www.football-data.co.uk/mmz4281/{season}/{league}.csv"


def main(argv: list[str] | None = None) -> int:
    """Fetch the requested seasons; returns a process exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--league", default="E0", help="E0 = Premier League, SP1, I1, D1, F1")
    parser.add_argument("--seasons", nargs="+", default=["2223", "2324", "2425"])
    parser.add_argument("--replace", action="store_true", help="delete bundled samples")
    args = parser.parse_args(argv)
    out_dir = Path(Settings.from_env().results_dir)  # RESULTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    ok = 0
    for season in args.seasons:
        url = URL.format(season=season, league=args.league)
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as exc:
            print(f"FAILED {url}: {exc}", file=sys.stderr)
            continue
        target = out_dir / f"{args.league}_{season}.csv"
        target.write_bytes(resp.content)
        ok += 1
        print(f"saved {target}")
    if ok and args.replace:
        for sample in out_dir.glob("sample_*.csv"):
            sample.unlink()
            print(f"removed synthetic {sample.name}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
