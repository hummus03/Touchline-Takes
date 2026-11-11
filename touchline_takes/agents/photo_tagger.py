"""Photo tagger agent: tags the photo attached to each story with the VGG16 tagger.

Only the derived tags are stored and shown; source photos are never saved or
republished. The agent is optional: without a trained model (or without Keras) it
logs that it skipped and the rest of the newsroom carries on.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import numpy as np
import requests

from touchline_takes.agents.base import Agent
from touchline_takes.db import Database
from touchline_takes.state import NewsroomState, Story
from touchline_takes.tools.feeds import USER_AGENT

MAX_BYTES = 5 * 1024 * 1024


class ImageFetchError(RuntimeError):
    """The photo could not be fetched or decoded."""


class ImageFetcher:
    """Fetches photos over HTTP(S), or from a local folder for bundled sample feeds."""

    def __init__(self, local_root: str, timeout: float = 10.0,
                 session: requests.Session | None = None, allow_local: bool = True) -> None:
        self.allow_local = allow_local
        self.local_root = Path(local_root).resolve()
        self.timeout = timeout
        self.session = session or requests.Session()

    def fetch(self, url: str) -> bytes:
        """Raw image bytes for ``url`` (size-capped; local paths stay inside ``local_root``)."""
        scheme = urlparse(url).scheme
        if scheme in ("http", "https"):
            try:
                resp = self.session.get(url, timeout=self.timeout,
                                        headers={"User-Agent": USER_AGENT})
                resp.raise_for_status()
            except requests.RequestException as exc:
                raise ImageFetchError(f"{url}: {exc}") from exc
            content = resp.content
            if not str(resp.headers.get("Content-Type", "image/")).startswith("image/"):
                raise ImageFetchError(f"{url}: not an image")
        elif scheme in ("", "file") and self.allow_local:
            path = (self.local_root / urlparse(url).path.lstrip("/")).resolve()
            if not path.is_relative_to(self.local_root) or not path.is_file():
                raise ImageFetchError(f"{url}: not a sample photo")
            content = path.read_bytes()
        else:
            raise ImageFetchError(f"{url}: unsupported scheme")
        if len(content) > MAX_BYTES:
            raise ImageFetchError(f"{url}: image larger than {MAX_BYTES} bytes")
        return content


class PhotoTaggerAgent(Agent):
    """Tags story photos; skips quietly when no trained model is available."""

    name = "photo_tagger"

    def __init__(self, db: Database, fetcher: ImageFetcher,
                 load_tagger: Callable[[], object | None], max_per_run: int = 20,
                 decode: Callable[[bytes, int], np.ndarray] | None = None) -> None:
        super().__init__()
        self.db = db
        self.fetcher = fetcher
        self.load_tagger = load_tagger
        self.max_per_run = max_per_run
        self.decode = decode
        self._tagger = None

    def _candidates(self, state: NewsroomState) -> list[Story]:
        stories = {s.id: s for s in state.stories if s.image_url and not s.image_tags}
        for story in self.db.untagged_photo_stories(self.max_per_run):
            stories.setdefault(story.id, story)
        return list(stories.values())[: self.max_per_run]

    def run(self, state: NewsroomState) -> NewsroomState:
        candidates = self._candidates(state)
        metrics = {"candidates": len(candidates), "tagged": 0, "failed": 0}
        state.metrics["photo_tagger"] = metrics
        if not candidates:
            return state
        if self._tagger is None:
            self._tagger = self.load_tagger()
        if self._tagger is None:
            metrics["skipped"] = "no trained photo model"
            self.log(state, "skipped", "no trained photo model; run "
                     "python scripts/train_photo_tagger.py")
            return state
        if self.decode is None:
            from touchline_takes.models.photo_tagger import load_image  # pylint: disable=import-outside-toplevel
            self.decode = load_image
        size = self._tagger.backbone.input_size
        for story in candidates:
            try:
                pixels = self.decode(self.fetcher.fetch(story.image_url), size)
            except (ImageFetchError, ValueError) as exc:
                metrics["failed"] += 1
                self.log(state, "photo_error", str(exc), story.id)
                continue
            story.image_tags = self._tagger.tag(pixels[None, ...])[0]
            self.db.update_image_tags(story.id, story.image_tags)
            metrics["tagged"] += 1
            self.log(state, "tagged", ", ".join(
                f"{t['tag']} {t['prob']:.0%}" for t in story.image_tags), story.id)
        return state
