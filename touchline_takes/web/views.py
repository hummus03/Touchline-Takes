"""Routes: home, article, /ask, RSS feed and the admin review desk."""

from __future__ import annotations

import hmac
import secrets
from functools import wraps

from flask import (Blueprint, Response, abort, current_app, flash, redirect, render_template,
                   request, session, url_for)

from touchline_takes.agents.factcheck import check_draft
from touchline_takes.agents.publisher import build_rss

bp = Blueprint("site", __name__)
LOCAL_ADDRS = {"127.0.0.1", "::1"}


def services():
    """Shared services for the current app."""
    return current_app.extensions["touchline"]


def admin_required(view):
    """HTTP Basic auth with ADMIN_PASSWORD; without one, only localhost may enter.

    Failed logins are rate-limited per client IP to slow down password guessing.
    """
    @wraps(view)
    def wrapper(*args, **kwargs):
        password = current_app.config["SETTINGS"].admin_password
        if password:
            limiter = services().admin_limiter
            client = request.remote_addr or "unknown"
            if limiter.blocked(client):
                return Response("Too many failed logins; try again later.", 429,
                                {"Retry-After": str(limiter.window)})
            auth = request.authorization
            if not (auth and auth.username == "admin" and auth.password is not None and
                    hmac.compare_digest(auth.password.encode(), password.encode())):
                if auth is not None:
                    limiter.hit(client)
                return Response("Admin login required", 401,
                                {"WWW-Authenticate": 'Basic realm="Touchline Takes admin"'})
        elif request.remote_addr not in LOCAL_ADDRS:
            abort(403, "Set ADMIN_PASSWORD to use the admin desk remotely.")
        return view(*args, **kwargs)
    return wrapper


def csrf_token() -> str:
    """Per-session CSRF token."""
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


def check_csrf() -> None:
    """Reject POSTs without the session's token."""
    sent = request.form.get("csrf", "")
    if not sent or not hmac.compare_digest(sent, session.get("csrf", "")):
        abort(400, "Invalid form token; reload the page and try again.")


@bp.app_context_processor
def _inject_csrf():
    return {"csrf_token": csrf_token}


@bp.get("/")
def index():
    """Latest takes and fixtures with Analyst predictions."""
    db = services().db
    return render_template("index.html", articles=db.list_articles(20),
                           fixtures=db.fixtures_with_predictions(8))


def photo_tags_for(story_ids: list[str]) -> list[dict]:
    """Photo-tagger output for a draft's source stories (tags only, never the photo)."""
    db = services().db
    out = []
    for story_id in story_ids:
        story = db.get_story(story_id)
        if story is not None and story.image_tags:
            out.append({"source": story.source, "tags": story.image_tags})
    return out


@bp.get("/article/<slug>")
def article(slug: str):
    """One article with its sources."""
    db = services().db
    item = db.get_article(slug)
    if item is None:
        abort(404)
    draft = db.get_draft(item["draft_id"]) if item.get("draft_id") else None
    return render_template("article.html", article=item,
                           photo_tags=photo_tags_for(draft.story_ids) if draft else [])


@bp.route("/ask", methods=["GET", "POST"])
def ask():
    """Ask the archive (RAG)."""
    question = request.values.get("q", "").strip()[:300]
    answer = None
    if question:
        limiter = services().ask_limiter
        if not limiter.hit(request.remote_addr or "unknown"):
            return render_template("ask.html", question=question, answer=None,
                                   limited=True), 429, {"Retry-After": str(limiter.window)}
        answer = services().research().ask(question)
    return render_template("ask.html", question=question, answer=answer)


@bp.get("/feed.xml")
def feed():
    """RSS feed of Touchline Takes' own articles."""
    settings = current_app.config["SETTINGS"]
    xml = build_rss(services().db.list_articles(30), settings.site_url)
    return Response(xml, mimetype="application/rss+xml")


@bp.get("/robots.txt")
def robots():
    """Let search engines in, keep them out of the admin desk."""
    settings = current_app.config["SETTINGS"]
    body = f"User-agent: *\nDisallow: /admin\nSitemap: {settings.site_url}/feed.xml\n"
    return Response(body, mimetype="text/plain")


@bp.get("/healthz")
def healthz():
    """Health probe: the app is up and the database answers."""
    return {"status": "ok", "stories": services().db.count_stories()}


@bp.get("/admin")
@admin_required
def admin():
    """Review desk: drafts awaiting approval, rejections and the agent log."""
    db = services().db
    pending = db.drafts_by_status("pending_review")
    checks = {d.id: check_draft(d) for d in pending}
    photos = {d.id: photo_tags_for(d.story_ids) for d in pending}
    return render_template(
        "admin/review.html", pending=pending, checks=checks, photos=photos,
        rejected=db.drafts_by_status("rejected", "rejected_by_editor")[:15],
        rejections=db.recent_rejections(25), logs=db.recent_logs(60),
        runs=db.recent_runs(5), settings=current_app.config["SETTINGS"])


@bp.post("/admin/drafts/<draft_id>/<action>")
@admin_required
def review_draft(draft_id: str, action: str):
    """Approve (publish) or reject a pending draft."""
    check_csrf()
    if action not in ("approve", "reject"):
        abort(404)
    # Resumes the run's paused LangGraph thread (or publishes directly for older drafts).
    draft = services().newsroom.review(draft_id, action,
                                       request.form.get("reason", "").strip()[:300])
    if draft is None:
        abort(404)
    if draft.status == "published":
        flash(f"Published: {draft.title}", "ok")
    elif draft.status == "rejected":
        flash("Blocked by the guardrail: the draft contains unsourced claims.", "error")
    else:
        flash(f"Rejected: {draft.title}", "ok")
    return redirect(url_for("site.admin"))


@bp.post("/admin/run")
@admin_required
def run_pipeline():
    """Run the newsroom once from the admin desk (development only; production is scheduled)."""
    if current_app.config["SETTINGS"].is_production:
        abort(403, "Runs are scheduled in production (the scheduler process).")
    check_csrf()
    state = services().newsroom.run_once()
    flash(f"Run {state.run_id}: {state.metrics.get('drafts')}", "ok")
    return redirect(url_for("site.admin"))
