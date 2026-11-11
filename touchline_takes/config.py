"""Runtime configuration loaded from environment variables (and an optional .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Mapping

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"

DEFAULT_FEEDS = ("https://feeds.bbci.co.uk/sport/football/rss.xml",
                 "https://www.theguardian.com/football/rss",
                 "https://www.skysports.com/rss/12040")


def _as_bool(value: str | None, default: bool = False) -> bool:
    """Parse a truthy environment value."""
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_list(value: str | None, default: tuple[str, ...]) -> list[str]:
    """Parse a comma-separated environment value."""
    if not value:
        return list(default)
    return [item.strip() for item in value.split(",") if item.strip()]


def _resolve(path: str) -> str:
    """Resolve relative paths against the project root."""
    candidate = Path(path)
    return str(candidate if candidate.is_absolute() else PROJECT_ROOT / candidate)


@dataclass
class Settings:
    """All tunable knobs for the newsroom, the web app and the tools."""

    environment: str = "development"  # development | production
    site_mode: str = "server"         # server (Flask app) | static (GitHub Actions + Pages)
    allow_sample_data: bool = True    # False in production unless ALLOW_SAMPLE_DATA=true
    ask_rate_limit: str = "10/minute"
    admin_auth_rate_limit: str = "20/hour"
    proxy_hops: int = 0               # reverse proxies in front of the app (ProxyFix)

    database_path: str = str(DATA_DIR / "touchline_takes.db")
    rss_feeds: list[str] = field(default_factory=lambda: list(DEFAULT_FEEDS))
    sample_feed_dir: str = str(DATA_DIR / "sample_feeds")
    offline: bool = False
    football_data_api_key: str = ""
    fixtures_path: str = str(DATA_DIR / "fixtures" / "sample_fixtures.json")
    results_dir: str = str(DATA_DIR / "results")
    teams_path: str = str(DATA_DIR / "teams.json")
    model_path: str = str(DATA_DIR / "models" / "match_predictor.joblib")
    llm_provider: str = "offline"
    llm_model: str = ""
    llm_effort: str = "medium"
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    llm_max_calls_per_run: int = 40
    llm_cache: bool = True
    embeddings_provider: str = "tfidf"
    embeddings_model: str = "text-embedding-3-small"
    vector_store: str = "chroma"
    chroma_dir: str = str(DATA_DIR / "chroma")
    classifier_provider: str = "local"
    factcheck_verifier: str = "rules"
    photo_tagger: bool = True
    photo_model_dir: str = str(DATA_DIR / "models" / "photo_tagger")
    photo_max_per_run: int = 20
    orchestrator: str = "langgraph"
    checkpoint_path: str = str(DATA_DIR / "checkpoints.db")
    dedupe_threshold: float = 0.8
    auto_publish: bool = False
    max_revisions: int = 2
    max_articles_per_run: int = 6
    admin_password: str = ""
    secret_key: str = ""
    site_url: str = "https://touchlinetakes.com"
    contact_email: str = "touchlinetakes101@gmail.com"  # shown on the About/Privacy pages
    request_timeout: float = 10.0

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None, load_dotenv_file: bool = True
                 ) -> "Settings":
        """Build settings from ``env`` (defaults to ``os.environ`` plus ``.env``)."""
        if env is None:
            if load_dotenv_file:
                try:
                    from dotenv import load_dotenv  # pylint: disable=import-outside-toplevel
                    load_dotenv(PROJECT_ROOT / ".env")
                except ImportError:  # pragma: no cover - dotenv is pinned
                    pass
            env = os.environ
        get = env.get
        defaults = cls()
        environment = (get("TOUCHLINE_ENV", "development") or "development").strip().lower()
        return cls(
            environment=environment,
            site_mode=(get("SITE_MODE", "server") or "server").strip().lower(),
            allow_sample_data=_as_bool(get("ALLOW_SAMPLE_DATA"), environment != "production"),
            ask_rate_limit=get("ASK_RATE_LIMIT", "10/minute") or "10/minute",
            admin_auth_rate_limit=get("ADMIN_AUTH_RATE_LIMIT", "20/hour") or "20/hour",
            proxy_hops=int(get("PROXY_HOPS", "0") or 0),
            database_path=_resolve(get("DATABASE_PATH", defaults.database_path)),
            rss_feeds=_as_list(get("RSS_FEEDS"), DEFAULT_FEEDS),
            sample_feed_dir=_resolve(get("SAMPLE_FEED_DIR", defaults.sample_feed_dir)),
            offline=_as_bool(get("TOUCHLINE_OFFLINE")),
            football_data_api_key=get("FOOTBALL_DATA_API_KEY", ""),
            fixtures_path=_resolve(get("FIXTURES_PATH", defaults.fixtures_path)),
            results_dir=_resolve(get("RESULTS_DIR", defaults.results_dir)),
            teams_path=_resolve(get("TEAMS_PATH", defaults.teams_path)),
            model_path=_resolve(get("MODEL_PATH", defaults.model_path)),
            llm_provider=get("LLM_PROVIDER", "offline").strip().lower() or "offline",
            llm_model=get("LLM_MODEL", ""),
            llm_effort=get("LLM_EFFORT", "medium") or "medium",
            anthropic_api_key=get("ANTHROPIC_API_KEY", ""),
            openai_api_key=get("OPENAI_API_KEY", ""),
            openai_base_url=get("OPENAI_BASE_URL", defaults.openai_base_url)
            or defaults.openai_base_url,
            llm_max_calls_per_run=int(get("LLM_MAX_CALLS_PER_RUN", "40") or 40),
            llm_cache=_as_bool(get("LLM_CACHE"), True),
            embeddings_provider=get("EMBEDDINGS_PROVIDER", "tfidf").strip().lower() or "tfidf",
            embeddings_model=get("EMBEDDINGS_MODEL", defaults.embeddings_model)
            or defaults.embeddings_model,
            vector_store=get("VECTOR_STORE", "chroma").strip().lower() or "chroma",
            chroma_dir=_resolve(get("CHROMA_DIR", defaults.chroma_dir)),
            classifier_provider=get("CLASSIFIER_PROVIDER", "local").strip().lower() or "local",
            factcheck_verifier=get("FACTCHECK_VERIFIER", "rules").strip().lower() or "rules",
            photo_tagger=_as_bool(get("PHOTO_TAGGER"), True),
            photo_model_dir=_resolve(get("PHOTO_MODEL_DIR", defaults.photo_model_dir)),
            photo_max_per_run=int(get("PHOTO_MAX_PER_RUN", "20") or 20),
            orchestrator=get("ORCHESTRATOR", "langgraph").strip().lower() or "langgraph",
            checkpoint_path=_resolve(get("CHECKPOINT_PATH", defaults.checkpoint_path))
            if get("CHECKPOINT_PATH", "x") else "",
            dedupe_threshold=float(get("DEDUPE_THRESHOLD", "0.8") or 0.8),
            auto_publish=_as_bool(get("AUTO_PUBLISH")),
            max_revisions=int(get("MAX_REVISIONS", "2") or 2),
            max_articles_per_run=int(get("MAX_ARTICLES_PER_RUN", "6") or 6),
            admin_password=get("ADMIN_PASSWORD", ""),
            secret_key=get("SECRET_KEY", ""),
            site_url=(get("SITE_URL", defaults.site_url) or defaults.site_url).rstrip("/"),
            contact_email=(get("CONTACT_EMAIL", defaults.contact_email)
                           or defaults.contact_email).strip(),
            request_timeout=float(get("REQUEST_TIMEOUT", "10") or 10),
        )

    @property
    def is_static(self) -> bool:
        """True when the site is published as static pages (review happens in GitHub PRs)."""
        return self.site_mode == "static"

    @property
    def is_production(self) -> bool:
        """True when running as the public site."""
        return self.environment == "production"

    def with_overrides(self, **changes) -> "Settings":
        """Return a copy with some fields replaced (handy in tests and the CLI)."""
        return replace(self, **changes)
