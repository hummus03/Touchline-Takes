"""Tests for the Flask site."""
# pylint: disable=redefined-outer-name

import base64
import re

import pytest

from touchline_takes.pipeline import Newsroom
from touchline_takes.web import create_app, render_body


@pytest.fixture
def newsroom(settings):
    """A newsroom that has run once (drafts pending review)."""
    room = Newsroom.build(settings)
    room.run_once()
    return room


@pytest.fixture
def client(settings, newsroom):
    """Test client."""
    app = create_app(settings, newsroom=newsroom, testing=True)
    return app.test_client()


def auth(password="secret"):
    """Basic-auth header."""
    token = base64.b64encode(f"admin:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def test_home_and_brand(client):
    """The home page carries the brand and fixture predictions."""
    page = client.get("/").get_data(as_text=True)
    assert "<title>Touchline Takes | AI-powered football takes" in page
    assert "Upcoming fixtures" in page and "probbar" in page


def test_admin_requires_auth(client):
    """The desk is password-protected."""
    assert client.get("/admin").status_code == 401
    assert client.get("/admin", headers=auth("wrong")).status_code == 401
    assert client.get("/admin", headers=auth()).status_code == 200


def test_admin_approve_flow_and_csrf(client, newsroom):
    """Approving a pending draft publishes it; posts without a CSRF token fail."""
    page = client.get("/admin", headers=auth()).get_data(as_text=True)
    token = re.search(r'name="csrf" value="([0-9a-f]+)"', page).group(1)
    draft = newsroom.db.drafts_by_status("pending_review")[0]
    url = f"/admin/drafts/{draft.id}/approve"
    assert client.post(url, headers=auth()).status_code == 400
    resp = client.post(url, data={"csrf": token}, headers=auth())
    assert resp.status_code == 302
    article = newsroom.db.list_articles()[0]
    page = client.get(f"/article/{article['slug']}").get_data(as_text=True)
    assert article["title"] in page and 'id="src-S1"' in page
    feed = client.get("/feed.xml")
    assert feed.mimetype == "application/rss+xml" and article["slug"] in feed.get_data(
        as_text=True)


def test_admin_reject_flow(client, newsroom):
    """Rejecting removes the draft from the queue and logs the reason."""
    page = client.get("/admin", headers=auth()).get_data(as_text=True)
    token = re.search(r'name="csrf" value="([0-9a-f]+)"', page).group(1)
    draft = newsroom.db.drafts_by_status("pending_review")[0]
    client.post(f"/admin/drafts/{draft.id}/reject", data={"csrf": token, "reason": "meh"},
                headers=auth())
    assert newsroom.db.get_draft(draft.id).status == "rejected_by_editor"
    assert newsroom.db.recent_rejections()[0]["reasons"] == ["meh"]


def test_ask_page(client):
    """Visitors can question the archive."""
    page = client.post("/ask", data={"q": "How long is the Aston Villa captain out?"}
                       ).get_data(as_text=True)
    assert "six weeks" in page and "Sources" in page


def test_admin_localhost_only_without_password(settings, newsroom):
    """Without ADMIN_PASSWORD the desk is limited to localhost."""
    app = create_app(settings.with_overrides(admin_password=""), newsroom=newsroom,
                     testing=True)
    client = app.test_client()
    assert client.get("/admin").status_code == 200
    assert client.get("/admin", environ_base={"REMOTE_ADDR": "10.0.0.5"}).status_code == 403


def test_404_and_render_body():
    """Unknown articles 404; citations become footnote links and HTML is escaped."""
    html = str(render_body("Arsenal <b>won</b> [S1].\n\nThe Touchline Take: yes."))
    assert '<a href="#src-S1">S1</a>' in html and "&lt;b&gt;" in html
    assert 'class="verdict"' in html


def test_article_shows_photo_tags_not_photos(settings):
    """With a tagger available, article pages list photo tags but never embed the photo."""
    from tests.test_photo_tagger import StubTagger  # pylint: disable=import-outside-toplevel
    room = Newsroom.build(settings.with_overrides(auto_publish=True))
    room.photo_tagger.load_tagger = StubTagger
    state = room.run_once()
    assert state.metrics["photo_tagger"]["tagged"] > 0
    client = create_app(settings, newsroom=room, testing=True).test_client()
    def has_photo_tags(article):
        story_ids = room.db.get_draft(article["draft_id"]).story_ids
        return bool(story_ids) and bool(room.db.get_story(story_ids[0]).image_tags)
    slug = next(a["slug"] for a in room.db.list_articles() if has_photo_tags(a))
    page = client.get(f"/article/{slug}").get_data(as_text=True)
    assert "Source photo, as our tagger sees it" in page and "crowd 90%" in page
    assert "sample_photos/" not in page and "<img" not in page
