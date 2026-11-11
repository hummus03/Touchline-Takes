"""Tests for feed parsing and the Ingest agent."""
# pylint: disable=redefined-outer-name

import pytest

from touchline_takes.agents.ingest import IngestAgent
from touchline_takes.state import NewsroomState
from touchline_takes.tools.embeddings import HashingTfidfEmbeddings
from touchline_takes.tools.feeds import FeedClient, parse_feed, skip_reason, source_name
from touchline_takes.tools.text import strip_html

from tests.conftest import FakeResponse, FakeSession, make_story

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


def test_source_names_and_trailers():
    """Feeds are credited by outlet, and 'Continue reading...' tails are dropped."""
    assert source_name("https://www.theguardian.com/football/rss") == "The Guardian"
    assert source_name("https://feeds.bbci.co.uk/sport/football/rss.xml") == "BBC Sport"
    assert source_name("https://www.skysports.com/rss/12040") == "Sky Sports"
    assert source_name("https://example.org/feed") == ""
    rss = ("<?xml version=\"1.0\"?><rss version=\"2.0\"><channel><title>Football | The "
           "Guardian</title><item><title>Arsenal win</title><link>https://g.test/1</link>"
           "<description>&lt;p&gt;Arsenal won the derby.&lt;/p&gt; &lt;a href=\"x\"&gt;"
           "Continue reading...&lt;/a&gt;</description></item></channel></rss>")
    client = FeedClient(".", session=FakeSession(
        {"theguardian.com": FakeResponse(rss)}))
    story = client.fetch("https://www.theguardian.com/football/rss")[0]
    assert story.source == "The Guardian" and story.summary == "Arsenal won the derby."


def test_guardian_standfirst_lines_and_promos():
    """List items end as sentences; newsletter plugs are removed (paraphrased HTML)."""
    assert strip_html("<p>Exit not confirmed</p><ul><li>Return could benefit Palace</li></ul>"
                      "<p>Palace could avoid paying.</p>") == \
        "Exit not confirmed. Return could benefit Palace. Palace could avoid paying."
    rss = ("<?xml version=\"1.0\"?><rss version=\"2.0\"><channel><title>x</title><item>"
           "<title>City under pressure</title><link>https://g.test/2</link><description>"
           "&lt;p&gt;Sign up now! Sign up now? Sign up now! City lost again.&lt;/p&gt;&lt;p&gt;"
           "Sign up for our free newsletter here The manager spoke. This is an extract from "
           "Soccer Desk, a newsletter. Subscribe for free here .&lt;/p&gt;</description></item>"
           "</channel></rss>")
    assert parse_feed(rss, "The Guardian")[0].summary == "City lost again. The manager spoke."


@pytest.mark.parametrize("title,url,summary,reason", [
    ("Hill backs Hamilton over Leclerc", "https://www.skysports.com/f1/news/1", "", "not football"),
    ("Hacken 0-0 Chelsea commentary", "https://www.skysports.com/football/x/live/1", "",
     "not a news article"),
    ("Football Daily | Talking points", "https://www.theguardian.com/football/2026/a", "",
     "not a news article"),
    ("Chelsea held in Europe", "https://www.bbc.co.uk/sport/football/articles/1",
     "Chelsea stay unbeaten in the Women's Champions League.", "women's football"),
    ("WSL talking points", "https://www.theguardian.com/football/2026/b", "", "women's football"),
    ("Arsenal beat Chelsea 2-1", "https://www.skysports.com/football/news/1",
     "Arsenal won the derby.", ""),
    ("Arsenal live up to their billing", "https://www.bbc.co.uk/sport/football/articles/2", "", ""),
])
def test_skip_reason(title, url, summary, reason):
    """Only football news articles about the men's game are written up."""
    story = make_story(1, title=title, summary=summary or title)
    story.url = url
    assert skip_reason(story) == reason


def test_feed_categories_mark_womens_football():
    """A Guardian interview with a WSL player names no women's team; its category does."""
    rss = ("<?xml version=\"1.0\"?><rss version=\"2.0\"><channel><title>x</title><item>"
           "<title>Manchester City's full-back: 'I love football'</title>"
           "<link>https://www.theguardian.com/football/2026/nov/10/interview</link>"
           "<description>The full-back on winning the Double.</description>"
           "<category domain=\"https://www.theguardian.com/football/womens-football\">"
           "Women's football</category><category domain=\"https://www.theguardian.com/"
           "football/manchestercity\">Manchester City</category></item></channel></rss>")
    story = parse_feed(rss, "The Guardian")[0]
    assert "Women's football" in story.categories
    assert skip_reason(story) == "women's football"
