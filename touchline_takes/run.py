"""Command-line entry point: ``python -m touchline_takes.run``.

Runs the whole newsroom once, or on an interval with ``--schedule MINUTES``.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time

from touchline_takes import BRAND_NAME
from touchline_takes.config import Settings
from touchline_takes.pipeline import Newsroom
from touchline_takes.state import NewsroomState


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """CLI arguments."""
    parser = argparse.ArgumentParser(description=f"Run the {BRAND_NAME} newsroom pipeline.")
    parser.add_argument("--offline", action="store_true",
                        help="skip network fetches and use bundled sample data")
    parser.add_argument("--auto-publish", action="store_true",
                        help="publish approved drafts without human review")
    parser.add_argument("--schedule", type=float, metavar="MINUTES",
                        help="run repeatedly every MINUTES")
    parser.add_argument("--max-runs", type=int, default=0,
                        help="stop after N scheduled runs (0 = forever)")
    parser.add_argument("--retrain", action="store_true", help="retrain the Analyst model")
    parser.add_argument("--quiet", action="store_true", help="only print the run summary")
    return parser.parse_args(argv)


def print_summary(state: NewsroomState, quiet: bool = False) -> None:
    """Human-readable report of what each agent did."""
    if not quiet:
        print(f"\n=== {BRAND_NAME} run {state.run_id}: agent log ===")
        for entry in state.logs:
            target = f" [{entry.story_id}]" if entry.story_id else ""
            print(f"{entry.agent:>10} | {entry.action:<13}{target} {entry.detail}")
    print(f"\n=== Summary ===\n{json.dumps(state.metrics, indent=2, default=str)}")


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    args = parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    settings = Settings.from_env()
    overrides = {}
    if args.offline:
        overrides["offline"] = True
    if args.auto_publish:
        overrides["auto_publish"] = True
    settings = settings.with_overrides(**overrides)
    newsroom = Newsroom.build(settings, retrain=args.retrain)
    runs = 0
    while True:
        state = newsroom.run_once()
        print_summary(state, args.quiet)
        runs += 1
        if not args.schedule or (args.max_runs and runs >= args.max_runs):
            break
        print(f"\nNext run in {args.schedule:g} minute(s). Ctrl+C to stop.")
        try:
            time.sleep(args.schedule * 60)
        except KeyboardInterrupt:
            break
    return 0


if __name__ == "__main__":
    sys.exit(main())
