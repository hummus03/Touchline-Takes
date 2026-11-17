"""Draw the 1200x630 link-preview image: ``python scripts/make_share_image.py``.

Writes ``touchline_takes/web/static/og-image.png`` in the site's look: sand and maroon,
the T-and-ball logo, the Yellowtail wordmark with its gold touchline, the home-page
headline and the geometric pitch shapes. Uses the site's own fonts.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "touchline_takes" / "web" / "static"
OUT = STATIC / "og-image.png"
CARD, MAROON, GOLD, GOLD_TEXT = (250, 244, 232), (110, 26, 42), (216, 162, 59), (163, 104, 15)
TEAL, INK, MUTED, FAINT = (31, 90, 99), (44, 26, 23), (133, 98, 90), (205, 170, 172)
WIDTH, HEIGHT, SS = 1200, 630, 2  # drawn at 2x, then scaled down for smooth edges


def sans(size: int, weight: int) -> ImageFont.FreeTypeFont:
    """DM Sans (a variable font) at a weight."""
    font = ImageFont.truetype(str(STATIC / "fonts" / "dm-sans-latin.woff2"), size * SS)
    axes = {a["name"]: a for a in font.get_variation_axes()}
    values = [weight if name in (b"Weight", "Weight") else axis["default"]
              for name, axis in axes.items()]
    font.set_variation_by_axes(values)
    return font


def script(size: int) -> ImageFont.FreeTypeFont:
    """Yellowtail, the brush script of the wordmark."""
    return ImageFont.truetype(str(STATIC / "fonts" / "yellowtail-latin.woff2"), size * SS)


def logo_icon(draw: ImageDraw.ImageDraw, x: float, y: float, size: float) -> None:
    """The T-and-ball icon (same shapes as favicon.svg, on a 64-unit grid)."""
    def box(x0, y0, x1, y1):
        k = size / 64 * SS
        return [(x * SS + x0 * k), (y * SS + y0 * k), (x * SS + x1 * k), (y * SS + y1 * k)]
    k = size / 64 * SS
    draw.rounded_rectangle(box(1, 1, 63, 63), radius=12 * k, fill=CARD, outline=MAROON,
                           width=round(2 * k))
    draw.rectangle(box(12, 9.5, 52, 19.5), fill=MAROON)
    draw.rectangle(box(27, 9.5, 37, 47.5), fill=MAROON)
    draw.ellipse(box(40, 35.5, 52, 47.5), fill=GOLD)
    draw.rounded_rectangle(box(9, 51.5, 55, 55.5), radius=2 * k, fill=FAINT)


def pitch_shapes(draw: ImageDraw.ImageDraw, ox: float, oy: float, scale: float) -> None:
    """The home page's geometric picture (from its 560x330 SVG)."""
    k = scale * SS
    def pt(x, y):
        return ox * SS + x * k, oy * SS + y * k
    def disc(cx, cy, r):
        (x0, y0), (x1, y1) = pt(cx - r, cy - r), pt(cx + r, cy + r)
        return [x0, y0, x1, y1]
    draw.pieslice(disc(150, 170, 150), 180, 270, fill=MAROON)
    draw.pieslice(disc(150, 170, 150), 90, 180, fill=TEAL)
    draw.ellipse(disc(150, 170, 52), fill=CARD, outline=INK, width=round(10 * k))
    draw.pieslice(disc(150, 170, 47), 270, 360, fill=GOLD)
    for x in range(250, 431, 18):
        draw.line([pt(x, 20), pt(x, 200)], fill=INK, width=round(2 * k))
    for y in (80, 140):
        draw.line([pt(250, y), pt(430, y)], fill=INK, width=round(2 * k))
    draw.pieslice(disc(560, 200, 130), 180, 270, fill=GOLD)
    draw.line([pt(548, 112), pt(548, 200)], fill=MAROON, width=round(5 * k))
    draw.polygon([pt(546, 114), pt(506, 128), pt(546, 142)], fill=MAROON)
    for cx, cy, r, colour in ((215, 60, 7, TEAL), (232, 96, 4, MAROON), (210, 250, 5, GOLD)):
        draw.ellipse(disc(cx, cy, r), fill=colour)


def main() -> int:
    """Render and save the image."""
    img = Image.new("RGB", (WIDTH * SS, HEIGHT * SS), CARD)
    draw = ImageDraw.Draw(img)
    left = 70
    # Logo: icon, script wordmark, gold touchline under it.
    logo_icon(draw, left, 70, 84)
    mark = script(78)
    draw.text(((left + 108) * SS, 112 * SS), "Touchline Takes", font=mark, fill=MAROON,
              anchor="lm")
    wide = draw.textlength("Touchline Takes", font=mark) / SS
    draw.line([((left + 106) * SS, 166 * SS), ((left + 112 + wide) * SS, 160 * SS)],
              fill=GOLD, width=5 * SS)
    # Headline, with "line by line." in script like the home page.
    head = sans(64, 800)
    draw.text((left * SS, 300 * SS), "Football takes,", font=head, fill=MAROON, anchor="ls")
    draw.text((left * SS, 380 * SS), "checked", font=head, fill=MAROON, anchor="ls")
    after = left + draw.textlength("checked ", font=head) / SS
    draw.text((after * SS, 384 * SS), "line by line.", font=script(76), fill=GOLD_TEXT,
              anchor="ls")
    body = sans(28, 400)
    draw.text((left * SS, 450 * SS), "AI football news and opinion, every claim checked",
              font=body, fill=INK, anchor="ls")
    draw.text((left * SS, 488 * SS), "against its source and approved by a person.",
              font=body, fill=INK, anchor="ls")
    draw.text((left * SS, 560 * SS), "touchlinetakes.com", font=sans(28, 700), fill=MAROON,
              anchor="ls")
    pitch_shapes(draw, 765, 248, 0.73)
    img = img.resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, optimize=True)
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
