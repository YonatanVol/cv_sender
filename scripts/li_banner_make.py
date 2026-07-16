"""Generate a clean LinkedIn banner (1584x396) as a PNG.

Usage: python scripts/li_banner_make.py <out_png> "Name" "Line2" "Line3" "Line4"

Dark navy->teal gradient, left-aligned text, faint concentric "radar" arcs on
the right. Uses a system TTF if available.
"""
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

W, H = 1584, 396


def font(size, bold=False):
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial.ttf",
        "/System/Library/Fonts/SFNS.ttf",
    ]
    for c in candidates:
        if Path(c).exists():
            try:
                return ImageFont.truetype(c, size)
            except Exception:
                continue
    return ImageFont.load_default()


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def main(out, name, l2, l3, l4):
    top, bottom = (10, 26, 54), (17, 94, 110)   # navy -> teal
    img = Image.new("RGB", (W, H), top)
    d = ImageDraw.Draw(img)
    # diagonal-ish gradient
    for y in range(H):
        d.line([(0, y), (W, y)], fill=lerp(top, bottom, y / H))
    # faint concentric radar arcs on the right (nod to Air Defense)
    cx, cy = 1360, 198
    for r in range(60, 520, 60):
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(255, 255, 255, 20), width=2)
    # radar sweep lines
    d.line([(cx, cy), (cx + 380, cy - 260)], fill=(127, 224, 212), width=2)
    d.line([(cx, cy), (cx + 380, cy + 60)], fill=(90, 160, 180), width=1)
    # overlay to keep text readable on the left
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(ov).rectangle([0, 0, 900, H], fill=(8, 20, 40, 120))
    img = Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")
    d = ImageDraw.Draw(img)
    x = 92
    d.text((x, 96), name, font=font(88, bold=True), fill=(255, 255, 255))
    d.text((x, 200), l2, font=font(34), fill=(224, 232, 240))
    d.text((x, 246), l3, font=font(30), fill=(127, 224, 212))
    d.text((x, 290), l4, font=font(26), fill=(176, 196, 216))
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG")
    print(f"saved {out} ({img.size[0]}x{img.size[1]})")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5])
