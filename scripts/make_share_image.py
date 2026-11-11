"""Draw the 1200x630 link-preview image: ``python scripts/make_share_image.py``.

Writes ``touchline_takes/web/static/og-image.png`` in the site's colours (mown-pitch
stripes, chalk touchline, yellow "TAKES").
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "touchline_takes" / "web" / "static" / "og-image.png"
PITCH, PITCH_DARK, CHALK, YELLOW = (11, 110, 58), (6, 77, 40), (255, 255, 255), (242, 193, 78)
FONT_DIRS = ["/usr/share/fonts/truetype/dejavu", "/Library/Fonts", "C:/Windows/Fonts"]


def font(name: str, size: int) -> ImageFont.ImageFont:
    """A system TrueType font, or Pillow's default if none is found."""
    for folder in FONT_DIRS:
        path = Path(folder) / name
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default(size=size)


def main() -> int:
    """Render and save the image."""
    width, height = 1200, 630
    img = Image.new("RGB", (width, height), PITCH)
    draw = ImageDraw.Draw(img)
    for x in range(0, width, 160):  # mown stripes
        draw.rectangle([x + 80, 0, x + 159, height], fill=PITCH_DARK)
    draw.rectangle([0, height - 70, width, height - 62], fill=CHALK)  # touchline
    draw.ellipse([90, 205, 190, 305], outline=CHALK, width=10)        # centre-spot logo
    draw.ellipse([125, 240, 155, 270], fill=YELLOW)
    size = 96
    bold = font("DejaVuSans-Bold.ttf", size)
    while 225 + draw.textlength("TOUCHLINE TAKES", font=bold) > width - 70 and size > 40:
        size -= 2  # shrink the title until it fits with a right margin
        bold = font("DejaVuSans-Bold.ttf", size)
    top = 255 - size // 2 - 8
    draw.text((225, top), "TOUCHLINE", font=bold, fill=CHALK)
    left = 225 + draw.textlength("TOUCHLINE ", font=bold)
    draw.text((left, top), "TAKES", font=bold, fill=YELLOW)
    draw.text((228, 335), "AI-powered football takes,", font=font("DejaVuSans.ttf", 44),
              fill=CHALK)
    draw.text((228, 392), "straight from the touchline.", font=font("DejaVuSans.ttf", 44),
              fill=CHALK)
    draw.text((228, 492), "touchlinetakes.com", font=font("DejaVuSans-Bold.ttf", 34),
              fill=YELLOW)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, optimize=True)
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
