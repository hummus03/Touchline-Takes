"""Tests for posting new articles to X (no network)."""
# pylint: disable=redefined-outer-name

import json
from datetime import datetime, timezone

import pytest

from scripts import post_social
from touchline_takes.tools.bluesky import BlueskyClient, BlueskyPoster, compose_text
from touchline_takes.tools.x_poster import (MAX_CHARS, URL_WEIGHT, XClient, XCredentials, XError,
                                            compose_post, intent_url, oauth_signature)

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


class FakeX:
    """Records posts; fails on request."""

    name = "x"

    def __init__(self, fail=False):
        self.posts, self.fail = [], fail

    def preview(self, item):
        """What would be posted."""
        return compose_post(item, "https://t.com")

    def post(self, item):
        """Pretend to post."""
        if self.fail:
            raise XError("X returned 402: credits depleted")
        self.posts.append(self.preview(item))
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
    assert not post_social.run(content, state, x, now=NOW)
    assert not x.posts and "old-one" in json.loads(state.read_text())
    (content / "new.json").write_text(json.dumps(article("new-one", "New")))
    assert post_social.run(content, state, x, now=NOW) == {"new-one": "1001"}
    assert not post_social.run(content, state, x, now=NOW)  # not twice
    assert len(x.posts) == 1


def test_failed_posts_are_retried_and_stale_articles_skipped(content, tmp_path):
    """An X outage is retried next deploy; an article merged days late isn't posted."""
    state = tmp_path / "x_posted.json"
    post_social.run(content, state, FakeX(), now=NOW)
    (content / "new.json").write_text(json.dumps(article("new-one", "New")))
    (content / "stale.json").write_text(json.dumps(
        article("stale-one", "Stale", published="2026-11-01T10:00:00+00:00")))
    assert not post_social.run(content, state, FakeX(fail=True), now=NOW)
    assert "new-one" not in json.loads(state.read_text())
    x = FakeX()
    assert post_social.run(content, state, x, now=NOW) == {"new-one": "1001"}
    assert json.loads(state.read_text())["stale-one"].startswith("skipped")


def test_no_keys_means_posting_is_off(content, tmp_path, monkeypatch):
    """Without the four secrets the script does nothing and creates no state."""
    for key in ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET",
                "BLUESKY_HANDLE", "BLUESKY_APP_PASSWORD"):
        monkeypatch.delenv(key, raising=False)
    state = tmp_path / "x_posted.json"
    assert post_social.main(["--network", "x", "--content", str(content),
                             "--state", str(state)]) == 0
    assert post_social.main(["--network", "bluesky", "--content", str(content),
                             "--state", str(state)]) == 0
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


def test_intent_link_opens_x_with_the_post_written():
    """The free 'Post to X' link carries the same text the API would post."""
    url = intent_url(article(), "https://touchlinetakes.com")
    assert url.startswith("https://x.com/intent/post?text=Palace%27s%20Sage")
    assert "touchlinetakes.com%2Farticle%2Fpalace-sacking%2F" in url


class FakeBsky:  # pylint: disable=too-few-public-methods
    """Records the AT Protocol calls."""

    def __init__(self):
        self.calls = []

    def post(self, url, json=None, data=None, headers=None, **_kwargs):  # pylint: disable=redefined-outer-name
        """Fake XRPC endpoint."""
        method = url.rsplit("/", 1)[1]
        self.calls.append((method, json, headers))
        body = {"com.atproto.server.createSession": {"did": "did:plc:abc", "accessJwt": "jwt"},
                "com.atproto.repo.uploadBlob": {"blob": {"$type": "blob",
                                                         "size": len(data or b"")}},
                "com.atproto.repo.createRecord": {"uri": "at://did:plc:abc/post/1"}}[method]
        return type("R", (), {"status_code": 200, "text": "", "json": lambda self: body})()


def test_bluesky_posts_text_with_a_link_card(tmp_path):
    """Logs in once, uploads the share image, posts headline + lede with a card."""
    image = tmp_path / "og.png"
    image.write_bytes(b"png")
    fake = FakeBsky()
    poster = BlueskyPoster(BlueskyClient("@touchlinetakes.bsky.social", "app-pw", session=fake),
                           "https://touchlinetakes.com", image)
    assert poster.post(article()) == "at://did:plc:abc/post/1"
    poster.post(article("second", "Second"))
    methods = [c[0] for c in fake.calls]
    assert methods.count("com.atproto.server.createSession") == 1
    assert methods.count("com.atproto.repo.uploadBlob") == 1
    record = fake.calls[2][1]["record"]
    assert record["text"] == compose_text(article())
    assert record["embed"]["external"]["uri"] == \
        "https://touchlinetakes.com/article/palace-sacking/"
    assert record["embed"]["external"]["thumb"]["$type"] == "blob"
    assert fake.calls[0][1] == {"identifier": "touchlinetakes.bsky.social", "password": "app-pw"}
    assert len(compose_text(article(title="T" * 290))) <= 300
