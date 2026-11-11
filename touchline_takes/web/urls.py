"""Page addresses: canonical URLs and club/league slugs."""

from __future__ import annotations

import re
import unicodedata


def canonical_url(site_url: str, path: str) -> str:
    """Absolute URL of a page as the static site serves it (directories end in '/')."""
    if path != "/" and not path.rsplit("/", 1)[-1].count("."):  # not feed.xml, robots.txt
        path = path.rstrip("/") + "/"
    return f"{site_url}{path}"


def slugify(name: str) -> str:
    """URL slug for a club or league: 'Paris Saint-Germain' -> 'paris-saint-germain'."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")
