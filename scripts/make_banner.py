"""Generate a LinkedIn banner (1584x396) PNG — works for any person.

Usage:
  python scripts/make_banner.py <out.png> "<Name>" "<Title>" "<Stack line>" "<Tagline>"

Dark navy -> teal gradient, subtle dot grid, left-aligned text block.
LinkedIn crops the banner on small screens, so text stays inside a safe margin.
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1584, 396
# Text is kept left of this so the profile photo (bottom-left on desktop,
# overlapping ~x<340) and right-side crop never cover it.
PAD_X, TOP = 96, 62
# The profile photo overlaps the banner's lower-left on desktop, so the text
# block stays in the upper band; the dot texture starts right of the text.
DOTS_FROM = 1040

FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial.ttf",
]


def font(size, bold=False):
    order = FONT_CANDIDATES if bold else FONT_CANDIDATES[1:] + FONT_CANDIDATES[:1]
    for path in order:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def lerp(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def main(out, name, title, stack, tagline):
    left, right = (13, 20, 33), (17, 74, 90)      # navy -> teal
    img = Image.new("RGB", (W, H), left)
    d = ImageDraw.Draw(img)

    # Diagonal-ish gradient (per-column blend, slight vertical shift).
    for x in range(W):
        t = x / (W - 1)
        d.line([(x, 0), (x, H)], fill=lerp(left, right, t ** 0.85))

    # Subtle dot grid on the right half for a technical texture.
    for gx in range(DOTS_FROM, W, 26):
        for gy in range(40, H - 30, 26):
            t = (gx - DOTS_FROM) / max(1, W - DOTS_FROM)
            a = int(26 + 44 * t)
            d.ellipse([gx, gy, gx + 2, gy + 2], fill=(120 + a, 190, 205))

    # Accent bar
    d.rectangle([PAD_X, TOP + 4, PAD_X + 6, TOP + 128], fill=(80, 220, 210))

    tx = PAD_X + 30
    d.text((tx, TOP), name, font=font(66, bold=True), fill=(255, 255, 255))
    d.text((tx, TOP + 82), title, font=font(34), fill=(120, 232, 220))
    d.text((tx, TOP + 146), stack, font=font(25), fill=(206, 220, 232))
    d.text((tx, TOP + 196), tagline, font=font(23), fill=(150, 176, 196))

    Path(out).parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG", optimize=True)
    print(f"OK wrote {out} ({W}x{H})")


if __name__ == "__main__":
    if len(sys.argv) < 6:
        print('usage: make_banner.py <out.png> "<Name>" "<Title>" "<Stack>" "<Tagline>"')
        raise SystemExit(2)
    main(*sys.argv[1:6])
