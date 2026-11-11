"""Regenerate the synthetic photos attached to the bundled sample feeds.

The sample RSS items reference these files via ``<media:thumbnail url="sample_photos/...">``
so the offline demo exercises the photo tagger. They are synthetic, like the training set.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from touchline_takes.tools.synthetic_photos import make_photo  # pylint: disable=wrong-import-position

ROOT = Path(__file__).resolve().parent.parent
PHOTOS = {"arsenal-beat-chelsea": "match_action", "arsenal-chelsea-report": "match_action",
          "liverpool-everton-draw": "stadium", "city-thrash-wolves": "match_action",
          "spurs-boss-sacked": "press_conference", "newcastle-amari-talks": "press_conference",
          "brighton-var-row": "crowd", "celtic-rangers-derby": "crowd",
          "united-fulham-preview": "press_conference"}


def main() -> None:
    """Write ``data/sample_photos/<slug>.jpg`` (seeds disjoint from the training set)."""
    out = ROOT / "data" / "sample_photos"
    out.mkdir(parents=True, exist_ok=True)
    for i, (slug, tag) in enumerate(PHOTOS.items()):
        make_photo(tag, 9_000_000 + i).save(out / f"{slug}.jpg", quality=80)
    print(f"wrote {len(PHOTOS)} sample photos to {out}")


if __name__ == "__main__":
    main()
