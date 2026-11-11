"""Static-site mode: content files, review PRs, the state branch and the site build."""
# pylint: disable=redefined-outer-name

import json
import os
import subprocess
from pathlib import Path

import pytest

from touchline_takes.config import PROJECT_ROOT
from touchline_takes.content import (ContentError, article_record, load_articles,
                                     review_body, validate_article, write_article)
from touchline_takes.db import Database
from touchline_takes.github_review import (LABEL, GitOps, GitOpsError, choose_slug,
                                           export_pending)
from touchline_takes.pipeline import Newsroom
from touchline_takes.preflight import check
from touchline_takes.static import main as static_main
from touchline_takes.static_site import build_site

from tests.conftest import make_story
from tests.test_factcheck_editor import make_draft


@pytest.fixture
def static(settings):
    """Static-mode settings."""
    return settings.with_overrides(site_mode="static", site_url="https://touchlinetakes.com")


def record(slug="arsenal-v-chelsea-2026-11-11", **changes):
    """A valid article record built from the shared test draft."""
    data = article_record(make_draft(), slug)
    data.update(changes)
    return data


def test_article_record_round_trip_and_validation(tmp_path):
    """A good draft validates; hand edits that add risk are caught."""
    good = record()
    assert not validate_article(good, f"{good['slug']}.json")
    path = write_article(tmp_path, good)
    articles, errors = load_articles(tmp_path)
    assert not errors and articles[0]["title"] == good["title"]
    assert path.read_text().endswith("}\n")
    bad_claim = record(body=good["body"] + " Juventus will bid 90 million [S1].")
    assert any("unsourced claim" in p for p in validate_article(bad_claim))
    evidence = [dict(e) for e in good["evidence"]]
    evidence[0]["url"] = "javascript:alert(1)"
    assert any("non-http(s)" in p for p in validate_article(record(evidence=evidence)))
    assert any("invalid slug" in p for p in validate_article(record(slug="../../x")))
    assert any("does not match" in p for p in validate_article(good, "other.json"))
    assert validate_article({"title": "x"})[0].startswith("missing field")
    (tmp_path / "broken.json").write_text("{not json")
    assert "invalid JSON" in load_articles(tmp_path)[1]["broken.json"][0]


def test_review_body_has_article_sources_and_instructions():
    """The PR description shows the article, its sources and how to review."""
    body = review_body(make_draft(), "slug-x", "content/articles/slug-x.json")
    for needle in ("## Arsenal v Chelsea", "Claims sourced:** 3/3", "**S1** Test Wire",
                   "**Merge** this pull request", "content/articles/slug-x.json"):
        assert needle in body


def test_choose_slug_is_dated_and_unique():
    """Slugs carry the draft date and never collide."""
    draft = make_draft()
    taken = set()
    first, second = choose_slug(draft, taken), choose_slug(draft, taken)
    assert first.endswith(draft.created_at[:10]) and second == first + "-2"


class FakeOps:
    """Stands in for GitOps: records calls, can fail on demand."""

    def __init__(self, repo_dir, fail_pr=False, fail_push=False, branches=()):
        self.repo_dir = str(repo_dir)
        self.base = "main"
        self.fail_pr, self.fail_push = fail_pr, fail_push
        self.branches = set(branches)
        self.labels = 0
        self.prs: list[tuple[str, dict, str]] = []
        self.pushed: dict[str, str] = {}

    def ensure_label(self):
        """Count label creation."""
        self.labels += 1

    def review_branch_exists(self, draft_id):
        """Pretend some review branches exist."""
        return draft_id in self.branches

    def open_review_pr(self, draft_id, files, title, body):
        """Record a PR."""
        if self.fail_pr:
            raise GitOpsError("gh: Resource not accessible by integration")
        self.prs.append((draft_id, files, body))
        assert title
        return f"https://github.com/o/r/pull/{len(self.prs)}"

    def publish_to_base(self, files, message):
        """Record a direct publish."""
        if self.fail_push:
            raise GitOpsError("push rejected")
        assert message
        self.pushed.update(files)


def queue(db, *drafts):
    """Store drafts as awaiting review."""
    for i, draft in enumerate(drafts):
        draft.id, draft.status = f"d{i}", "pending_review"
        db.save_draft(draft)


def test_export_opens_one_pr_per_draft_once(db, tmp_path):
    """Each approved draft becomes one PR; re-running sends nothing twice."""
    queue(db, make_draft(), make_draft())
    ops = FakeOps(tmp_path)
    result = export_pending(db, ops)
    assert len(result.opened) == 2 and ops.labels == 1
    paths = [next(iter(files)) for _, files, _ in ops.prs]
    assert paths[0] != paths[1] and all(p.startswith("content/articles/") for p in paths)
    stored = json.loads(next(iter(ops.prs[0][1].values())))
    assert not validate_article(stored, paths[0])
    assert [d.status for d in db.drafts_by_status("in_review")] == ["in_review"] * 2
    assert not export_pending(db, ops).opened


def test_export_failures_and_duplicates(db, tmp_path):
    """Failed PRs are retried later; invalid drafts are rejected; known drafts are skipped."""
    queue(db, make_draft())
    result = export_pending(db, FakeOps(tmp_path, fail_pr=True))
    assert result.errors and db.drafts_by_status("pending_review")
    bad = make_draft(make_draft().body + " Juventus will bid 90 million [S1].")
    bad.id, bad.status = "bad", "pending_review"
    db.save_draft(bad)
    result = export_pending(db, FakeOps(tmp_path, branches={"d0"}))
    assert result.skipped == ["bad"] and db.get_draft("bad").status == "rejected"
    assert result.duplicates == ["d0"] and db.get_draft("d0").status == "in_review"
    content = tmp_path / "content" / "articles"
    write_article(content, record(slug="already-there", draft_id="x1"))
    again = make_draft()
    again.id, again.status = "x1", "pending_review"
    db.save_draft(again)
    assert export_pending(db, FakeOps(tmp_path)).duplicates == ["x1"]


def test_export_auto_publish(db, tmp_path):
    """AUTO_PUBLISH commits straight to main, and only marks drafts once the push worked."""
    queue(db, make_draft(), make_draft())
    failed = export_pending(db, FakeOps(tmp_path, fail_push=True), auto_publish=True)
    assert failed.errors and len(db.drafts_by_status("pending_review")) == 2
    ops = FakeOps(tmp_path)
    result = export_pending(db, ops, auto_publish=True)
    assert len(result.published) == 2 and len(ops.pushed) == 2 and not ops.prs
    assert len(db.list_articles()) == 2


def test_gitops_commands(tmp_path):
    """GitOps runs the expected git/gh commands and always returns to the base branch."""
    calls = []

    def runner(cmd, **_kwargs):
        calls.append(cmd)
        failing = cmd[:3] == ["gh", "pr", "create"] and "fail" in cmd[cmd.index("--title") + 1]
        return subprocess.CompletedProcess(cmd, 1 if failing else 0,
                                           stdout="https://github.com/o/r/pull/7\n",
                                           stderr="boom" if failing else "")

    ops = GitOps(repo_dir=str(tmp_path), runner=runner)
    url = ops.open_review_pr("abc", {"content/articles/a.json": "{}"}, "A title", "body")
    assert url.endswith("/pull/7") and (tmp_path / "content/articles/a.json").exists()
    flat = [" ".join(c) for c in calls]
    assert any("switch -C review/abc origin/main" in c for c in flat)
    assert any("push --force origin HEAD:refs/heads/review/abc" in c for c in flat)
    assert any(c.startswith("gh pr create --base main --head review/abc") and LABEL in c
               for c in flat)
    assert flat[-1].endswith("switch --detach origin/main")
    calls.clear()
    with pytest.raises(GitOpsError):
        ops.open_review_pr("x", {"content/articles/b.json": "{}"}, "fail", "body")
    assert " ".join(calls[-1]).endswith("switch --detach origin/main")


def git(cwd, *args):
    """Run git quietly."""
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"}
    return subprocess.run(["git", "-c", "push.negotiate=false", *args], cwd=cwd, env=env,
                          check=True, capture_output=True, text=True).stdout


def test_state_branch_round_trip(tmp_path):
    """The state script stores the DB as a parentless commit and restores it elsewhere."""
    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "-q", "--bare", str(origin))
    work = tmp_path / "work"
    git(tmp_path, "clone", "-q", str(origin), str(work))
    (work / "README").write_text("x")
    git(work, "add", "README")
    git(work, "commit", "-qm", "init")
    git(work, "push", "-q", "origin", "HEAD:refs/heads/main")
    script = PROJECT_ROOT / "scripts" / "newsroom_state.sh"
    env = {**os.environ, "STATE_DIR": ".newsroom", "GIT_CONFIG_COUNT": "1",
           "GIT_CONFIG_KEY_0": "push.negotiate", "GIT_CONFIG_VALUE_0": "false"}
    database = Database(str(work / ".newsroom" / "touchline_takes.db"))
    database.insert_story(make_story(5))
    database.close()
    for _ in range(2):  # saving twice still leaves a single commit
        subprocess.run(["bash", str(script), "save"], cwd=work, env=env, check=True,
                       capture_output=True)
    assert git(origin, "log", "--format=%P", "newsroom-state").strip() == ""
    files = git(origin, "ls-tree", "-r", "--name-only", "newsroom-state").split()
    assert files == ["touchline_takes.db"]
    fresh = tmp_path / "fresh"
    git(tmp_path, "clone", "-q", "-b", "main", str(origin), str(fresh))
    out = subprocess.run(["bash", str(script), "restore"], cwd=fresh, env=env, check=True,
                         capture_output=True, text=True).stdout
    assert "Restored" in out
    assert Database(str(fresh / ".newsroom" / "touchline_takes.db")).count_stories() == 1


def test_static_run_does_not_pause_and_queues_drafts(static):
    """In static mode the graph ends without interrupting; drafts wait for export."""
    room = Newsroom.build(static.with_overrides(auto_publish=True))
    state = room.run_once()
    assert room.app.get_state({"configurable": {"thread_id": state.run_id}}).next == ()
    assert not state.published and room.db.drafts_by_status("pending_review")


def test_static_preflight_skips_server_secrets(static):
    """No server means no SECRET_KEY/ADMIN_PASSWORD requirement; HTTPS still required."""
    errors = " ".join(check(static.with_overrides(environment="production")).errors)
    assert "SECRET_KEY" not in errors and "ADMIN_PASSWORD" not in errors
    assert "SITE_URL" in " ".join(check(static.with_overrides(site_url="http://x")).errors)


def test_build_site(tmp_path, static, db):
    """The build renders every page, adds CNAME, and refuses invalid content."""
    content = tmp_path / "content"
    write_article(content, record())
    db.upsert_fixture({"id": "f1", "date": "2026-11-21", "league": "Premier League",
                       "home": "Arsenal", "away": "Chelsea"})
    db.upsert_prediction("f1", {"H": 0.5, "D": 0.3, "A": 0.2}, "H", "v1")
    out = tmp_path / "_site"
    report = build_site(content, out, static.with_overrides(environment="production",
                                                            allow_sample_data=False),
                        state_db=db.path)
    assert report.articles == 1 and report.fixtures == 1
    for page in ("index.html", "archive/index.html", "feed.xml", "sitemap.xml", "robots.txt",
                 "404.html", "article/arsenal-v-chelsea-2026-11-11/index.html",
                 "static/style.css", ".nojekyll"):
        assert (out / page).exists(), page
    assert (out / "CNAME").read_text().strip() == "touchlinetakes.com"
    home = (out / "index.html").read_text()
    assert 'http-equiv="Content-Security-Policy"' in home and "sample-banner" not in home
    assert "/admin" not in home and "/ask" not in home and "Arsenal" in home
    assert "throw-in" in (out / "404.html").read_text()
    write_article(content, record(slug="bad", body="Juventus will bid 90 million [S1]."))
    with pytest.raises(ContentError):
        build_site(content, tmp_path / "_site2", static)
    assert not (tmp_path / "_site2").exists()


def test_static_cli(tmp_path, static, monkeypatch, capsys):
    """CLI exit codes: validate/build fail on bad content; run refuses unsafe production."""
    monkeypatch.setattr("touchline_takes.static.Settings.from_env", lambda: static)
    content = tmp_path / "c"
    write_article(content, record())
    assert static_main(["validate", "--content-dir", str(content)]) == 0
    assert static_main(["build", "--content-dir", str(content),
                        "--out", str(tmp_path / "o")]) == 0
    (Path(content) / "x.json").write_text("[]")
    assert static_main(["validate", "--content-dir", str(content)]) == 1
    assert static_main(["build", "--content-dir", str(content),
                        "--out", str(tmp_path / "o2")]) == 1
    monkeypatch.setattr("touchline_takes.static.Settings.from_env",
                        lambda: static.with_overrides(environment="production"))
    assert static_main(["run"]) == 2
    assert "refused to start" in capsys.readouterr().err


def test_link_preview_tags(tmp_path, static):
    """Every page has Open Graph/Twitter tags with absolute URLs; articles get their own."""
    content = tmp_path / "content"
    write_article(content, record())
    out = tmp_path / "_site"
    build_site(content, out, static.with_overrides(environment="production",
                                                   allow_sample_data=False))
    home = (out / "index.html").read_text()
    assert '<meta property="og:image" content="https://touchlinetakes.com/static/og-image.png">' \
        in home
    assert '<link rel="canonical" href="https://touchlinetakes.com/">' in home
    assert '<meta name="twitter:card" content="summary_large_image">' in home
    page = (out / "article" / "arsenal-v-chelsea-2026-11-11" / "index.html").read_text()
    assert ('<meta property="og:url" content="https://touchlinetakes.com/article/'
            'arsenal-v-chelsea-2026-11-11/">') in page
    assert '<meta property="og:type" content="article">' in page
    assert '<meta property="og:title" content="Arsenal v Chelsea: the Touchline Take">' in page
    assert 'property="article:published_time"' in page
    assert '<meta property="og:description" content="Arsenal beat Chelsea 2-1' in page
    assert (out / "static" / "og-image.png").stat().st_size > 10_000
