"""Post newly published articles to X (Twitter).

One post per article: headline, a one-sentence teaser and the link. The account's own
keys (OAuth 1.0a user context) sign each request; nothing is read from X.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import requests

from touchline_takes.tools.text import split_paragraphs, split_sentences, strip_citations

POST_URL = "https://api.x.com/2/tweets"
MAX_CHARS = 280
URL_WEIGHT = 23  # X counts every link as 23 characters, whatever its length


class XError(RuntimeError):
    """X refused or failed a request."""


@dataclass
class XCredentials:
    """The four keys of the posting account (from the X Developer Console)."""

    api_key: str
    api_secret: str
    access_token: str
    access_secret: str

    @property
    def complete(self) -> bool:
        """True when all four keys are set."""
        return all((self.api_key, self.api_secret, self.access_token, self.access_secret))


def _pct(value: str) -> str:
    """RFC 3986 percent-encoding, as OAuth 1.0a requires."""
    return quote(value, safe="-._~")


def oauth_signature(method: str, url: str, params: dict[str, str], consumer_secret: str,
                    token_secret: str) -> str:
    """HMAC-SHA1 signature over the method, URL and (query + oauth) parameters."""
    pairs = sorted((_pct(k), _pct(v)) for k, v in params.items())
    param_string = "&".join(f"{k}={v}" for k, v in pairs)
    base = "&".join((method.upper(), _pct(url), _pct(param_string)))
    key = f"{_pct(consumer_secret)}&{_pct(token_secret)}"
    digest = hmac.new(key.encode(), base.encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


def oauth_header(method: str, url: str, creds: XCredentials, query: dict[str, str] | None = None,
                 nonce: str = "", timestamp: str = "") -> str:
    """The ``Authorization`` header for one request (a JSON body is not signed)."""
    oauth = {
        "oauth_consumer_key": creds.api_key,
        "oauth_nonce": nonce or secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": timestamp or str(int(time.time())),
        "oauth_token": creds.access_token,
        "oauth_version": "1.0",
    }
    oauth["oauth_signature"] = oauth_signature(method, url, {**(query or {}), **oauth},
                                               creds.api_secret, creds.access_secret)
    return "OAuth " + ", ".join(f'{_pct(k)}="{_pct(v)}"' for k, v in sorted(oauth.items()))


def _weighted_length(text: str) -> int:
    """Characters as X counts them (close enough for the plain text written here)."""
    return len(text)


def compose_post(article: dict[str, Any], site_url: str) -> str:
    """Headline, the article's first sentence (if it fits) and the link, within 280."""
    url = f"{site_url.rstrip('/')}/article/{article['slug']}/"
    title = article["title"].strip()
    budget = MAX_CHARS - URL_WEIGHT - 2  # two newlines before the link
    if _weighted_length(title) > budget:
        title = title[:budget - 1].rsplit(" ", 1)[0] + "…"
    # A template article opens with "BBC Sport has a story involving...": headline only.
    body = article.get("body", "") if article.get("mode") == "llm" else ""
    paras = split_paragraphs(strip_citations(body))
    sentences = split_sentences(paras[0]) if paras else []
    lede = " ".join(s.strip() for s in sentences[:1]).replace(" .", ".")
    room = budget - _weighted_length(title) - 2
    if lede and _weighted_length(lede) <= room:
        return f"{title}\n\n{lede}\n\n{url}"
    return f"{title}\n\n{url}"


class XClient:  # pylint: disable=too-few-public-methods
    """Creates posts on the account the credentials belong to."""

    def __init__(self, creds: XCredentials, session: requests.Session | None = None,
                 timeout: float = 20.0) -> None:
        self.creds = creds
        self.session = session or requests.Session()
        self.timeout = timeout

    def post(self, text: str) -> str:
        """Publish ``text``; returns the new post's id."""
        try:
            resp = self.session.post(
                POST_URL, json={"text": text}, timeout=self.timeout,
                headers={"Authorization": oauth_header("POST", POST_URL, self.creds)})
        except requests.RequestException as exc:
            raise XError(f"X request failed: {exc}") from exc
        if resp.status_code not in (200, 201):
            raise XError(f"X returned {resp.status_code}: {resp.text[:300]}")
        try:
            return str(resp.json()["data"]["id"])
        except (ValueError, KeyError, TypeError) as exc:
            raise XError(f"unexpected X response: {resp.text[:300]}") from exc
