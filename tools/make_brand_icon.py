#!/usr/bin/env python3
"""Generate the HACS brand assets for this integration.

HACS validation requires brand assets. It looks in the repository at
custom_components/<domain>/brand/ FIRST and only falls back to the
home-assistant/brands repo if they are absent, so shipping them here avoids
needing a PR against brands just to get a green check.

The mark is deliberately generic - a panel and a sun. It is NOT EasyCharging's
logo: this is an unofficial integration and using their actual trademark would
be wrong, quite apart from the licensing.

Sizes follow the Home Assistant brands spec: icon.png 256x256 and icon@2x.png
512x512, square, transparent background.
"""
from PIL import Image, ImageDraw

BLUE = (21, 101, 192, 255)      # panel body
DARK = (13, 60, 117, 255)       # panel edge / grid lines
SUN = (255, 193, 7, 255)        # sun


def draw(size: int) -> Image.Image:
    # Supersample, then downscale, so the diagonals come out smooth.
    s = size * 4
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    u = s / 100.0  # 1 unit = 1% of the canvas

    # Sun, upper right, drawn first so the panel overlaps it.
    cx, cy, r = 68 * u, 30 * u, 15 * u
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=SUN)
    for i in range(8):
        import math
        a = math.radians(i * 45)
        x0, y0 = cx + math.cos(a) * r * 1.35, cy + math.sin(a) * r * 1.35
        x1, y1 = cx + math.cos(a) * r * 1.85, cy + math.sin(a) * r * 1.85
        d.line([x0, y0, x1, y1], fill=SUN, width=int(3.2 * u))

    # Panel: a trapezium, wider at the bottom, so it reads as tilted.
    top_y, bot_y = 52 * u, 88 * u
    panel = [(26 * u, top_y), (78 * u, top_y), (90 * u, bot_y), (14 * u, bot_y)]
    d.polygon(panel, fill=BLUE)

    # Grid: two horizontal rows and three verticals, following the taper.
    def lerp(a, b, t):
        return a + (b - a) * t

    for t in (0.34, 0.67):
        y = lerp(top_y, bot_y, t)
        xl = lerp(26 * u, 14 * u, t)
        xr = lerp(78 * u, 90 * u, t)
        d.line([xl, y, xr, y], fill=DARK, width=int(2.4 * u))
    for f in (0.25, 0.5, 0.75):
        d.line([lerp(26 * u, 78 * u, f), top_y,
                lerp(14 * u, 90 * u, f), bot_y], fill=DARK, width=int(2.4 * u))
    d.line(panel + [panel[0]], fill=DARK, width=int(2.4 * u), joint="curve")

    return img.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    import pathlib
    out = pathlib.Path(__file__).resolve().parents[1] / "custom_components/eway_solar/brand"
    out.mkdir(parents=True, exist_ok=True)
    for name, size in (("icon.png", 256), ("icon@2x.png", 512)):
        draw(size).save(out / name)
        print("wrote", out / name, size)
    # HACS accepts an icon-only brand; logo.png is optional and a square icon
    # doubles acceptably where a logo is wanted.
    for name, size in (("logo.png", 256), ("logo@2x.png", 512)):
        draw(size).save(out / name)
        print("wrote", out / name, size)
