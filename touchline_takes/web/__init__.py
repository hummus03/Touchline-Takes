"""Flask app factory for the Touchline Takes site."""

from __future__ import annotations

import secrets
import threading

from flask import Flask
from markupsafe import Markup, escape

from touchline_takes import BRAND_NAME, DOMAIN, TAGLINE
from touchline_takes.config import Settings
from touchline_takes.db import Database
from touchline_takes.tools.text import CITATION_RE, split_paragraphs, strip_citations


def render_body(body: str) -> Markup:
    """Article body -> HTML paragraphs with citation markers as footnote links."""
    html = []
    for para in split_paragraphs(body):
        text = str(escape(para))
        text = CITATION_RE.sub(
            lambda m: f'<sup class="cite"><a href="#src-{m.group(1)}">{m.group(1)}</a></sup>',
            text)
        cls = ' class="verdict"' if para.strip().startswith("The Touchline Take:") or (
            "The Touchline Take:" in para) else ""
        html.append(f"<p{cls}>{text}</p>")
    return Markup("\n".join(html))


def teaser(body: str, length: int = 220) -> str:
    """First paragraph without citations, trimmed."""
    paras = split_paragraphs(strip_citations(body))
    text = paras[0] if paras else ""
    return text if len(text) <= length else text[:length].rsplit(" ", 1)[0] + "…"


class Services:
    """Lazily-built shared services (DB, newsroom pipeline)."""

    def __init__(self, settings: Settings, newsroom=None) -> None:
        self.settings = settings
        self._newsroom = newsroom
        self._lock = threading.Lock()
        self.db = newsroom.db if newsroom is not None else Database(settings.database_path)

    @property
    def newsroom(self):
        """The pipeline (built on first use: loads models, vector store, etc.)."""
        with self._lock:
            if self._newsroom is None:
                from touchline_takes.pipeline import Newsroom  # pylint: disable=import-outside-toplevel
                self._newsroom = Newsroom.build(self.settings, db=self.db)
            return self._newsroom

    def research(self):
        """RAG index, synced with the stories table."""
        newsroom = self.newsroom
        newsroom.research.index_stories(self.db.all_stories())
        return newsroom.research


def create_app(settings: Settings | None = None, newsroom=None, testing: bool = False) -> Flask:
    """Build the Flask application."""
    settings = settings or Settings.from_env()
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=settings.secret_key or secrets.token_hex(32), TESTING=testing,
        SETTINGS=settings, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")
    app.extensions["touchline"] = Services(settings, newsroom)
    app.jinja_env.filters["render_body"] = render_body
    app.jinja_env.filters["teaser"] = teaser
    app.jinja_env.filters["pct"] = lambda v: f"{round(100 * v)}%" if v is not None else "–"

    @app.context_processor
    def _brand():
        return {"brand": BRAND_NAME, "tagline": TAGLINE, "domain": DOMAIN}

    from touchline_takes.web.views import bp  # pylint: disable=import-outside-toplevel
    app.register_blueprint(bp)
    return app
