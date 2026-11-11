"""Build the public site as static files (for GitHub Pages or any static host).

Pages are rendered with the same Flask templates as the server version, via Flask's
test client, so both look identical. The build refuses to run if any article file
fails validation (see :mod:`touchline_takes.content`): a bad edit can't go live, and
the previous deployment simply stays up.
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from touchline_takes.config import Settings
from touchline_takes.content import ContentError, load_articles
from touchline_takes.db import Database

WEB_STATIC = Path(__file__).parent / "web" / "static"


@dataclass
class BuildReport:
    """What was written."""

    pages: list[str] = field(default_factory=list)
    articles: int = 0
    fixtures: int = 0


def build_site(content_dir: str | Path, out_dir: str | Path, settings: Settings,
               state_db: str | Path | None = None) -> BuildReport:
    """Render the site into ``out_dir``; raises :class:`ContentError` on invalid content."""
    from touchline_takes.web import create_app  # pylint: disable=import-outside-toplevel

    articles, errors = load_articles(content_dir)
    if errors:
        details = "\n".join(f"  {name}: {'; '.join(problems)}"
                            for name, problems in errors.items())
        raise ContentError(f"{len(errors)} article file(s) failed validation:\n{details}")
    out = Path(out_dir)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    report = BuildReport(articles=len(articles))
    with tempfile.TemporaryDirectory() as tmp:
        db = Database(str(Path(tmp) / "site.db"))
        for record in articles:
            db.insert_article_record(record)
        if state_db and Path(state_db).exists():
            report.fixtures = db.copy_fixtures_from(Database(str(state_db)))
        site_settings = settings.with_overrides(site_mode="static",
                                                database_path=str(Path(tmp) / "site.db"))
        client = create_app(site_settings, db=db, run_preflight=False).test_client()
        routes = {"index.html": "/", "archive/index.html": "/archive",
                  "feed.xml": "/feed.xml", "sitemap.xml": "/sitemap.xml",
                  "robots.txt": "/robots.txt"}
        routes.update({f"article/{a['slug']}/index.html": f"/article/{a['slug']}"
                       for a in articles})
        for target, route in routes.items():
            response = client.get(route)
            if response.status_code != 200:
                raise RuntimeError(f"{route} rendered HTTP {response.status_code}")
            _write(out / target, response.get_data())
            report.pages.append(target)
        _write(out / "404.html", client.get("/__not_found__").get_data())
        db.close()
    shutil.copytree(WEB_STATIC, out / "static")
    host = urlparse(settings.site_url).hostname
    if host and host not in ("localhost", "127.0.0.1"):
        (out / "CNAME").write_text(host + "\n", encoding="utf-8")  # GitHub Pages domain
    (out / ".nojekyll").write_text("", encoding="utf-8")
    return report


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
