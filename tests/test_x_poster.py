"""Tests for posting new articles to X (no network)."""
# pylint: disable=redefined-outer-name

import json
from datetime import datetime, timezone

import pytest

from scripts import post_to_x
from touchline_takes.tools.x_poster import (MAX_CHARS, URL_WEIGHT, XClient, XCredentials, XError,
                                            compose_post, oauth_signature)

NOW = datetime(2026, 11, 11, 18, 0, tzinfo=timezone.utc)


def test_oauth_signature_matches_the_documented_example():
    """The worked example from X's 'Creating a signature' documentation."""
    params = {
        "status": "Hello Ladies + Gentlemen, a signed OAuth request!",
        "include_entities": "true",
        "oauth_consumer_key": "xvz1evFS4wEEPTGEFPHBog",
        "oauth_nonce": "kYjzVBB8Y0ZFabxSWbWovY3uYSQ2pTgmZeNu2VS4cg",
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": "1318622958",
        "oauth_token": "370773112-GmHxMAgYyLbNEtIKZeRNFsMKPR9EyMZeS9weJAEb",
        "oauth_version": "1.0",
    }
    assert oauth_signature("post", "https://api.twitter.com/1.1/statuses/update.json", params,
                           "kAcSOqF21Fu85e7zjz7ZN2U4ZRhfV3WpwPAoE3Z7kBw",
                           "LswwdoUaIvS8ltyTt5jkRh4J50vUPVVHtR2YPi5kE") \
        == "hCtSmYh+iHYCEqBWrE7C7hYmtUk="


def article(slug="palace-sacking", title="Palace's Sage Sacking Is the Easy Bit",
            published="2026-11-11T17:00:00+00:00", body=None):
    """A published-article record."""
    return {"slug": slug, "title": title, "published_at": published, "mode": "llm",
            "body": body or ("Crystal Palace are poised to sack Pierre Sage [S1][S2]. It is a "
                             "stark moment [S2].\n\nMore detail [S1].")}


def test_compose_post_fits_and_drops_citations():
    """Headline, first sentence without citation markers, then the link."""
    text = compose_post(article(), "https://touchlinetakes.com")
    assert text == ("Palace's Sage Sacking Is the Easy Bit\n\nCrystal Palace are poised to sack "
                    "Pierre Sage.\n\nhttps://touchlinetakes.com/article/palace-sacking/")
    long = compose_post(article(body="Word " * 120 + "[S1]."), "https://touchlinetakes.com")
    assert long.count("\n\n") == 1  # a sentence that doesn't fit is left out
    weighted = len(long) - len(long.rsplit("\n", 1)[1]) + URL_WEIGHT
    assert weighted <= MAX_CHARS
    template = {**article(), "mode": "template"}
    assert compose_post(template, "https://t.com").count("\n\n") == 1  # headline + link


class FakeX:  # pylint: disable=too-few-public-methods
    """Records posts; fails on request."""

    def __init__(self, fail=False):
        self.posts, self.fail = [], fail

    def post(self, text):
        """Pretend to post."""
        if self.fail:
            raise XError("X returned 503")
        self.posts.append(text)
        return str(1000 + len(self.posts))


@pytest.fixture
def content(tmp_path):
    """A content directory with one existing article."""
    folder = tmp_path / "articles"
    folder.mkdir()
    (folder / "old.json").write_text(json.dumps(article("old-one", "Old")))
    return folder


def test_first_run_marks_existing_articles_then_posts_new_ones_once(content, tmp_path):
    """Switching posting on doesn't flood the timeline; each new article goes out once."""
    state, x = tmp_path / ".social" / "x_posted.json", FakeX()
    assert not post_to_x.run(content, state, "https://t.com", x, now=NOW)
    assert not x.posts and "old-one" in json.loads(state.read_text())
    (content / "new.json").write_text(json.dumps(article("new-one", "New")))
    assert post_to_x.run(content, state, "https://t.com", x, now=NOW) == {"new-one": "1001"}
    assert not post_to_x.run(content, state, "https://t.com", x, now=NOW)  # not twice
    assert len(x.posts) == 1


def test_failed_posts_are_retried_and_stale_articles_skipped(content, tmp_path):
    """An X outage is retried next deploy; an article merged days late isn't posted."""
    state = tmp_path / "x_posted.json"
    post_to_x.run(content, state, "https://t.com", FakeX(), now=NOW)
    (content / "new.json").write_text(json.dumps(article("new-one", "New")))
    (content / "stale.json").write_text(json.dumps(
        article("stale-one", "Stale", published="2026-11-01T10:00:00+00:00")))
    assert not post_to_x.run(content, state, "https://t.com", FakeX(fail=True), now=NOW)
    assert "new-one" not in json.loads(state.read_text())
    x = FakeX()
    assert post_to_x.run(content, state, "https://t.com", x, now=NOW) == {"new-one": "1001"}
    assert json.loads(state.read_text())["stale-one"].startswith("skipped")


def test_no_keys_means_posting_is_off(content, tmp_path, monkeypatch):
    """Without the four secrets the script does nothing and creates no state."""
    for key in ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET"):
        monkeypatch.delenv(key, raising=False)
    state = tmp_path / "x_posted.json"
    assert post_to_x.main(["--content", str(content), "--state", str(state)]) == 0
    assert not state.exists()


def test_client_sends_signed_json_and_reads_the_id():
    """The client posts {"text": ...} with an OAuth header and returns the new id."""
    sent = {}

    class Session:  # pylint: disable=too-few-public-methods
        """Captures the request."""

        def post(self, url, json=None, timeout=None, headers=None):  # pylint: disable=redefined-outer-name
            """Fake POST."""
            sent.update(url=url, json=json, timeout=timeout, headers=headers)
            return type("R", (), {"status_code": 201, "text": "",
                                  "json": lambda self: {"data": {"id": "42"}}})()

    client = XClient(XCredentials("k", "ks", "t", "ts"), session=Session())
    assert client.post("hello") == "42"
    assert sent["url"] == "https://api.x.com/2/tweets" and sent["json"] == {"text": "hello"}
    assert sent["headers"]["Authorization"].startswith('OAuth oauth_consumer_key="k"')
