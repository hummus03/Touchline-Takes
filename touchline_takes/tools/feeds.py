"""RSS fetching/normalisation with a bundled offline fallback."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import requests

from touchline_takes.state import Story, story_id_for
from touchline_takes.tools.text import strip_html

LOGGER = logging.getLogger(__name__)
USER_AGENT = "TouchlineTakesBot/0.1 (+https://touchlinetakes.com)"


class FeedError(RuntimeError):
    """Raised when a feed cannot be fetched or parsed."""


@dataclass
class FeedResult:
    """Outcome of fetching all configured feeds."""

    stories: list[Story] = field(default_factory=list)
    used_fallback: bool = False
    errors: list[str] = field(default_factory=list)


def _published_iso(entry) -> str:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        return datetime.fromtimestamp(time.mktime(parsed), tz=timezone.utc).replace(
            microsecond=0).isoformat()
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _image_url(entry) -> str:
    """Photo attached to a feed item (media:thumbnail, media:content or an image enclosure)."""
    for key in ("media_thumbnail", "media_content"):
        for item in entry.get(key) or []:
            if item.get("url") and item.get("medium", "image") == "image":
                return item["url"]
    for link in entry.get("links") or []:
        if link.get("rel") == "enclosure" and str(link.get("type", "")).startswith("image/"):
            return link.get("href", "")
    return ""


def parse_feed(xml_text: str, default_source: str = "") -> list[Story]:
    """Parse RSS/Atom XML into normalised :class:`Story` objects."""
    parsed = feedparser.parse(xml_text)
    if parsed.bozo and not parsed.entries:
        raise FeedError(f"could not parse feed: {parsed.get('bozo_exception')}")
    source = default_source or strip_html(parsed.feed.get("title", "")) or "Unknown source"
    stories = []
    for entry in parsed.entries:
        title = strip_html(entry.get("title", ""))
        url = entry.get("link", "").strip()
        summary = strip_html(entry.get("summary", "") or entry.get("description", ""))
        if not title or not url:
            continue
        stories.append(Story(
            id=story_id_for(url, title), title=title, summary=summary or title, url=url,
            source=source, published=_published_iso(entry), image_url=_image_url(entry)))
    return stories


class FeedClient:
    """Fetches feeds over HTTP; falls back to bundled samples when the network fails."""

    def __init__(self, sample_dir: str, timeout: float = 10.0,
                 session: requests.Session | None = None) -> None:
        self.sample_dir = Path(sample_dir)
        self.timeout = timeout
        self.session = session or requests.Session()

    def fetch(self, url: str) -> list[Story]:
        """Fetch and parse one feed URL."""
        try:
            resp = self.session.get(url, timeout=self.timeout,
                                    headers={"User-Agent": USER_AGENT})
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise FeedError(f"{url}: {exc}") from exc
        return parse_feed(resp.text)

    def load_samples(self) -> list[Story]:
        """Parse every bundled sample feed (``*.xml``)."""
        stories: list[Story] = []
        for path in sorted(self.sample_dir.glob("*.xml")):
            stories.extend(parse_feed(path.read_text(encoding="utf-8")))
        return stories

    def fetch_all(self, urls: list[str], offline: bool = False) -> FeedResult:
        """Fetch all feeds; use samples if offline or if every feed failed."""
        result = FeedResult()
        if not offline:
            for url in urls:
                try:
                    result.stories.extend(self.fetch(url))
                except FeedError as exc:
                    LOGGER.warning("feed failed: %s", exc)
                    result.errors.append(str(exc))
        if offline or not result.stories:
            result.used_fallback = True
            result.stories = self.load_samples()
        return result
