"""Post newly published articles to X, once each.

Run after the site deploys (see .github/workflows/deploy-site.yml):

    python scripts/post_to_x.py --state .social/x_posted.json

Reads the account's keys from X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN and
X_ACCESS_SECRET; without all four it does nothing. The state file records every
article already posted (or present when posting was switched on, so the back
catalogue isn't posted all at once). A failed post is logged and retried next time;
it never fails the deploy.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# pylint: disable=wrong-import-position
from touchline_takes.tools.x_poster import XClient, XCredentials, XError, compose_post

LOGGER = logging.getLogger("post_to_x")


def load_articles(content_dir: Path) -> list[dict]:
    """Published articles, oldest first."""
    articles = [json.loads(p.read_text(encoding="utf-8"))
                for p in sorted(content_dir.glob("*.json"))]
    return sorted(articles, key=lambda a: a.get("published_at", ""))


def recent(article: dict, now: datetime, max_age: timedelta) -> bool:
    """Only fresh articles are posted; an old one merged late stays off the timeline."""
    try:
        published = datetime.fromisoformat(article["published_at"])
    except (KeyError, ValueError):
        return False
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    return now - published <= max_age


def run(content_dir: Path, state_path: Path, site_url: str, client: XClient | None,  # pylint: disable=too-many-arguments
        max_posts: int = 5, max_age_hours: int = 48, dry_run: bool = False,
        now: datetime | None = None) -> dict[str, str]:
    """Post what's new; returns {slug: post id} for this run. Updates the state file."""
    now = now or datetime.now(timezone.utc)
    articles = load_articles(content_dir)
    if not state_path.exists():
        # First run: everything already on the site counts as posted.
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps({a["slug"]: "already published" for a in articles},
                                         indent=2) + "\n", encoding="utf-8")
        LOGGER.info("posting switched on: %d existing articles marked as posted", len(articles))
        return {}
    posted: dict[str, str] = json.loads(state_path.read_text(encoding="utf-8"))
    done: dict[str, str] = {}
    for article in articles:
        if len(done) >= max_posts:
            LOGGER.info("reached %d posts this run; the rest go next time", max_posts)
            break
        slug = article["slug"]
        if slug in posted:
            continue
        if not recent(article, now, timedelta(hours=max_age_hours)):
            posted[slug] = "skipped: older than the posting window"
            continue
        text = compose_post(article, site_url)
        if dry_run or client is None:
            LOGGER.info("would post:\n%s", text)
            continue
        try:
            post_id = client.post(text)
        except XError as exc:
            LOGGER.warning("not posted (will retry next deploy): %s: %s", slug, exc)
            continue
        posted[slug] = done[slug] = post_id
        LOGGER.info("posted %s as %s", slug, post_id)
    state_path.write_text(json.dumps(posted, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return done


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--content", default="content/articles")
    parser.add_argument("--state", default=".social/x_posted.json")
    parser.add_argument("--site-url", default=os.environ.get("SITE_URL",
                                                             "https://touchlinetakes.com"))
    parser.add_argument("--max-posts", type=int, default=5)
    parser.add_argument("--dry-run", action="store_true", help="print posts, send nothing")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    creds = XCredentials(*(os.environ.get(k, "").strip() for k in (
        "X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET")))
    if not creds.complete and not args.dry_run:
        LOGGER.info("X keys not set: posting to X is off")
        return 0
    client = XClient(creds) if creds.complete else None
    run(Path(args.content), Path(args.state), args.site_url, client, args.max_posts,
        dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
