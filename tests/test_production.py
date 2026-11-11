"""Production readiness: preflight, hardening, rate limits, no sample data, scheduler."""
# pylint: disable=redefined-outer-name

import base64
import shutil

import pytest

from touchline_takes.config import DATA_DIR, Settings
from touchline_takes.db import Database
from touchline_takes.pipeline import Newsroom
from touchline_takes.preflight import PreflightError, check, require_ready
from touchline_takes.run import StopFlag, main as run_main
from touchline_takes.tools.feeds import FeedClient
from touchline_takes.tools.football_api import FixturesClient
from touchline_takes.web import create_app
from touchline_takes.web.ratelimit import RateLimiter, parse_limit

from tests.conftest import make_story

STRONG = "a" * 40


@pytest.fixture
def prod(settings, tmp_path):
    """Production settings that pass preflight (a copied CSV stands in for real results)."""
    results = tmp_path / "results"
    results.mkdir()
    shutil.copy(DATA_DIR / "results" / "sample_E0_2425.csv", results / "E0_2425.csv")
    return settings.with_overrides(
        environment="production", allow_sample_data=False, offline=False, secret_key=STRONG,
        admin_password="correct-horse-battery", site_url="https://touchlinetakes.com",
        results_dir=str(results), football_data_api_key="key", llm_provider="anthropic",
        proxy_hops=1, rss_feeds=["https://feeds.test/rss"])


def auth(password="correct-horse-battery"):
    """Basic-auth header."""
    return {"Authorization": "Basic " + base64.b64encode(f"admin:{password}".encode()).decode()}


def test_preflight_blocks_unsafe_settings(settings):
    """Weak secrets, http URLs, offline mode and sample data all block production."""
    report = check(settings.with_overrides(environment="production", secret_key="change-me",
                                           admin_password="short", site_url="http://x"))
    text = " | ".join(report.errors)
    for needle in ("SECRET_KEY", "ADMIN_PASSWORD", "https://", "TOUCHLINE_OFFLINE",
                   "ALLOW_SAMPLE_DATA"):
        assert needle in text
    with pytest.raises(PreflightError):
        require_ready(settings.with_overrides(environment="production"))
    assert require_ready(settings).errors  # development: reported, not raised


def test_preflight_passes_real_config_and_catches_sample_db(prod, db):
    """A complete production config passes; synthetic results or sample stories block it."""
    assert check(prod).ok, check(prod).errors
    synthetic = check(prod.with_overrides(results_dir=str(DATA_DIR / "results")))
    assert any("only synthetic sample CSVs" in e for e in synthetic.errors)
    empty = check(prod.with_overrides(results_dir=str(DATA_DIR / "no-such-dir")))
    assert any("no results CSVs" in e for e in empty.errors)
    db.insert_story(make_story())  # https://example.com/1
    assert any("sample stories" in e for e in check(prod, db).errors)
    warned = check(prod.with_overrides(auto_publish=True, llm_provider="offline",
                                       football_data_api_key=""))
    assert warned.ok and len(warned.warnings) == 3


def test_settings_from_env_production_defaults():
    """TOUCHLINE_ENV=production turns sample data off unless explicitly allowed."""
    prod = Settings.from_env({"TOUCHLINE_ENV": "production"})
    assert prod.is_production and not prod.allow_sample_data
    staging = Settings.from_env({"TOUCHLINE_ENV": "production", "ALLOW_SAMPLE_DATA": "true"})
    assert staging.allow_sample_data
    assert Settings.from_env({}).allow_sample_data


def test_no_sample_fallbacks_when_disabled(settings):
    """Feeds and fixtures never fall back to bundled samples when sample data is off."""
    feeds = FeedClient(settings.sample_feed_dir).fetch_all(["https://feeds.test/rss"],
                                                           allow_fallback=False)
    assert not feeds.stories and feeds.errors and not feeds.used_fallback
    fixtures, used = FixturesClient(settings.fixtures_path).upcoming(allow_fallback=False)
    assert not fixtures and not used
    state = Newsroom.build(settings.with_overrides(allow_sample_data=False, offline=False,
                                                   rss_feeds=["https://feeds.test/rss"])
                           ).run_once()
    assert state.metrics["ingest"]["new"] == 0 and not state.metrics["ingest"]["fallback"]
    assert state.metrics["analyst"]["fixtures"] == 0
    assert any(log.action == "no_stories" for log in state.logs)


def test_production_app_refuses_unsafe_config(settings):
    """The web app will not boot in production with a failing preflight."""
    with pytest.raises(PreflightError):
        create_app(settings.with_overrides(environment="production"))


def test_production_app_hardening(prod):
    """Security headers, HSTS, secure cookies, robots.txt, no demo banner, no run-now."""
    app = create_app(prod, testing=True)
    client = app.test_client()
    resp = client.get("/")
    assert resp.headers["Strict-Transport-Security"].startswith("max-age=")
    assert "script-src 'none'" in resp.headers["Content-Security-Policy"]
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert "sample-banner" not in resp.get_data(as_text=True)
    assert app.config["SESSION_COOKIE_SECURE"]
    assert "Disallow: /admin" in client.get("/robots.txt").get_data(as_text=True)
    assert client.get("/healthz").get_json() == {"status": "ok", "stories": 0}
    admin = client.get("/admin", headers=auth()).get_data(as_text=True)
    assert "Run newsroom now" not in admin
    assert client.post("/admin/run", headers=auth()).status_code == 403
    missing = client.get("/no-such-page")
    assert missing.status_code == 404 and "throw-in" in missing.get_data(as_text=True)


def test_dev_app_shows_sample_banner(settings):
    """Outside production, a banner warns that content may be sample data; no HSTS."""
    client = create_app(settings, testing=True).test_client()
    resp = client.get("/")
    assert "sample-banner" in resp.get_data(as_text=True)
    assert "Strict-Transport-Security" not in resp.headers


def test_rate_limiter_window():
    """Sliding window: N hits per window, then blocked until hits age out."""
    now = [0.0]
    limiter = RateLimiter("2/minute", clock=lambda: now[0])
    assert limiter.hit("a") and limiter.hit("a") and not limiter.hit("a")
    assert limiter.hit("b")
    now[0] = 61
    assert not limiter.blocked("a") and limiter.hit("a")
    assert parse_limit("5/hours") == (5, 3600)
    with pytest.raises(ValueError):
        parse_limit("lots")


def test_ask_and_admin_rate_limits_use_real_client_ip(prod):
    """Limits key on the client IP from X-Forwarded-For (ProxyFix); others are unaffected."""
    app = create_app(prod.with_overrides(ask_rate_limit="2/minute",
                                         admin_auth_rate_limit="3/hour"), testing=True)
    client = app.test_client()
    alice = {"X-Forwarded-For": "203.0.113.1"}
    bob = {"X-Forwarded-For": "203.0.113.2"}
    codes = [client.get("/ask?q=arsenal", headers=alice).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
    assert client.get("/ask?q=arsenal", headers=bob).status_code == 200
    assert client.get("/ask", headers=alice).status_code == 200  # empty form isn't limited
    for _ in range(3):
        assert client.get("/admin", headers={**alice, **auth("wrong")}).status_code == 401
    assert client.get("/admin", headers={**alice, **auth()}).status_code == 429
    assert client.get("/admin", headers={**bob, **auth()}).status_code == 200


def test_web_process_never_writes_chroma(settings, tmp_path):
    """The web app searches an in-memory index synced from the DB; only the scheduler
    writes to the persistent Chroma store."""
    chroma = tmp_path / "chroma_web"
    settings = settings.with_overrides(vector_store="chroma", chroma_dir=str(chroma))
    Newsroom.build(settings.with_overrides(vector_store="memory")).run_once()
    app = create_app(settings, testing=True)
    page = app.test_client().get("/ask?q=Aston+Villa+captain").get_data(as_text=True)
    assert "six weeks" in page
    assert not chroma.exists()


def test_database_uses_wal(settings):
    """File databases run in WAL mode so the web app reads while the scheduler writes."""
    database = Database(settings.database_path)
    mode = database._query("PRAGMA journal_mode")[0][0]  # pylint: disable=protected-access
    assert mode == "wal" and database.count_stories() == 0


def test_scheduler_survives_failed_run_and_refuses_unsafe_production(settings, monkeypatch,
                                                                     capsys):
    """One bad run doesn't kill the scheduler; production with bad config exits 2."""
    calls = []

    def flaky(self):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("provider outage")
        return Newsroom.run_once_sequential(self)

    monkeypatch.setattr("touchline_takes.run.Settings.from_env", lambda: settings)
    monkeypatch.setattr(Newsroom, "run_once", flaky)
    monkeypatch.setattr(StopFlag, "sleep", lambda self, seconds: None)
    assert run_main(["--schedule", "1", "--max-runs", "2", "--quiet"]) == 0
    assert len(calls) == 2 and "Summary" in capsys.readouterr().out
    monkeypatch.setattr("touchline_takes.run.Settings.from_env",
                        lambda: settings.with_overrides(environment="production"))
    assert run_main(["--quiet"]) == 2
    assert "refused to start in production" in capsys.readouterr().err


def test_stop_flag():
    """SIGTERM sets the flag and cuts the sleep short."""
    flag = StopFlag()
    flag(15, None)
    flag.sleep(30)  # returns immediately
    assert flag.stop
