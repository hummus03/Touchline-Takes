"""A read-only JSON feed for the mobile app: ``/api/v1/...``.

The static build writes every endpoint out as a file (``api/v1/articles.json`` and so on),
so the app reads plain files from GitHub Pages and needs no server. Citations are kept as
lists of evidence ids so the app can show sources the way the site does.
"""

from __future__ import annotations

from flask import Blueprint, abort, current_app, jsonify

from touchline_takes.tools.text import citations, split_paragraphs, strip_citations, teaser
from touchline_takes.web.urls import canonical_url

API_VERSION = 1
api = Blueprint("api", __name__, url_prefix=f"/api/v{API_VERSION}")


def _views():
    from touchline_takes.web import views  # pylint: disable=import-outside-toplevel
    return views


def _summary(item: dict) -> dict:
    """The fields a list of articles needs."""
    base = current_app.config["SETTINGS"].site_url
    return {"slug": item["slug"], "title": item["title"],
            "teaser": teaser(item["body"]), "type": item["article_type"],
            "league": item.get("league") or "", "teams": list(item.get("teams") or []),
            "published_at": item["published_at"], "sources": len(item.get("sources") or []),
            "url": canonical_url(base, f"/article/{item['slug']}")}


def _paragraphs(body: str) -> list[dict]:
    """Body paragraphs without citation markers, each with the ids it cites."""
    return [{"text": strip_citations(p), "cites": list(dict.fromkeys(citations(p))),
             "verdict": "The Touchline Take:" in p} for p in split_paragraphs(body)]


def _evidence(item: dict) -> dict:
    return {"id": item.get("id", ""), "kind": item.get("kind", ""),
            "source": item.get("source", ""), "text": item.get("text", ""),
            "url": item.get("url") or ""}


@api.get("/articles.json")
def articles():
    """Every published article, newest first."""
    rows = _views().services().db.list_articles(100_000)
    return jsonify({"version": API_VERSION, "articles": [_summary(a) for a in rows]})


@api.get("/article/<slug>.json")
def article(slug: str):
    """One article: paragraphs with their citations, and the evidence they cite."""
    item = _views().services().db.get_article(slug)
    if item is None:
        abort(404)
    return jsonify({**_summary(item), "paragraphs": _paragraphs(item["body"]),
                    "evidence": [_evidence(e) for e in item.get("evidence") or []]})


@api.get("/clubs.json")
def clubs():
    """Every club we cover, with its league and number of articles."""
    entries = _views().club_directory().values()
    return jsonify({"version": API_VERSION, "clubs": [
        {"slug": c["slug"], "name": c["name"], "league": c["league"],
         "articles": c["articles"]} for c in entries]})


@api.get("/fixtures.json")
def fixtures():
    """Upcoming fixtures with the model's win/draw/loss probabilities."""
    rows = _views().services().db.fixtures_with_predictions(100, upcoming=True)
    return jsonify({"version": API_VERSION, "fixtures": [
        {"id": f["id"], "date": f["date"], "league": f.get("league") or "",
         "home": f["home"], "away": f["away"], "home_win": f.get("home_win"),
         "draw": f.get("draw"), "away_win": f.get("away_win")} for f in rows]})


def api_paths() -> list[str]:
    """Every API path, for the static build."""
    slugs = [a["slug"] for a in _views().services().db.list_articles(100_000)]
    return [f"{api.url_prefix}/{name}.json" for name in ("articles", "clubs", "fixtures")] + [
        f"{api.url_prefix}/article/{slug}.json" for slug in slugs]
