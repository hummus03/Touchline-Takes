"""RSS fetching/normalisation with a bundled offline fallback."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import re
from urllib.parse import urlparse

import feedparser
import requests

from touchline_takes.state import Story, story_id_for
from touchline_takes.tools.text import strip_html

LOGGER = logging.getLogger(__name__)
USER_AGENT = "TouchlineTakesBot/0.1 (+https://touchlinetakes.com)"


# Clean attribution names by feed host (feed titles are often "Football | The Guardian").
SOURCE_NAMES = {"bbc.co.uk": "BBC Sport", "bbci.co.uk": "BBC Sport",
                "theguardian.com": "The Guardian", "skysports.com": "Sky Sports"}
TRAILER_RE = re.compile(r"\s*(?:Continue reading|Read more|Full story)\s*(?:\.\.\.|…)?\s*$", re.I)
# Newsletter plugs inside summaries ("Sign up now! Sign up now!", "Subscribe for free here").
PROMO_RE = re.compile(
    r"(?:\bSign up (?:now|here|for [^.!?]{0,60}?(?:newsletter|email)(?:\s+here)?)[.!?]?\s*)+|"
    r"\bThis is an extract from [^.]{0,120}\.\s*(?:Subscribe[^.]{0,60}\.?)?|"
    r"\bSubscribe (?:for free )?here\s*\.?", re.I)
# Not news articles: live blogs, commentary, newsletters, podcasts, videos, quizzes.
FORMAT_TITLE_RE = re.compile(
    r"(?:\bcommentary$|(?:^|[-–|:]\s*)live\b|as it happened|^Football Daily\b|Football Weekly|"
    r"\| The Knowledge|\bpodcast\b|\bquiz\b|\bvideo\b|\bin pictures\b)", re.I)
FORMAT_URL_RE = re.compile(r"/(?:live|video|videos|audio|podcasts?|gallery|picture)/", re.I)
# Touchline Takes covers men's senior football; the classifier only skips "Chelsea Women".
WOMENS_RE = re.compile(
    r"\bwomen(?:'s|’s)?\b|\bWSL\b|\bWCL\b|\bLionesses\b|\bNWSL\b|\bLiga F\b", re.I)
# Outlets whose feeds mix sports: keep only football URLs.
FOOTBALL_PATH = {"skysports.com": "/football/"}


def skip_reason(story: Story) -> str:
    """Why a feed item isn't a football news story we can write from ('' = keep it)."""
    return skip_reason_for(story.title, story.url, story.summary, story.categories)


def skip_reason_for(title: str, url: str, summary: str = "",
                    categories: list[str] | None = None) -> str:
    """:func:`skip_reason` for a headline, link, summary and feed categories."""
    host = (urlparse(url).hostname or "").lower()
    path = urlparse(url).path
    for domain, section in FOOTBALL_PATH.items():
        if (host == domain or host.endswith("." + domain)) and section not in path:
            return "not football"
    if FORMAT_TITLE_RE.search(title) or FORMAT_URL_RE.search(path):
        return "not a news article"
    if WOMENS_RE.search(title) or "women" in path.lower() \
            or WOMENS_RE.search(summary[:300]) \
            or any(WOMENS_RE.search(c) or "womens-football" in c for c in categories or ()):
        return "women's football"
    return ""


def source_name(url: str) -> str:
    """Attribution name for a feed URL ("" if unknown, so the feed's own title is used)."""
    host = (urlparse(url).hostname or "").lower()
    return next((name for domain, name in SOURCE_NAMES.items()
                 if host == domain or host.endswith("." + domain)), "")


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
        summary = re.sub(r"\s+", " ", PROMO_RE.sub(" ", TRAILER_RE.sub("", summary))).strip()
        if not title or not url:
            continue
        stories.append(Story(
            id=story_id_for(url, title), title=title, summary=summary or title, url=url,
            source=source, published=_published_iso(entry), image_url=_image_url(entry),
            categories=[str(t.get(k) or "") for t in entry.get("tags", [])
                        for k in ("term", "scheme") if t.get(k)]))
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
        return parse_feed(resp.text, source_name(url))

    def load_samples(self) -> list[Story]:
        """Parse every bundled sample feed (``*.xml``)."""
        stories: list[Story] = []
        for path in sorted(self.sample_dir.glob("*.xml")):
            stories.extend(parse_feed(path.read_text(encoding="utf-8")))
        return stories

    def fetch_all(self, urls: list[str], offline: bool = False,
                  allow_fallback: bool = True) -> FeedResult:
        """Fetch all feeds; use samples if offline or if every feed failed.

        With ``allow_fallback=False`` (production) samples are never used: a failed
        fetch simply yields no stories.
        """
        result = FeedResult()
        if not offline:
            for url in urls:
                try:
                    result.stories.extend(self.fetch(url))
                except FeedError as exc:
                    LOGGER.warning("feed failed: %s", exc)
                    result.errors.append(str(exc))
        if (offline or not result.stories) and allow_fallback:
            result.used_fallback = True
            result.stories = self.load_samples()
        return result
