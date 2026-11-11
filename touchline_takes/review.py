"""Human review from the command line: ``python -m touchline_takes.review``.

    python -m touchline_takes.review list
    python -m touchline_takes.review approve <draft id>
    python -m touchline_takes.review reject <draft id> --reason "not our style"

Approving or rejecting resumes the run's paused LangGraph thread, exactly like the
admin page does.
"""

from __future__ import annotations

import argparse
import sys

from touchline_takes.config import Settings
from touchline_takes.pipeline import Newsroom
from touchline_takes.tools.text import word_count


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(description="Review drafts awaiting approval.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="show drafts awaiting approval")
    for name in ("approve", "reject"):
        cmd = sub.add_parser(name, help=f"{name} a draft")
        cmd.add_argument("draft_id")
        cmd.add_argument("--reason", default="")
    args = parser.parse_args(argv)
    room = Newsroom.build(Settings.from_env())
    if args.command == "list":
        pending = room.db.drafts_by_status("pending_review")
        if not pending:
            print("Nothing awaiting approval.")
        for draft in pending:
            print(f"{draft.id}  run {room.db.draft_run_id(draft.id)}  {draft.article_type:<12} "
                  f"{word_count(draft.body):>3} words  {draft.title}")
        return 0
    draft = room.review(args.draft_id, args.command, args.reason)
    if draft is None:
        print(f"No pending draft with id {args.draft_id}.", file=sys.stderr)
        return 1
    print(f"{draft.id}: {draft.status}  {draft.title}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
