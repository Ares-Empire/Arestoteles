"""Build the Arestoteles bot avatar from a reference marble bust of Aristotle.

Takes the source bust image, removes its background, places it on pure black,
and tunes it to a light-grey/white marble tone with a soft 3D light from the
upper-left (matches the Aresium dark aesthetic).

Run:    python scripts/make_bust.py [source.png]
Output: assets/arestoteles_bust.png  (1024x1024 square -> Telegram avatar)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter, ImageOps
from rembg import remove

ASSETS = Path(__file__).resolve().parent.parent / "assets"
SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else ASSETS / "bust_source.png"
OUT = ASSETS / "arestoteles_bust.png"
S = 1024


def cutout(src: Path) -> Image.Image:
    """Background-removed RGBA bust, tightly cropped to its alpha bbox."""
    img = Image.open(src).convert("RGBA")
    cut = remove(img, post_process_mask=True)          # U2Net segmentation
    a = np.asarray(cut.split()[-1])
    ys, xs = np.where(a > 16)
    box = (xs.min(), ys.min(), xs.max() + 1, ys.max() + 1)
    return cut.crop(box)


def tune_marble(rgba: Image.Image) -> Image.Image:
    """Light-grey/white marble tone + soft upper-left 3D light, alpha kept."""
    rgb = rgba.convert("RGB")
    r, g, b = (np.asarray(rgb, np.float32)[..., i] for i in range(3))
    lum = 0.299 * r + 0.587 * g + 0.114 * b            # desaturate -> stone grey

    # gentle contrast/level so it sits as light grey -> white, not washed out
    lum = np.clip((lum - 18) * 1.18 + 12, 0, 255)
    lum = 255 * (lum / 255) ** 0.86                    # lift midtones toward white

    # directional 3D light: brighten upper-left, deepen lower-right
    h, w = lum.shape
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    grad = (1 - xx / w) * 0.10 + (1 - yy / h) * 0.14
    lum = np.clip(lum * (1 + grad - 0.10), 0, 255)

    grey = lum.astype(np.uint8)
    out = Image.merge("RGB", [Image.fromarray(grey)] * 3).convert("RGBA")
    out.putalpha(rgba.split()[-1])
    return out


def main() -> None:
    bust = tune_marble(cutout(SRC))

    # fit onto a square black canvas with margin (room for Telegram's circle crop)
    margin = 0.86
    bw, bh = bust.size
    scale = (S * margin) / max(bw, bh)
    bust = bust.resize((max(1, int(bw * scale)), max(1, int(bh * scale))), Image.LANCZOS)

    canvas = Image.new("RGBA", (S, S), (0, 0, 0, 255))
    ox = (S - bust.width) // 2
    oy = (S - bust.height) // 2
    # soft contact shadow under the bust so it doesn't float flatly
    sh = Image.new("L", (S, S), 0)
    a = bust.split()[-1].point(lambda v: 90 if v > 24 else 0)
    sh.paste(a, (ox, oy + 26))
    sh = sh.filter(ImageFilter.GaussianBlur(22))
    canvas = Image.composite(Image.new("RGBA", (S, S), (0, 0, 0, 255)), canvas, sh)

    canvas.alpha_composite(bust, (ox, oy))
    canvas.convert("RGB").save(OUT)
    print("wrote", OUT, "from", SRC.name)


if __name__ == "__main__":
    main()
