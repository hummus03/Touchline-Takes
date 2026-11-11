"""Post newly published articles to Bluesky (free AT Protocol API).

Each post is the headline and the article's first sentence, with a link card (title,
teaser, share image) pointing at the article. Logs in with an app password, never the
account's main password.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from touchline_takes.tools.x_poster import article_url, lede

SERVICE = "https://bsky.social"
MAX_CHARS = 300


class BlueskyError(RuntimeError):
    """Bluesky refused or failed a request."""


def compose_text(article: dict[str, Any]) -> str:
    """Headline plus first sentence, within Bluesky's 300 characters (the card carries
    the link)."""
    title = article["title"].strip()[:MAX_CHARS]
    first = lede(article)
    if first and len(title) + 2 + len(first) <= MAX_CHARS:
        return f"{title}\n\n{first}"
    return title


class BlueskyClient:
    """Creates posts on the account the app password belongs to."""

    def __init__(self, handle: str, app_password: str, service: str = SERVICE,
                 session: requests.Session | None = None, timeout: float = 20.0) -> None:
        self.handle = handle.lstrip("@")
        self.app_password = app_password
        self.service = service.rstrip("/")
        self.session = session or requests.Session()
        self.timeout = timeout
        self._auth: dict[str, str] | None = None

    def _call(self, method: str, **kwargs) -> dict[str, Any]:
        try:
            resp = self.session.post(f"{self.service}/xrpc/{method}", timeout=self.timeout,
                                     **kwargs)
        except requests.RequestException as exc:
            raise BlueskyError(f"Bluesky request failed: {exc}") from exc
        if resp.status_code != 200:
            raise BlueskyError(f"Bluesky {method} returned {resp.status_code}: "
                               f"{resp.text[:300]}")
        try:
            return resp.json()
        except ValueError as exc:
            raise BlueskyError(f"unexpected Bluesky response: {resp.text[:300]}") from exc

    def login(self) -> dict[str, str]:
        """Start a session (once per run)."""
        if self._auth is None:
            data = self._call("com.atproto.server.createSession",
                              json={"identifier": self.handle, "password": self.app_password})
            self._auth = {"did": data["did"], "jwt": data["accessJwt"]}
        return self._auth

    def upload_image(self, image: bytes, mime: str = "image/png") -> dict[str, Any]:
        """Upload an image; returns the blob reference for an embed."""
        auth = self.login()
        return self._call("com.atproto.repo.uploadBlob", data=image,
                          headers={"Authorization": f"Bearer {auth['jwt']}",
                                   "Content-Type": mime})["blob"]

    def post(self, text: str, link: dict[str, Any] | None = None) -> str:
        """Publish ``text`` (with an optional link card); returns the post's URI."""
        auth = self.login()
        record: dict[str, Any] = {
            "$type": "app.bsky.feed.post", "text": text, "langs": ["en"],
            "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
        if link:
            record["embed"] = {"$type": "app.bsky.embed.external", "external": link}
        data = self._call("com.atproto.repo.createRecord",
                          json={"repo": auth["did"], "collection": "app.bsky.feed.post",
                                "record": record},
                          headers={"Authorization": f"Bearer {auth['jwt']}"})
        return str(data["uri"])


class BlueskyPoster:
    """Turns an article into a Bluesky post with a link card."""

    name = "bluesky"

    def __init__(self, client: BlueskyClient, site_url: str,
                 image_path: str | Path | None = None) -> None:
        self.client = client
        self.site_url = site_url
        self.image_path = Path(image_path) if image_path else None
        self._thumb: dict[str, Any] | None = None

    def preview(self, article: dict[str, Any]) -> str:
        """What will be posted (text and link)."""
        return f"{compose_text(article)}\n[card] {article_url(article, self.site_url)}"

    def post(self, article: dict[str, Any]) -> str:
        """Post the article; returns the post URI."""
        if self._thumb is None and self.image_path and self.image_path.exists():
            try:
                self._thumb = self.client.upload_image(self.image_path.read_bytes())
            except BlueskyError:
                self._thumb = {}  # the card works without a picture
        card = {"uri": article_url(article, self.site_url), "title": article["title"],
                "description": lede(article) or article["title"]}
        if self._thumb:
            card["thumb"] = self._thumb
        return self.client.post(compose_text(article), card)
