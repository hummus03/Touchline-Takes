"""Production preflight: refuse to serve the public site with unsafe settings or sample data.

Run it yourself with ``python -m touchline_takes.preflight``; the web app and the
scheduler also run it at startup when ``TOUCHLINE_ENV=production`` and refuse to
start on any error. Warnings are printed but don't block.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from touchline_takes.config import Settings
from touchline_takes.db import Database

WEAK_SECRETS = {"", "change-me", "changeme", "secret", "password", "admin", "test"}
SAMPLE_URL_MARKERS = ("://example.com/", "://example.org/")


class PreflightError(RuntimeError):
    """Raised when production settings are unsafe."""


@dataclass
class Report:
    """Blocking errors and non-blocking warnings."""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True when nothing blocks a production start."""
        return not self.errors


def _results_are_real(results_dir: str) -> bool:
    files = list(Path(results_dir).glob("*.csv"))
    return bool(files) and not all(f.name.startswith("sample_") for f in files)


def _check_security(settings: Settings, err) -> None:
    if settings.secret_key.strip().lower() in WEAK_SECRETS or len(settings.secret_key) < 32:
        err("SECRET_KEY must be a random value of at least 32 characters "
            "(python -c \"import secrets; print(secrets.token_hex(32))\")")
    if settings.admin_password.strip().lower() in WEAK_SECRETS or \
            len(settings.admin_password) < 12:
        err("ADMIN_PASSWORD must be set and at least 12 characters")
    if not settings.site_url.startswith("https://"):
        err(f"SITE_URL must use https:// (got {settings.site_url})")


def _check_data(settings: Settings, db: Database | None, err, warn) -> None:
    if settings.offline:
        err("TOUCHLINE_OFFLINE must be false in production")
    if not settings.rss_feeds:
        err("RSS_FEEDS is empty")
    if settings.allow_sample_data:
        err("ALLOW_SAMPLE_DATA is true: sample stories, synthetic stats and sample fixtures "
            "could be published as if they were real (only use it on a private staging site)")
        return
    if not _results_are_real(settings.results_dir):
        what = "only synthetic sample CSVs" if any(
            Path(settings.results_dir).glob("*.csv")) else "no results CSVs"
        err(f"{what} in {settings.results_dir}: set RESULTS_SEASONS (Docker) or run "
            "python scripts/download_football_data.py, then retrain with --retrain")
    if not settings.football_data_api_key:
        warn("FOOTBALL_DATA_API_KEY is not set: no fixtures, predictions or previews")
    if db is not None:
        samples = [s.url for s in db.all_stories() if any(m in s.url for m in SAMPLE_URL_MARKERS)]
        if samples:
            err(f"the database contains {len(samples)} sample stories "
                f"(e.g. {samples[0]}): start production from a fresh DATABASE_PATH")


def _check_quality(settings: Settings, warn) -> None:
    if settings.llm_provider == "offline":
        warn("LLM_PROVIDER=offline: articles use the template writer")
    if settings.auto_publish:
        warn("AUTO_PUBLISH=true: drafts go live without human review")
    meta = Path(settings.photo_model_dir) / "meta.json"
    if settings.photo_tagger and meta.exists():
        data = json.loads(meta.read_text(encoding="utf-8")).get("report", {}).get("data", "")
        if "photos_synthetic" in data:
            warn("the photo tagger was trained on synthetic photos: retrain on real ones or "
                 "set PHOTO_TAGGER=false")
    if settings.proxy_hops == 0:
        warn("PROXY_HOPS=0: if a reverse proxy or load balancer sits in front of the app, set "
             "it to 1 so client IPs (rate limits) and https detection are correct")


def check(settings: Settings, db: Database | None = None) -> Report:
    """Check ``settings`` (and the database, if given) for production use."""
    report = Report()
    _check_security(settings, report.errors.append)
    _check_data(settings, db, report.errors.append, report.warnings.append)
    _check_quality(settings, report.warnings.append)
    return report


def require_ready(settings: Settings, db: Database | None = None) -> Report:
    """Raise :class:`PreflightError` listing every blocking problem (production only)."""
    report = check(settings, db)
    if settings.is_production and not report.ok:
        raise PreflightError("Touchline Takes refused to start in production:\n  - "
                             + "\n  - ".join(report.errors))
    return report


def main() -> int:
    """CLI: print the report; exit 1 if anything blocks production."""
    settings = Settings.from_env()
    db = Database(settings.database_path) if Path(settings.database_path).exists() else None
    report = check(settings, db)
    print(f"Environment: {settings.environment}")
    for line in report.errors:
        print(f"ERROR   {line}")
    for line in report.warnings:
        print(f"WARNING {line}")
    print("Ready for production." if report.ok else "Not ready for production.")
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
