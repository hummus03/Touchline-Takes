"""Routes: home, article, /ask, RSS feed and the admin review desk."""

from __future__ import annotations

import hmac
import secrets
from functools import wraps

from flask import (Blueprint, Response, abort, current_app, flash, redirect, render_template,
                   request, session, url_for)
from markupsafe import escape

from touchline_takes.agents.factcheck import check_draft
from touchline_takes.agents.publisher import build_rss
from touchline_takes.tools.stats import load_results
from touchline_takes.transparency import newsroom_stats, prediction_scorecard
from touchline_takes.web.urls import canonical_url, slugify

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
    numbers = current_app.config.get("TRANSPARENCY")
    stats = numbers["newsroom"] if numbers else newsroom_stats(db, db.list_articles(100_000))
    return render_template("index.html", articles=db.list_articles(20),
                           fixtures=db.fixtures_with_predictions(8, upcoming=True), stats=stats)


def photo_tags_for(story_ids: list[str]) -> list[dict]:
    """Photo-tagger output for a draft's source stories (tags only, never the photo)."""
    db = services().db
    out = []
    for story_id in story_ids:
        story = db.get_story(story_id)
        if story is not None and story.image_tags:
            out.append({"source": story.source, "tags": story.image_tags})
    return out


@bp.get("/archive")
def archive():
    """Every published article, newest first."""
    return render_template("archive.html", articles=services().db.list_articles(100_000))


def _fixtures_for(match) -> list[dict]:
    """Upcoming fixtures (with predictions) for which ``match(fixture)`` is true."""
    return [f for f in services().db.fixtures_with_predictions(100, upcoming=True) if match(f)]


def club_directory() -> dict[str, dict]:
    """Every club with an article or an upcoming fixture: slug -> name, league, count."""
    teams = services().teams
    found: dict[str, dict] = {}

    def add(name: str, is_article: bool) -> None:
        # A club's home league from the directory: Chelsea are a Premier League club
        # even when their latest take was about the Champions League.
        entry = found.setdefault(slugify(name), {"name": name, "articles": 0,
                                                 "league": teams.league_of(name) or "",
                                                 "slug": slugify(name)})
        entry["articles"] += int(is_article)

    for item in services().db.list_articles(100_000):
        for name in item["teams"]:
            add(name, True)
    for fixture in services().db.fixtures_with_predictions(100, upcoming=True):
        for side in ("home", "away"):
            add(teams.canonical(fixture[side]), False)
    return dict(sorted(found.items(), key=lambda kv: kv[1]["name"]))


def league_directory() -> dict[str, str]:
    """Every league with an article or a fixture: slug -> name."""
    names = {a["league"] for a in services().db.list_articles(100_000) if a.get("league")}
    names |= {f["league"] for f in services().db.fixtures_with_predictions(100, upcoming=True)
              if f.get("league")}
    return {slugify(n): n for n in sorted(names)}


@bp.get("/clubs")
def clubs():
    """Every club we cover, by league."""
    return render_template("clubs.html", clubs=list(club_directory().values()))


@bp.get("/club/<slug>")
def club(slug: str):
    """One club: its articles and upcoming fixtures."""
    entry = club_directory().get(slug)
    if entry is None:
        abort(404)
    teams = services().teams
    articles = [a for a in services().db.list_articles(100_000) if entry["name"] in a["teams"]]
    fixtures = _fixtures_for(lambda f: entry["name"] in (teams.canonical(f["home"]),
                                                         teams.canonical(f["away"])))
    return render_template("listing.html", heading=entry["name"], kind="club",
                           league=entry["league"], articles=articles, fixtures=fixtures)


@bp.get("/league/<slug>")
def league(slug: str):
    """One league: its articles and upcoming fixtures."""
    name = league_directory().get(slug)
    if name is None:
        abort(404)
    articles = [a for a in services().db.list_articles(100_000) if a.get("league") == name]
    return render_template("listing.html", heading=name, kind="league", league=None,
                           articles=articles,
                           fixtures=_fixtures_for(lambda f: f.get("league") == name))


def transparency_numbers() -> dict:
    """Newsroom stats and the prediction scorecard. The static build computes them from
    the newsroom's state and passes them in; the server computes them from its database."""
    numbers = current_app.config.get("TRANSPARENCY")
    if numbers is None:
        db, settings = services().db, current_app.config["SETTINGS"]
        numbers = {"newsroom": newsroom_stats(db, db.list_articles(100_000)),
                   "scorecard": prediction_scorecard(
                       db, load_results(settings.results_dir, odds=True), services().teams)}
    return numbers


@bp.get("/how-we-check")
def how_we_check():
    """The newsroom in numbers: what it read, checked, cut and spent, and how its
    predictions did against real results and the bookmaker."""
    return render_template("how_we_check.html", **transparency_numbers())


@bp.get("/about")
def about():
    """How Touchline Takes works, editorial standards and corrections."""
    return render_template("about.html")


@bp.get("/privacy")
def privacy():
    """Privacy notice."""
    return render_template("privacy.html")


@bp.get("/terms")
def terms():
    """Terms of use."""
    return render_template("terms.html")


PAGES = ("/archive", "/clubs", "/how-we-check", "/about", "/privacy", "/terms")


def site_paths() -> list[str]:
    """Every public page path (for the sitemap and the static build)."""
    paths = ["/", *PAGES]
    paths += [f"/club/{slug}" for slug in club_directory()]
    paths += [f"/league/{slug}" for slug in league_directory()]
    paths += [f"/article/{a['slug']}" for a in services().db.list_articles(100_000)]
    return paths


@bp.get("/sitemap.xml")
def sitemap():
    """XML sitemap of every public page."""
    base = current_app.config["SETTINGS"].site_url
    urls = [canonical_url(base, path) for path in site_paths()]
    body = ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            + "".join(f"  <url><loc>{escape(u)}</loc></url>\n" for u in urls) + "</urlset>\n")
    return Response(body, mimetype="application/xml")


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
    body = f"User-agent: *\nDisallow: /admin\nSitemap: {settings.site_url}/sitemap.xml\n"
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
