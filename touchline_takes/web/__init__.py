"""Flask app factory for the Touchline Takes site."""

from __future__ import annotations

import secrets
import threading

from flask import Flask, render_template
from markupsafe import Markup, escape
from werkzeug.middleware.proxy_fix import ProxyFix

from touchline_takes import BRAND_NAME, DOMAIN, TAGLINE
from touchline_takes.config import Settings
from touchline_takes.db import Database
from touchline_takes.preflight import require_ready
from touchline_takes.web.ratelimit import RateLimiter
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


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    # No JavaScript anywhere on the site; inline style attributes draw the probability bars.
    "Content-Security-Policy": "default-src 'self'; script-src 'none'; "
                               "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                               "frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
}


class Services:
    """Lazily-built shared services (DB, newsroom pipeline, rate limiters).

    The web process builds its newsroom with an in-memory vector store: only the
    scheduler writes to the persistent Chroma index, so the two processes never write
    to it at the same time. ``/ask`` searches an in-memory index synced from the DB.
    """

    def __init__(self, settings: Settings, newsroom=None, db: Database | None = None) -> None:
        self.settings = settings
        self._newsroom = newsroom
        self._lock = threading.Lock()
        self._indexed_count = -1
        self.db = db or (newsroom.db if newsroom is not None else
                         Database(settings.database_path))
        self.ask_limiter = RateLimiter(settings.ask_rate_limit)
        self.admin_limiter = RateLimiter(settings.admin_auth_rate_limit)

    @property
    def newsroom(self):
        """The pipeline (built on first use: loads models, vector store, etc.)."""
        with self._lock:
            if self._newsroom is None:
                from touchline_takes.pipeline import Newsroom  # pylint: disable=import-outside-toplevel
                self._newsroom = Newsroom.build(
                    self.settings.with_overrides(vector_store="memory"), db=self.db)
            return self._newsroom

    def research(self):
        """RAG index, synced with the stories table when new stories have arrived."""
        newsroom = self.newsroom
        with self._lock:
            count = self.db.count_stories()
            if count != self._indexed_count:
                newsroom.research.index_stories(self.db.all_stories())
                self._indexed_count = count
        return newsroom.research


def create_app(settings: Settings | None = None, newsroom=None, testing: bool = False,
               db: Database | None = None, run_preflight: bool = True) -> Flask:
    """Build the Flask application (``db``/``run_preflight`` are for static builds)."""
    settings = settings or Settings.from_env()
    services = Services(settings, newsroom, db)
    if settings.is_production and run_preflight:
        require_ready(settings, services.db)  # refuses to boot with unsafe settings
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=settings.secret_key or secrets.token_hex(32), TESTING=testing,
        SETTINGS=settings, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=settings.is_production, MAX_CONTENT_LENGTH=64 * 1024)
    if settings.proxy_hops:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=settings.proxy_hops,
                                x_proto=settings.proxy_hops, x_host=settings.proxy_hops)
    app.extensions["touchline"] = services

    @app.after_request
    def _security_headers(response):
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        if settings.is_production:
            response.headers.setdefault("Strict-Transport-Security",
                                        "max-age=31536000; includeSubDomains")
        return response

    @app.errorhandler(404)
    def _not_found(_error):
        return render_template("error.html", code=404,
                               message="That page has gone out for a throw-in."), 404

    @app.errorhandler(500)
    def _server_error(_error):
        return render_template("error.html", code=500,
                               message="Something went wrong on our side of the pitch."), 500
    app.jinja_env.filters["render_body"] = render_body
    app.jinja_env.filters["teaser"] = teaser
    app.jinja_env.filters["pct"] = lambda v: f"{round(100 * v)}%" if v is not None else "–"

    @app.context_processor
    def _brand():
        return {"brand": BRAND_NAME, "tagline": TAGLINE, "domain": DOMAIN,
                "sample_mode": settings.allow_sample_data, "production": settings.is_production,
                "static_site": settings.is_static,
                "csp": SECURITY_HEADERS["Content-Security-Policy"].replace(
                    "frame-ancestors 'none'; ", "")}

    from touchline_takes.web.views import bp  # pylint: disable=import-outside-toplevel
    app.register_blueprint(bp)
    return app
