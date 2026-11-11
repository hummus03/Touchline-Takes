"""A thin SQLite repository for stories, drafts, articles, fixtures, logs and the LLM cache."""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable

from touchline_takes.state import Draft, LogEntry, Story, utcnow_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS stories (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    url TEXT UNIQUE,
    source TEXT,
    published TEXT,
    body TEXT DEFAULT '',
    league TEXT,
    teams TEXT DEFAULT '[]',
    topic TEXT,
    sentiment TEXT,
    sentiment_score REAL DEFAULT 0,
    emotion TEXT,
    classified INTEGER DEFAULT 0,
    used INTEGER DEFAULT 0,
    ingested_at TEXT,
    image_url TEXT DEFAULT '',
    image_tags TEXT DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS drafts (
    id TEXT PRIMARY KEY,
    run_id TEXT,
    status TEXT,
    data TEXT NOT NULL,
    created_at TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS articles (
    slug TEXT PRIMARY KEY,
    draft_id TEXT,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    article_type TEXT,
    league TEXT,
    teams TEXT DEFAULT '[]',
    sources TEXT DEFAULT '[]',
    evidence TEXT DEFAULT '[]',
    published_at TEXT
);
CREATE TABLE IF NOT EXISTS fixtures (
    id TEXT PRIMARY KEY,
    date TEXT,
    league TEXT,
    home TEXT,
    away TEXT,
    source TEXT
);
CREATE TABLE IF NOT EXISTS predictions (
    fixture_id TEXT PRIMARY KEY,
    home_win REAL,
    draw REAL,
    away_win REAL,
    predicted TEXT,
    model_version TEXT,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS agent_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT,
    ts TEXT,
    agent TEXT,
    story_id TEXT,
    action TEXT,
    detail TEXT
);
CREATE TABLE IF NOT EXISTS rejections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT,
    draft_id TEXT,
    revision INTEGER,
    agent TEXT,
    reasons TEXT,
    ts TEXT
);
CREATE TABLE IF NOT EXISTS llm_cache (
    key TEXT PRIMARY KEY,
    provider TEXT,
    model TEXT,
    response TEXT,
    tokens_in INTEGER,
    tokens_out INTEGER,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    started_at TEXT,
    finished_at TEXT,
    summary TEXT
);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


def _story_from_row(row: sqlite3.Row) -> Story:
    """Convert a ``stories`` row into a :class:`Story`."""
    return Story(
        id=row["id"], title=row["title"], summary=row["summary"], url=row["url"],
        source=row["source"], published=row["published"], body=row["body"] or "",
        league=row["league"], teams=json.loads(row["teams"] or "[]"), topic=row["topic"],
        sentiment=row["sentiment"], sentiment_score=row["sentiment_score"] or 0.0,
        emotion=row["emotion"], image_url=row["image_url"] or "",
        image_tags=json.loads(row["image_tags"] or "[]"),
    )


class Database:  # pylint: disable=too-many-public-methods  # one repository for the newsroom
    """SQLite-backed repository. Safe to share across Flask request threads."""

    def __init__(self, path: str) -> None:
        self.path = path
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False, timeout=10)
        self._conn.row_factory = sqlite3.Row
        if path != ":memory:":
            # WAL lets the web process read while the scheduler writes.
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA busy_timeout=10000")
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._migrate()
            self._conn.commit()

    def _migrate(self) -> None:
        """Add columns introduced after a database was first created."""
        columns = {row[1] for row in self._conn.execute("PRAGMA table_info(stories)")}
        for name, ddl in (("image_url", "TEXT DEFAULT ''"), ("image_tags", "TEXT DEFAULT '[]'")):
            if name not in columns:
                self._conn.execute(f"ALTER TABLE stories ADD COLUMN {name} {ddl}")

    # -- helpers ----------------------------------------------------------
    def _execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.execute(sql, tuple(params))
            self._conn.commit()
            return cur

    def _query(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self._conn.execute(sql, tuple(params)).fetchall())

    def close(self) -> None:
        """Close the connection."""
        with self._lock:
            self._conn.close()

    # -- stories ----------------------------------------------------------
    def story_url_exists(self, url: str) -> bool:
        """True if a story with ``url`` is already stored."""
        return bool(self._query("SELECT 1 FROM stories WHERE url = ?", (url,)))

    def insert_story(self, story: Story) -> bool:
        """Insert a story; returns False if it already existed."""
        cur = self._execute(
            "INSERT OR IGNORE INTO stories (id, title, summary, url, source, published, body,"
            " ingested_at, image_url) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (story.id, story.title, story.summary, story.url, story.source, story.published,
             story.body, utcnow_iso(), story.image_url),
        )
        return cur.rowcount > 0

    def update_classification(self, story: Story) -> None:
        """Persist the classifier's tags for ``story``."""
        self._execute(
            "UPDATE stories SET league = ?, teams = ?, topic = ?, sentiment = ?,"
            " sentiment_score = ?, emotion = ?, classified = 1 WHERE id = ?",
            (story.league, json.dumps(story.teams), story.topic, story.sentiment,
             story.sentiment_score, story.emotion, story.id),
        )

    def update_image_tags(self, story_id: str, tags: list[dict[str, Any]]) -> None:
        """Persist the photo tagger's tags for a story."""
        self._execute("UPDATE stories SET image_tags = ? WHERE id = ?",
                      (json.dumps(tags), story_id))

    def untagged_photo_stories(self, limit: int = 50) -> list[Story]:
        """Stories with a photo that has not been tagged yet."""
        rows = self._query(
            "SELECT * FROM stories WHERE image_url != '' AND (image_tags IS NULL OR"
            " image_tags = '[]') ORDER BY ingested_at DESC LIMIT ?", (limit,))
        return [_story_from_row(r) for r in rows]

    def get_story(self, story_id: str) -> Story | None:
        """Fetch one story by id."""
        rows = self._query("SELECT * FROM stories WHERE id = ?", (story_id,))
        return _story_from_row(rows[0]) if rows else None

    def recent_stories(self, limit: int = 200) -> list[Story]:
        """Most recently ingested stories."""
        rows = self._query(
            "SELECT * FROM stories ORDER BY ingested_at DESC, published DESC LIMIT ?", (limit,))
        return [_story_from_row(r) for r in rows]

    def count_stories(self) -> int:
        """Number of stored stories."""
        return int(self._query("SELECT COUNT(*) AS n FROM stories")[0]["n"])

    def all_stories(self) -> list[Story]:
        """Every stored story."""
        return [_story_from_row(r) for r in self._query("SELECT * FROM stories")]

    def unclassified_stories(self) -> list[Story]:
        """Stories the classifier has not tagged yet."""
        rows = self._query("SELECT * FROM stories WHERE classified = 0")
        return [_story_from_row(r) for r in rows]

    def unused_stories(self, limit: int = 50) -> list[Story]:
        """Classified stories not yet turned into an article."""
        rows = self._query(
            "SELECT * FROM stories WHERE classified = 1 AND used = 0"
            " ORDER BY published DESC LIMIT ?", (limit,))
        return [_story_from_row(r) for r in rows]

    def reset_unused_classification(self) -> int:
        """Queue every story not yet written up for classification again."""
        n = int(self._query("SELECT COUNT(*) AS n FROM stories WHERE classified = 1 AND used = 0"
                            )[0]["n"])
        self._execute("UPDATE stories SET classified = 0 WHERE used = 0")
        return n

    def get_meta(self, key: str) -> str | None:
        """A stored setting (e.g. the classifier rules version), or None."""
        rows = self._query("SELECT value FROM meta WHERE key = ?", (key,))
        return rows[0]["value"] if rows else None

    def set_meta(self, key: str, value: str) -> None:
        """Store a setting."""
        self._execute("INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) "
                      "DO UPDATE SET value = excluded.value", (key, value))

    def mark_used(self, story_ids: Iterable[str]) -> None:
        """Flag stories as already written up."""
        for story_id in story_ids:
            self._execute("UPDATE stories SET used = 1 WHERE id = ?", (story_id,))

    # -- drafts -----------------------------------------------------------
    def save_draft(self, draft: Draft, run_id: str = "") -> None:
        """Insert or update a draft."""
        now = utcnow_iso()
        self._execute(
            "INSERT INTO drafts (id, run_id, status, data, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET status = excluded.status,"
            " data = excluded.data, updated_at = excluded.updated_at",
            (draft.id, run_id, draft.status, json.dumps(draft.to_dict()), now, now),
        )

    def get_draft(self, draft_id: str) -> Draft | None:
        """Fetch a draft by id."""
        rows = self._query("SELECT data FROM drafts WHERE id = ?", (draft_id,))
        return Draft.from_dict(json.loads(rows[0]["data"])) if rows else None

    def draft_run_id(self, draft_id: str) -> str | None:
        """The run that last saved a draft (its LangGraph thread id)."""
        rows = self._query("SELECT run_id FROM drafts WHERE id = ?", (draft_id,))
        return rows[0]["run_id"] if rows else None

    def drafts_by_status(self, *statuses: str) -> list[Draft]:
        """Drafts in any of ``statuses`` (newest first)."""
        marks = ",".join("?" for _ in statuses)
        rows = self._query(
            f"SELECT data FROM drafts WHERE status IN ({marks}) ORDER BY updated_at DESC",
            statuses)
        return [Draft.from_dict(json.loads(r["data"])) for r in rows]

    # -- articles ---------------------------------------------------------
    def insert_article(self, slug: str, draft: Draft) -> None:
        """Publish ``draft`` under ``slug``."""
        self._execute(
            "INSERT OR REPLACE INTO articles (slug, draft_id, title, body, article_type, league,"
            " teams, sources, evidence, published_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (slug, draft.id, draft.title, draft.body, draft.article_type, draft.league,
             json.dumps(draft.teams), json.dumps(draft.sources),
             json.dumps([e.to_dict() for e in draft.evidence]), utcnow_iso()),
        )

    def insert_article_record(self, record: dict[str, Any]) -> None:
        """Insert a published article from its content-file representation."""
        self._execute(
            "INSERT OR REPLACE INTO articles (slug, draft_id, title, body, article_type, league,"
            " teams, sources, evidence, published_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (record["slug"], record.get("draft_id", ""), record["title"], record["body"],
             record.get("article_type", ""), record.get("league"),
             json.dumps(record.get("teams", [])), json.dumps(record.get("sources", [])),
             json.dumps(record.get("evidence", [])), record.get("published_at", "")))

    def copy_fixtures_from(self, other: "Database") -> int:
        """Copy fixtures and predictions from another database (for static builds)."""
        rows = other.fixtures_with_predictions(100)
        for row in rows:
            self.upsert_fixture(row)
            if row.get("home_win") is not None:
                self.upsert_prediction(row["id"], {"H": row["home_win"], "D": row["draw"],
                                                   "A": row["away_win"]},
                                       row["predicted"], row["model_version"] or "")
        return len(rows)

    def prune(self, days: int = 30) -> None:
        """Drop old log lines and cached LLM replies so the state file stays small."""
        cutoff = f"-{int(days)} days"
        self._execute("DELETE FROM agent_log WHERE ts < datetime('now', ?)", (cutoff,))
        self._execute("DELETE FROM llm_cache WHERE created_at < datetime('now', ?)", (cutoff,))
        self._execute("DELETE FROM rejections WHERE ts < datetime('now', ?)", (cutoff,))
        with self._lock:
            self._conn.execute("VACUUM")

    def slug_exists(self, slug: str) -> bool:
        """True if an article already uses ``slug``."""
        return bool(self._query("SELECT 1 FROM articles WHERE slug = ?", (slug,)))

    def list_articles(self, limit: int = 30) -> list[dict[str, Any]]:
        """Published articles, newest first."""
        rows = self._query(
            "SELECT * FROM articles ORDER BY published_at DESC, rowid DESC LIMIT ?", (limit,))
        return [self._article_dict(r) for r in rows]

    def get_article(self, slug: str) -> dict[str, Any] | None:
        """One published article."""
        rows = self._query("SELECT * FROM articles WHERE slug = ?", (slug,))
        return self._article_dict(rows[0]) if rows else None

    @staticmethod
    def _article_dict(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        for key in ("teams", "sources", "evidence"):
            data[key] = json.loads(data.get(key) or "[]")
        return data

    # -- fixtures & predictions -------------------------------------------
    def upsert_fixture(self, fixture: dict[str, Any]) -> None:
        """Insert or replace an upcoming fixture."""
        self._execute(
            "INSERT OR REPLACE INTO fixtures (id, date, league, home, away, source)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (fixture["id"], fixture["date"], fixture.get("league", ""), fixture["home"],
             fixture["away"], fixture.get("source", "")),
        )

    def upsert_prediction(self, fixture_id: str, probs: dict[str, float], predicted: str,
                          model_version: str) -> None:
        """Store the Analyst's prediction for a fixture."""
        self._execute(
            "INSERT OR REPLACE INTO predictions (fixture_id, home_win, draw, away_win, predicted,"
            " model_version, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (fixture_id, probs["H"], probs["D"], probs["A"], predicted, model_version,
             utcnow_iso()),
        )

    def fixtures_with_predictions(self, limit: int = 20) -> list[dict[str, Any]]:
        """Upcoming fixtures joined with predictions."""
        rows = self._query(
            "SELECT f.*, p.home_win, p.draw, p.away_win, p.predicted, p.model_version"
            " FROM fixtures f LEFT JOIN predictions p ON p.fixture_id = f.id"
            " ORDER BY f.date ASC LIMIT ?", (limit,))
        return [dict(r) for r in rows]

    # -- logs ---------------------------------------------------------------
    def write_logs(self, run_id: str, entries: Iterable[LogEntry]) -> None:
        """Persist agent log entries for a run."""
        for e in entries:
            self._execute(
                "INSERT INTO agent_log (run_id, ts, agent, story_id, action, detail)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (run_id, e.ts, e.agent, e.story_id, e.action, e.detail))

    def recent_logs(self, limit: int = 100) -> list[dict[str, Any]]:
        """Most recent agent log lines."""
        rows = self._query("SELECT * FROM agent_log ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]

    def log_rejection(self, run_id: str, draft: Draft, agent: str, reasons: list[str]) -> None:
        """Record why a draft was sent back or rejected."""
        self._execute(
            "INSERT INTO rejections (run_id, draft_id, revision, agent, reasons, ts)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, draft.id, draft.revision, agent, json.dumps(reasons), utcnow_iso()))

    def recent_rejections(self, limit: int = 50) -> list[dict[str, Any]]:
        """Most recent rejection records."""
        rows = self._query("SELECT * FROM rejections ORDER BY id DESC LIMIT ?", (limit,))
        out = []
        for r in rows:
            item = dict(r)
            item["reasons"] = json.loads(item["reasons"] or "[]")
            out.append(item)
        return out

    def record_run(self, run_id: str, started_at: str, summary: dict[str, Any]) -> None:
        """Store a run summary."""
        self._execute(
            "INSERT OR REPLACE INTO runs (run_id, started_at, finished_at, summary)"
            " VALUES (?, ?, ?, ?)", (run_id, started_at, utcnow_iso(), json.dumps(summary)))

    def recent_runs(self, limit: int = 10) -> list[dict[str, Any]]:
        """Most recent run summaries."""
        rows = self._query("SELECT * FROM runs ORDER BY finished_at DESC LIMIT ?", (limit,))
        return [{**dict(r), "summary": json.loads(r["summary"] or "{}")} for r in rows]

    # -- LLM cache ------------------------------------------------------------
    def cache_get(self, key: str) -> dict[str, Any] | None:
        """Look up a cached LLM response."""
        rows = self._query("SELECT * FROM llm_cache WHERE key = ?", (key,))
        return dict(rows[0]) if rows else None

    def cache_put(self, key: str, provider: str, model: str, response: str,
                  tokens_in: int, tokens_out: int) -> None:
        """Store an LLM response."""
        self._execute(
            "INSERT OR REPLACE INTO llm_cache (key, provider, model, response, tokens_in,"
            " tokens_out, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (key, provider, model, response, tokens_in, tokens_out, utcnow_iso()))
