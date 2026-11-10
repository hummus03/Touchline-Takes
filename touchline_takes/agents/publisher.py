"""Publisher agent: stores approved articles (or queues them for human review) and builds RSS."""

from __future__ import annotations

from email.utils import format_datetime
from datetime import datetime, timezone
from typing import Any
from xml.sax.saxutils import escape

from touchline_takes import BRAND_NAME, TAGLINE
from touchline_takes.agents.base import Agent
from touchline_takes.agents.factcheck import unsupported_claims
from touchline_takes.db import Database
from touchline_takes.state import Draft, NewsroomState
from touchline_takes.tools.text import slugify, split_paragraphs, strip_citations


class PublisherAgent(Agent):
    """Publishes approved drafts, enforcing the 'no unsourced claim' guardrail."""

    name = "publisher"

    def __init__(self, db: Database, auto_publish: bool = False) -> None:
        super().__init__()
        self.db = db
        self.auto_publish = auto_publish

    def unique_slug(self, title: str) -> str:
        """Slug from the title, de-duplicated against existing articles."""
        base = slugify(title)
        slug, n = base, 2
        while self.db.slug_exists(slug):
            slug, n = f"{base}-{n}", n + 1
        return slug

    def publish(self, draft: Draft, state: NewsroomState | None = None) -> str | None:
        """Publish one draft; returns the slug, or ``None`` if the guardrail blocks it."""
        state = state or NewsroomState()
        bad = unsupported_claims(draft)
        if bad:
            draft.status = "rejected"
            self.db.log_rejection(state.run_id, draft, self.name,
                                  [f"guardrail: unsourced claim: {b}" for b in bad])
            self.log(state, "blocked", f"{len(bad)} unsourced claim(s)", draft.id)
            self.db.save_draft(draft, state.run_id)
            return None
        slug = self.unique_slug(draft.title)
        self.db.insert_article(slug, draft)
        draft.status = "published"
        self.db.save_draft(draft, state.run_id)
        state.published.append(slug)
        self.log(state, "published", f"/article/{slug}", draft.id)
        return slug

    def reject(self, draft: Draft, reason: str, state: NewsroomState | None = None) -> None:
        """Human rejection from the admin page."""
        state = state or NewsroomState()
        draft.status = "rejected_by_editor"
        draft.rejection_history.append({"agent": "human", "revision": draft.revision,
                                        "reasons": [reason or "rejected in review"]})
        self.db.log_rejection(state.run_id, draft, "human", [reason or "rejected in review"])
        self.db.save_draft(draft, state.run_id)

    def run(self, state: NewsroomState) -> NewsroomState:
        for draft in state.drafts_with_status("approved"):
            if self.auto_publish:
                self.publish(draft, state)
            else:
                draft.status = "pending_review"
                self.db.save_draft(draft, state.run_id)
                self.log(state, "queued", "awaiting human review in /admin", draft.id)
        state.metrics["publisher"] = {
            "published": len(state.published),
            "pending_review": len(state.drafts_with_status("pending_review")),
            "auto_publish": self.auto_publish}
        return state


def _rfc822(iso: str) -> str:
    try:
        moment = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        moment = datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return format_datetime(moment)


def build_rss(articles: list[dict[str, Any]], site_url: str) -> str:
    """RSS 2.0 feed of Touchline Takes' own published articles."""
    items = []
    for art in articles:
        link = f"{site_url}/article/{art['slug']}"
        paras = split_paragraphs(strip_citations(art["body"]))
        summary = paras[0] if paras else ""
        items.append(
            "<item>"
            f"<title>{escape(art['title'])}</title>"
            f"<link>{escape(link)}</link>"
            f"<guid isPermaLink=\"true\">{escape(link)}</guid>"
            f"<pubDate>{_rfc822(art.get('published_at') or '')}</pubDate>"
            f"<category>{escape(art.get('league') or 'Football')}</category>"
            f"<description>{escape(summary)}</description>"
            "</item>")
    return ("<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
            "<rss version=\"2.0\"><channel>"
            f"<title>{escape(BRAND_NAME)}</title>"
            f"<link>{escape(site_url)}</link>"
            f"<description>{escape(TAGLINE)}</description>"
            "<language>en-gb</language>"
            + "".join(items) + "</channel></rss>")
