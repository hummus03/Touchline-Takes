"""Send drafts for human review as GitHub pull requests (static mode).

For each draft the agents approved (``pending_review``):

* review mode (default): create branch ``review/<draft id>`` from ``main`` with the
  article file, push it, and open a pull request labelled ``newsroom-review``.
  Merging publishes; closing rejects. The draft is then marked ``in_review`` so it is
  never sent twice.
* auto-publish mode (``AUTO_PUBLISH=true``): commit the article file straight to ``main``.

All git/gh calls go through :class:`GitOps` so they can be faked in tests.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

from touchline_takes.content import article_record, review_body, validate_article, write_article
from touchline_takes.db import Database
from touchline_takes.state import Draft
from touchline_takes.tools.text import slugify

LABEL = "newsroom-review"
BOT_NAME = "touchline-takes-newsroom[bot]"
BOT_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"


class GitOpsError(RuntimeError):
    """A git or gh command failed."""


@dataclass
class GitOps:
    """Thin wrapper over the ``git`` and ``gh`` command-line tools."""

    repo_dir: str = "."
    base: str = "main"
    remote: str = "origin"
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run
    log: list[list[str]] = field(default_factory=list)

    def run(self, *args: str) -> str:
        """Run a command in the repository; raise :class:`GitOpsError` on failure."""
        cmd = list(args)
        self.log.append(cmd)
        result = self.runner(cmd, cwd=self.repo_dir, capture_output=True, text=True,
                             check=False)
        if result.returncode != 0:
            raise GitOpsError(f"{' '.join(cmd[:3])}... failed: {result.stderr.strip()[:400]}")
        return result.stdout.strip()

    def git(self, *args: str) -> str:
        """``git -c user... <args>`` (commits are attributed to the newsroom bot)."""
        return self.run("git", "-c", f"user.name={BOT_NAME}", "-c", f"user.email={BOT_EMAIL}",
                        *args)

    def ensure_label(self) -> None:
        """Create the review label if it doesn't exist (idempotent)."""
        self.run("gh", "label", "create", LABEL, "--color", "0B6E3A", "--force",
                 "--description", "Touchline Takes draft awaiting human review")

    def open_review_pr(self, draft_id: str, files: dict[str, str], title: str,
                       body: str) -> str:
        """Commit ``files`` ({repo path: content}) on a review branch and open a PR."""
        branch = f"review/{draft_id}"
        self.git("fetch", self.remote, self.base)
        self.git("switch", "-C", branch, f"{self.remote}/{self.base}")
        try:
            paths = self._write(files)
            self.git("add", "--", *paths)
            self.git("commit", "-m", f"Draft for review: {title}")
            self.git("push", "--force", self.remote, f"HEAD:refs/heads/{branch}")
            with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False,
                                             encoding="utf-8") as handle:
                handle.write(body)
            return self.run("gh", "pr", "create", "--base", self.base, "--head", branch,
                            "--title", f"Review: {title}", "--body-file", handle.name,
                            "--label", LABEL)
        finally:
            try:  # leave the working tree back on the base branch for the next draft
                self.git("switch", "--detach", f"{self.remote}/{self.base}")
            except GitOpsError:
                pass

    def review_branch_exists(self, draft_id: str) -> bool:
        """True if ``review/<draft id>`` is already on the remote (e.g. an open PR)."""
        return bool(self.git("ls-remote", "--heads", self.remote, f"review/{draft_id}"))

    def publish_to_base(self, files: dict[str, str], message: str) -> None:
        """Commit ``files`` directly to the base branch (auto-publish)."""
        self.git("fetch", self.remote, self.base)
        self.git("switch", "--detach", f"{self.remote}/{self.base}")
        paths = self._write(files)
        self.git("add", "--", *paths)
        self.git("commit", "-m", message)
        self.git("push", self.remote, f"HEAD:refs/heads/{self.base}")

    def _write(self, files: dict[str, str]) -> Sequence[str]:
        for rel, content in files.items():
            target = Path(self.repo_dir) / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        return list(files)


@dataclass
class ExportResult:
    """What the export step did."""

    opened: list[str] = field(default_factory=list)      # PR URLs
    published: list[str] = field(default_factory=list)   # slugs committed to main
    skipped: list[str] = field(default_factory=list)     # draft ids that failed validation
    duplicates: list[str] = field(default_factory=list)  # already published or in review
    errors: list[str] = field(default_factory=list)


def choose_slug(draft: Draft, taken: set[str]) -> str:
    """Date-stamped slug from the title, unique against ``taken`` (which it updates)."""
    base = f"{slugify(draft.title, 70)}-{draft.created_at[:10]}"
    slug, n = base, 2
    while slug in taken:
        slug, n = f"{base}-{n}", n + 1
    taken.add(slug)
    return slug


def _published_ids(files: list[Path]) -> set[str]:
    ids = set()
    for path in files:
        try:
            ids.add(json.loads(path.read_text(encoding="utf-8")).get("draft_id"))
        except (json.JSONDecodeError, AttributeError):
            continue
    return ids


def _already_handled(draft: Draft, db: Database, ops: GitOps, published_ids: set[str],
                     auto_publish: bool) -> bool:
    """Draft ids derive from the source story, so this catches re-drafts after a lost state."""
    if draft.id in published_ids:
        draft.status = "published"
    elif not auto_publish and ops.review_branch_exists(draft.id):
        draft.status = "in_review"
    else:
        return False
    db.save_draft(draft)
    return True


def _reject(draft: Draft, db: Database, problems: list[str]) -> None:
    draft.status = "rejected"
    draft.rejection_history.append({"agent": "export", "revision": draft.revision,
                                    "reasons": problems})
    db.log_rejection("export", draft, "export", problems)
    db.save_draft(draft)


def _publish_staged(staged: list[tuple[Draft, dict, str]], db: Database, ops: GitOps,
                    result: "ExportResult") -> None:
    """Commit staged articles to the base branch; mark drafts only after the push worked."""
    try:
        ops.publish_to_base({path: article_text(record) for _, record, path in staged},
                            f"Publish {len(staged)} article(s) from the newsroom")
    except GitOpsError as exc:
        result.errors.append(f"publish to {ops.base}: {exc}")
        return  # drafts stay pending_review; retried next run
    for draft, record, _ in staged:
        db.insert_article_record(record)
        draft.status, draft.slug = "published", record["slug"]
        db.save_draft(draft)
        result.published.append(record["slug"])


def export_pending(db: Database, ops: GitOps, content_dir: str = "content/articles",
                   auto_publish: bool = False,
                   site_url: str = "https://touchlinetakes.com") -> ExportResult:
    """Send every ``pending_review`` draft to GitHub (PRs, or straight to main)."""
    result = ExportResult()
    pending = db.drafts_by_status("pending_review")
    if not pending:
        return result
    published_files = list((Path(ops.repo_dir) / content_dir).glob("*.json"))
    published_ids = _published_ids(published_files)
    taken = {p.stem for p in published_files}
    taken |= {d.slug for d in db.drafts_by_status("in_review") if d.slug}
    if not auto_publish:
        ops.ensure_label()
    staged: list[tuple[Draft, dict, str]] = []
    for draft in pending:
        if _already_handled(draft, db, ops, published_ids, auto_publish):
            result.duplicates.append(draft.id)
            continue
        record = article_record(draft, choose_slug(draft, taken))
        path = f"{content_dir}/{record['slug']}.json"
        problems = validate_article(record, path)
        if problems:
            _reject(draft, db, problems)
            result.skipped.append(draft.id)
        elif auto_publish:
            staged.append((draft, record, path))
        else:
            try:
                url = ops.open_review_pr(draft.id, {path: article_text(record)}, draft.title,
                                         review_body(draft, record["slug"], path, site_url))
            except GitOpsError as exc:
                result.errors.append(f"{draft.id}: {exc}")
                continue  # stays pending_review; retried next run
            draft.status, draft.slug = "in_review", record["slug"]
            db.save_draft(draft)
            result.opened.append(url)
    if staged:
        _publish_staged(staged, db, ops, result)
    return result


def article_text(record: dict) -> str:
    """Serialised article file content (same format as :func:`write_article`)."""
    with tempfile.TemporaryDirectory() as tmp:
        return write_article(tmp, record).read_text(encoding="utf-8")
