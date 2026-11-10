"""Tests for the Publisher agent and RSS output."""
# pylint: disable=redefined-outer-name

import xml.etree.ElementTree as ET

from touchline_takes.agents.publisher import PublisherAgent, build_rss
from touchline_takes.state import NewsroomState

from tests.test_factcheck_editor import make_draft


def test_queue_for_review_when_not_auto(db):
    """Without auto-publish, approved drafts wait for a human."""
    draft = make_draft()
    draft.status = "approved"
    state = PublisherAgent(db, auto_publish=False).run(NewsroomState(drafts=[draft]))
    assert draft.status == "pending_review" and not state.published
    assert db.drafts_by_status("pending_review")[0].id == draft.id


def test_auto_publish_and_unique_slugs(db):
    """Auto-publish stores the article; repeated titles get unique slugs."""
    publisher = PublisherAgent(db, auto_publish=True)
    first, second = make_draft(), make_draft()
    second.id = "d2"
    first.status = second.status = "approved"
    state = publisher.run(NewsroomState(drafts=[first, second]))
    assert state.published == ["arsenal-v-chelsea-the-touchline-take",
                               "arsenal-v-chelsea-the-touchline-take-2"]
    stored = db.get_article(state.published[0])
    assert stored["sources"][0]["url"] == "https://example.com/1"


def test_guardrail_blocks_unsourced_claims(db):
    """A draft with an unsourced claim is never published."""
    draft = make_draft(make_draft().body + " Juventus will bid 90 million.")
    assert PublisherAgent(db).publish(draft) is None
    assert draft.status == "rejected" and db.list_articles() == []
    assert "guardrail" in db.recent_rejections()[0]["reasons"][0]


def test_human_reject(db):
    """Human rejections are logged."""
    draft = make_draft()
    PublisherAgent(db).reject(draft, "not our style")
    assert draft.status == "rejected_by_editor"
    assert db.recent_rejections()[0]["agent"] == "human"


def test_rss_is_valid():
    """The feed parses as XML and strips citation markers."""
    xml = build_rss([{"slug": "a-b", "title": "A & B", "body": "Arsenal won [S1].\n\nMore.",
                      "league": "Premier League", "published_at": "2026-11-10T10:00:00+00:00"}],
                    "https://touchlinetakes.com")
    root = ET.fromstring(xml)
    item = root.find("channel/item")
    assert root.find("channel/title").text == "Touchline Takes"
    assert item.find("title").text == "A & B"
    assert item.find("description").text == "Arsenal won."
    assert item.find("link").text == "https://touchlinetakes.com/article/a-b"
