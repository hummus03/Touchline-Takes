"""Static-site mode commands, used by the GitHub Actions workflows.

    python -m touchline_takes.static run        # run the newsroom once (no pause for review)
    python -m touchline_takes.static export     # open review PRs (or publish with AUTO_PUBLISH)
    python -m touchline_takes.static build      # render the site into _site/
    python -m touchline_takes.static validate   # check content/articles/*.json
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

from touchline_takes.config import Settings
from touchline_takes.content import ContentError, load_articles
from touchline_takes.db import Database
from touchline_takes.github_review import GitOps, export_pending
from touchline_takes.preflight import PreflightError, require_ready

CONTENT_DIR = "content/articles"


def _settings() -> Settings:
    return Settings.from_env().with_overrides(site_mode="static")


def _output(**values) -> None:
    """Expose values to later workflow steps (``$GITHUB_OUTPUT``), if running in Actions."""
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            for key, value in values.items():
                handle.write(f"{key}={value}\n")


def cmd_run(_args) -> int:
    """Run the newsroom once."""
    from touchline_takes.pipeline import Newsroom  # pylint: disable=import-outside-toplevel
    settings = _settings()
    room = Newsroom.build(settings, retrain=True)
    try:
        report = require_ready(settings, room.db)
    except PreflightError as exc:
        print(exc, file=sys.stderr)
        return 2
    for warning in report.warnings:
        print(f"preflight warning: {warning}")
    state = room.run_once()
    room.db.prune(30)
    room.db.close()
    for entry in state.logs:
        print(f"{entry.agent:>12} | {entry.action:<13} {entry.detail[:160]}")
    print(json.dumps(state.metrics, indent=2, default=str))
    return 0


def cmd_export(args) -> int:
    """Send approved drafts to GitHub."""
    settings = _settings()
    db = Database(settings.database_path)
    result = export_pending(db, GitOps(repo_dir=args.repo, base=args.base), args.content_dir,
                            auto_publish=settings.auto_publish)
    db.close()
    for url in result.opened:
        print(f"review PR: {url}")
    for slug in result.published:
        print(f"published: {slug}")
    for draft_id in result.duplicates:
        print(f"already published or in review: {draft_id}")
    for draft_id in result.skipped:
        print(f"skipped (failed validation): {draft_id}")
    for error in result.errors:
        print(f"ERROR {error}", file=sys.stderr)
    _output(opened=len(result.opened), published=len(result.published))
    return 1 if result.errors else 0


def cmd_build(args) -> int:
    """Render the static site."""
    from touchline_takes.static_site import build_site  # pylint: disable=import-outside-toplevel
    try:
        report = build_site(args.content_dir, args.out, _settings(), args.state_db)
    except ContentError as exc:
        print(f"Refusing to build the site:\n{exc}", file=sys.stderr)
        return 1
    print(f"Built {len(report.pages)} pages ({report.articles} articles, "
          f"{report.fixtures} fixtures) into {args.out}")
    return 0


def cmd_validate(args) -> int:
    """Validate article files."""
    _, errors = load_articles(args.content_dir)
    for name, problems in errors.items():
        for problem in problems:
            print(f"{name}: {problem}")
    print("All article files are valid." if not errors else f"{len(errors)} invalid file(s).")
    return 1 if errors else 0


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(description="Touchline Takes static-site commands.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run", help="run the newsroom once")
    export = sub.add_parser("export", help="open review PRs / publish approved drafts")
    export.add_argument("--repo", default=".")
    export.add_argument("--base", default="main")
    export.add_argument("--content-dir", default=CONTENT_DIR)
    build = sub.add_parser("build", help="render the site")
    build.add_argument("--out", default="_site")
    build.add_argument("--content-dir", default=CONTENT_DIR)
    build.add_argument("--state-db", default=None, help="newsroom DB with fixtures")
    validate = sub.add_parser("validate", help="validate article files")
    validate.add_argument("--content-dir", default=CONTENT_DIR)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    handlers = {"run": cmd_run, "export": cmd_export, "build": cmd_build,
                "validate": cmd_validate}
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
