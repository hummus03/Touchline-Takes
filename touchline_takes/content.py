"""Published articles as files (``content/articles/<slug>.json``) for the static site.

In static mode the repository's ``content/articles`` folder is the source of truth for
what is live: the newsroom proposes an article by opening a pull request that adds its
file, and merging the PR publishes it. Because a human can edit the file in the PR,
every file is validated again before the site is built (:func:`validate_article`):
the same "no claim without a source" guardrail, plus checks that keep a hand-edited
file from injecting unsafe links or paths.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from touchline_takes.agents.factcheck import check_draft
from touchline_takes.state import Draft, Evidence, utcnow_iso
from touchline_takes.tools.text import word_count
from touchline_takes.tools.x_poster import intent_url

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
REQUIRED = ("slug", "title", "body", "article_type", "evidence", "published_at")
ARTICLE_TYPES = {"match_report", "preview", "explainer"}


class ContentError(ValueError):
    """An article file is invalid and must not be published."""


def article_record(draft: Draft, slug: str) -> dict[str, Any]:
    """The JSON stored for a published article."""
    return {
        "slug": slug, "title": draft.title, "body": draft.body,
        "article_type": draft.article_type, "league": draft.league, "teams": draft.teams,
        "sources": draft.sources, "evidence": [e.to_dict() for e in draft.evidence],
        "published_at": utcnow_iso(), "draft_id": draft.id, "story_ids": draft.story_ids,
        "mode": draft.mode, "revision": draft.revision,
    }


def write_article(content_dir: str | Path, record: dict[str, Any]) -> Path:
    """Write ``<content_dir>/<slug>.json`` (stable formatting for readable diffs)."""
    path = Path(content_dir) / f"{record['slug']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def validate_article(record: dict[str, Any], filename: str = "") -> list[str]:
    """Problems that block publication (empty list means the file is safe to publish)."""
    problems = [f"missing field '{key}'" for key in REQUIRED if key not in record]
    if problems:
        return problems
    slug = record["slug"]
    if not SLUG_RE.match(str(slug)) or len(slug) > 90:
        problems.append(f"invalid slug {slug!r} (lowercase letters, digits and hyphens only)")
    if filename and Path(filename).stem != slug:
        problems.append(f"file name {Path(filename).name!r} does not match slug {slug!r}")
    if record["article_type"] not in ARTICLE_TYPES:
        problems.append(f"unknown article_type {record['article_type']!r}")
    if not str(record["title"]).strip() or len(str(record["title"])) > 120:
        problems.append("title must be 1-120 characters")
    try:
        evidence = [Evidence(**e) for e in record["evidence"]]
    except TypeError as exc:
        return problems + [f"malformed evidence: {exc}"]
    for item in evidence:
        if item.url and urlparse(item.url).scheme not in ("http", "https"):
            problems.append(f"evidence {item.id} has a non-http(s) link: {item.url!r}")
    for source in record.get("sources", []):
        url = source.get("url", "")
        if url and urlparse(url).scheme not in ("http", "https"):
            problems.append(f"source link is not http(s): {url!r}")
    draft = Draft(id=str(record.get("draft_id", slug)), article_type=record["article_type"],
                  title=str(record["title"]), body=str(record["body"]), evidence=evidence)
    for check in check_draft(draft):
        if check.is_claim and not check.supported:
            problems.append(f"unsourced claim ({check.reason}): {check.sentence}")
    if word_count(draft.body) < 20:
        problems.append("body is too short")
    return problems


def load_articles(content_dir: str | Path) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    """``(valid articles, {file: problems})`` for every ``*.json`` in ``content_dir``."""
    articles, errors = [], {}
    for path in sorted(Path(content_dir).glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors[path.name] = [f"invalid JSON: {exc}"]
            continue
        if not isinstance(record, dict):
            errors[path.name] = ["top level must be a JSON object"]
            continue
        problems = validate_article(record, path.name)
        if problems:
            errors[path.name] = problems
        else:
            articles.append(record)
    return articles, errors


def review_body(draft: Draft, slug: str, path: str,
                site_url: str = "https://touchlinetakes.com") -> str:
    """Markdown description for the review pull request."""
    checks = [c for c in check_draft(draft) if c.is_claim]
    sourced = sum(c.supported for c in checks)
    share = intent_url({"slug": slug, "title": draft.title, "body": draft.body,
                        "mode": draft.mode}, site_url)
    lines = [
        f"## {draft.title}", "",
        f"**Type:** {draft.article_type.replace('_', ' ')} · **League:** {draft.league or '-'} "
        f"· **Writer:** {draft.mode} · **Revisions:** {draft.revision} · "
        f"**Claims sourced:** {sourced}/{len(checks)}", "",
        "### The article", "",
    ]
    lines += [f"> {para}" if para else ">" for para in draft.body.split("\n")]
    lines += ["", "### Sources and data", ""]
    for item in draft.evidence:
        link = f" ([link]({item.url}))" if item.url else ""
        text = item.source if item.kind == "story" else f"{item.source}: {item.text}"
        lines.append(f"- **{item.id}** {text}{link}")
    if draft.rejection_history:
        lines += ["", "### What the Fact-checker and Editor sent back", ""]
        lines += [f"- {r['agent']} (revision {r['revision']}): {'; '.join(r['reasons'])[:300]}"
                  for r in draft.rejection_history]
    lines += [
        "", "### How to review", "",
        "- **Merge** this pull request to publish the article on the site.",
        "- **Close** it to reject the article.",
        f"- **Share:** once the site has updated (about a minute after merging), "
        f"[**Post to X**]({share}) opens X with the post written; check it and press Post.",
        f"- To change the wording, edit `{path}` in this PR before merging. The site build "
        "re-checks every claim against its cited source and refuses to publish a claim "
        "without one.",
        "", f"<sub>Draft `{draft.id}` · slug `{slug}`</sub>",
    ]
    return "\n".join(lines)
