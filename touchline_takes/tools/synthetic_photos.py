"""Procedurally generated *synthetic* match photos for training and testing the photo tagger.

No labelled football photo dataset was reachable from the development sandbox, so the
repo generates simple scenes for four tags. They prove the transfer-learning
pipeline end to end; they are not a substitute for real photos (drop real images
into ``data/photos/<tag>/`` and retrain).

* ``match_action``: close-up of the pitch with players in two kits and a ball.
* ``crowd``: packed stands of supporters, scarves and banners.
* ``stadium``: wide shot with sky, roof, stands and a mostly empty pitch.
* ``press_conference``: a sponsor backdrop, a table, microphones and a speaker.

Scenes share elements on purpose (stadium shots contain crowd and pitch, crowd shots
can show a strip of pitch) so the classes are not trivially separable.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

TAGS = ("match_action", "crowd", "stadium", "press_conference")
KITS = [(200, 30, 40), (240, 240, 240), (30, 60, 170), (250, 200, 30), (20, 20, 20),
        (120, 20, 120), (0, 150, 200), (230, 110, 20)]


def _ri(rng: np.random.Generator, low, high) -> int:
    """``rng.integers(low, high)`` that tolerates an empty range (small image sizes)."""
    low, high = int(low), int(high)
    return int(rng.integers(low, high)) if high > low else low


def _rand_colour(rng: np.random.Generator, base: tuple[int, int, int], spread: int = 25
                 ) -> tuple[int, int, int]:
    return tuple(int(np.clip(c + _ri(rng, -spread, spread + 1), 0, 255)) for c in base)


def _pitch(draw: ImageDraw.ImageDraw, rng, box, stripes: int) -> None:
    x0, y0, x1, y1 = box
    green = (40 + _ri(rng, 0, 30), 120 + _ri(rng, 0, 50), 40 + _ri(rng, 0, 30))
    for i in range(stripes):
        shade = 12 if i % 2 else 0
        top = y0 + (y1 - y0) * i // stripes
        bottom = y0 + (y1 - y0) * (i + 1) // stripes
        draw.rectangle([x0, top, x1, bottom],
                       fill=tuple(int(min(255, c + shade)) for c in green))


def _player(draw, rng, x, y, scale, kit) -> None:
    w, h = 6 * scale, 14 * scale
    draw.rectangle([x - w, y - h, x + w, y], fill=kit)                       # shirt
    draw.rectangle([x - w, y, x + w, y + 0.8 * h], fill=_rand_colour(rng, (30, 30, 30)))
    draw.ellipse([x - 0.7 * w, y - h - 1.4 * w, x + 0.7 * w, y - h], fill=(225, 185, 150))


def _match_action(rng, size: int) -> Image.Image:
    img = Image.new("RGB", (size, size))
    draw = ImageDraw.Draw(img)
    _pitch(draw, rng, (0, 0, size, size), int(_ri(rng, 4, 9)))
    for _ in range(int(_ri(rng, 1, 3))):  # pitch markings
        y = int(_ri(rng, 0, size))
        draw.line([0, y, size, y + int(_ri(rng, -40, 40))], fill=(235, 235, 235), width=3)
    kits = rng.choice(len(KITS), size=2, replace=False)
    for _ in range(int(_ri(rng, 3, 9))):
        scale = rng.uniform(1.6, 3.2) * size / 224
        _player(draw, rng, _ri(rng, 10, size - 10), _ri(rng, size // 3, size - 20),
                scale, _rand_colour(rng, KITS[kits[int(_ri(rng, 0, 2))]]))
    bx, by, r = _ri(rng, 20, size - 20), _ri(rng, size // 2, size - 10), size // 40 + 2
    draw.ellipse([bx - r, by - r, bx + r, by + r], fill=(250, 250, 250), outline=(20, 20, 20))
    return img


def _crowd_block(draw, rng, box, density: float) -> None:
    x0, y0, x1, y1 = box
    draw.rectangle(box, fill=_rand_colour(rng, (60, 60, 70), 20))
    team = KITS[int(_ri(rng, 0, len(KITS)))]
    step = max(4, int(9 / density))
    for y in range(y0 + step // 2, y1, step):
        for x in range(x0 + int(_ri(rng, 0, step)), x1, step):
            colour = _rand_colour(rng, team, 40) if rng.random() < 0.55 else \
                _rand_colour(rng, (200, 170, 140), 40)
            r = step // 2 - 1
            draw.ellipse([x - r, y - r, x + r, y + r], fill=colour)


def _crowd(rng, size: int) -> Image.Image:
    img = Image.new("RGB", (size, size))
    draw = ImageDraw.Draw(img)
    pitch_strip = size - int(_ri(rng, 0, size // 5)) if rng.random() < 0.4 else size
    _crowd_block(draw, rng, (0, 0, size, pitch_strip), rng.uniform(1.0, 1.8))
    if pitch_strip < size:
        _pitch(draw, rng, (0, pitch_strip, size, size), 2)
    for _ in range(int(_ri(rng, 0, 3))):  # banners / scarves
        y = int(_ri(rng, 0, size - 20))
        draw.rectangle([int(_ri(rng, 0, size // 2)), y, int(_ri(rng, size // 2, size)),
                        y + int(_ri(rng, 8, 20))], fill=KITS[int(_ri(rng, 0, len(KITS)))])
    return img


def _stadium(rng, size: int) -> Image.Image:
    img = Image.new("RGB", (size, size))
    draw = ImageDraw.Draw(img)
    sky = int(_ri(rng, size // 10, size // 4))
    draw.rectangle([0, 0, size, sky], fill=_rand_colour(rng, (130, 170, 220), 30))
    roof = sky + int(_ri(rng, 6, 16))
    draw.rectangle([0, sky, size, roof], fill=_rand_colour(rng, (70, 70, 80), 15))
    stands = roof + int(_ri(rng, size // 6, size // 3))
    _crowd_block(draw, rng, (0, roof, size, stands), rng.uniform(2.2, 3.0))
    _pitch(draw, rng, (0, stands, size, size), int(_ri(rng, 6, 12)))
    draw.rectangle([size // 8, stands + 10, size - size // 8, size - 8], outline=(235, 235, 235),
                   width=2)
    draw.line([size // 2, stands + 10, size // 2, size - 8], fill=(235, 235, 235), width=2)
    for _ in range(int(_ri(rng, 0, 6))):  # distant players
        _player(draw, rng, _ri(rng, 20, size - 20), _ri(rng, stands + 20, size - 10),
                0.5 * size / 224, KITS[int(_ri(rng, 0, len(KITS)))])
    for x in (int(_ri(rng, 0, size // 4)), int(_ri(rng, 3 * size // 4, size))):
        draw.rectangle([x, 0, x + 4, roof], fill=(200, 200, 200))  # floodlight pylons
    return img


def _press_conference(rng, size: int) -> Image.Image:
    img = Image.new("RGB", (size, size))
    draw = ImageDraw.Draw(img)
    backdrop = _rand_colour(rng, (235, 235, 235) if rng.random() < 0.6 else (25, 40, 90), 20)
    draw.rectangle([0, 0, size, size], fill=backdrop)
    logo = KITS[int(_ri(rng, 0, len(KITS)))]
    step = int(_ri(rng, size // 7, size // 4))
    for row, y in enumerate(range(4, size, step // 2)):  # step-and-repeat sponsor wall
        for x in range(4 + (row % 2) * step // 2, size, step):
            draw.rectangle([x, y, x + step // 2, y + step // 5], fill=logo)
    cx = int(_ri(rng, size // 3, 2 * size // 3))
    draw.ellipse([cx - size // 12, size // 3, cx + size // 12, size // 3 + size // 6],
                 fill=(225, 185, 150))  # head
    draw.rectangle([cx - size // 6, size // 2, cx + size // 6, int(0.8 * size)],
                   fill=_rand_colour(rng, (30, 30, 40), 20))  # jacket
    table = int(0.72 * size)
    draw.rectangle([0, table, size, size], fill=_rand_colour(rng, (90, 60, 40), 20))
    for _ in range(int(_ri(rng, 2, 6))):  # microphones
        mx = int(_ri(rng, size // 4, 3 * size // 4))
        draw.line([mx, table, cx + int(_ri(rng, -15, 15)), int(0.6 * size)],
                  fill=(20, 20, 20), width=2)
        draw.ellipse([mx - 4, table - 4, mx + 4, table + 4], fill=(20, 20, 20))
    return img


DRAWERS = {"match_action": _match_action, "crowd": _crowd, "stadium": _stadium,
           "press_conference": _press_conference}


def make_photo(tag: str, seed: int, size: int = 224) -> Image.Image:
    """One synthetic photo for ``tag`` (deterministic for a given seed)."""
    rng = np.random.default_rng(seed)
    img = DRAWERS[tag](rng, size)
    img = img.filter(ImageFilter.GaussianBlur(rng.uniform(0.0, 1.2)))
    pixels = np.asarray(img, dtype=np.float32)
    pixels = pixels * rng.uniform(0.75, 1.2) + rng.normal(0, 8, pixels.shape)  # light + noise
    return Image.fromarray(np.clip(pixels, 0, 255).astype(np.uint8))


def write_dataset(out_dir: str | Path, per_tag: int = 60, size: int = 224, seed: int = 7
                  ) -> dict[str, int]:
    """Write ``out_dir/<tag>/<n>.jpg`` for every tag; returns counts."""
    out = Path(out_dir)
    counts = {}
    for t_index, tag in enumerate(TAGS):
        folder = out / tag
        folder.mkdir(parents=True, exist_ok=True)
        for i in range(per_tag):
            make_photo(tag, seed * 100_000 + t_index * 10_000 + i, size).save(
                folder / f"{i:04d}.jpg", quality=85)
        counts[tag] = per_tag
    return counts
