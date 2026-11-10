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
    """HTTP Basic auth with ADMIN_PASSWORD; without one, only localhost may enter."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        password = current_app.config["SETTINGS"].admin_password
        if password:
            auth = request.authorization
            if not (auth and auth.username == "admin" and auth.password is not None and
                    hmac.compare_digest(auth.password, password)):
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


@bp.get("/article/<slug>")
def article(slug: str):
    """One article with its sources."""
    item = services().db.get_article(slug)
    if item is None:
        abort(404)
    return render_template("article.html", article=item)


@bp.route("/ask", methods=["GET", "POST"])
def ask():
    """Ask the archive (RAG)."""
    question = request.values.get("q", "").strip()[:300]
    answer = services().research().ask(question) if question else None
    return render_template("ask.html", question=question, answer=answer)


@bp.get("/feed.xml")
def feed():
    """RSS feed of Touchline Takes' own articles."""
    settings = current_app.config["SETTINGS"]
    xml = build_rss(services().db.list_articles(30), settings.site_url)
    return Response(xml, mimetype="application/rss+xml")


@bp.get("/healthz")
def healthz():
    """Liveness probe."""
    return {"status": "ok"}


@bp.get("/admin")
@admin_required
def admin():
    """Review desk: drafts awaiting approval, rejections and the agent log."""
    db = services().db
    pending = db.drafts_by_status("pending_review")
    checks = {d.id: check_draft(d) for d in pending}
    return render_template(
        "admin/review.html", pending=pending, checks=checks,
        rejected=db.drafts_by_status("rejected", "rejected_by_editor")[:15],
        rejections=db.recent_rejections(25), logs=db.recent_logs(60),
        runs=db.recent_runs(5), settings=current_app.config["SETTINGS"])


@bp.post("/admin/drafts/<draft_id>/<action>")
@admin_required
def review_draft(draft_id: str, action: str):
    """Approve (publish) or reject a pending draft."""
    check_csrf()
    svc = services()
    draft = svc.db.get_draft(draft_id)
    if draft is None or draft.status != "pending_review":
        abort(404)
    publisher = svc.newsroom.publisher
    if action == "approve":
        slug = publisher.publish(draft)
        if slug:
            flash(f"Published: {draft.title}", "ok")
        else:
            flash("Blocked by the guardrail: the draft contains unsourced claims.", "error")
    elif action == "reject":
        publisher.reject(draft, request.form.get("reason", "").strip()[:300])
        flash(f"Rejected: {draft.title}", "ok")
    else:
        abort(404)
    return redirect(url_for("site.admin"))


@bp.post("/admin/run")
@admin_required
def run_pipeline():
    """Run the newsroom once from the admin desk."""
    check_csrf()
    state = services().newsroom.run_once()
    flash(f"Run {state.run_id}: {state.metrics.get('drafts')}", "ok")
    return redirect(url_for("site.admin"))
