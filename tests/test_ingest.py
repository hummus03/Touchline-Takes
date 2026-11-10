"""Tests for feed parsing and the Ingest agent."""

from touchline_takes.agents.ingest import IngestAgent
from touchline_takes.state import NewsroomState
from touchline_takes.tools.embeddings import HashingTfidfEmbeddings
from touchline_takes.tools.feeds import FeedClient, parse_feed

from tests.conftest import FakeResponse, FakeSession

RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>Live Wire</title>
<item><title>Liverpool sign <b>new</b> striker</title><link>https://x.test/1</link>
<description>&lt;p&gt;Liverpool have signed a striker.&lt;/p&gt;</description>
<pubDate>Sat, 08 Nov 2026 17:30:00 GMT</pubDate></item>
<item><title>No link item</title></item>
</channel></rss>"""


def test_parse_feed_normalises():
    """HTML is stripped, items without links are skipped, dates become ISO."""
    stories = parse_feed(RSS)
    assert len(stories) == 1
    story = stories[0]
    assert story.title == "Liverpool sign new striker"
    assert story.summary == "Liverpool have signed a striker."
    assert story.source == "Live Wire"
    assert story.published.startswith("2026-11-08T17:30")


def test_fetch_all_uses_network_then_fallback(settings):
    """A working feed is used; a failing one falls back to bundled samples."""
    ok = FeedClient(settings.sample_feed_dir, session=FakeSession(
        {"good": FakeResponse(RSS)}))
    result = ok.fetch_all(["https://good.test/rss"])
    assert not result.used_fallback and len(result.stories) == 1

    bad = FeedClient(settings.sample_feed_dir, session=FakeSession(
        {"bad": FakeResponse(status=500)}))
    result = bad.fetch_all(["https://bad.test/rss"])
    assert result.used_fallback and result.errors and len(result.stories) > 5


def test_ingest_stores_and_dedupes(settings, db):
    """Sample feeds contain one cross-source near-duplicate, which is dropped."""
    agent = IngestAgent(db, FeedClient(settings.sample_feed_dir), HashingTfidfEmbeddings(),
                        [], threshold=0.8, offline=True)
    state = agent.run(NewsroomState())
    metrics = state.metrics["ingest"]
    assert metrics["duplicates"] == 1
    assert metrics["new"] == metrics["fetched"] - 1
    assert any(log.action == "duplicate" for log in state.logs)
    # A second run finds nothing new (URL + similarity dedupe).
    again = agent.run(NewsroomState())
    assert again.metrics["ingest"]["new"] == 0
