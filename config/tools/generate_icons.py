"""Regenerate the PNG icon set from config/images/chef-hat-icon.svg.

Produces (all in config/images/):
  icon-192.png           PWA "any" icon — red circle, transparent corners
  icon-512.png           PWA "any" icon
  icon-512-maskable.png  PWA "maskable" icon — full-bleed red square
  apple-touch-icon.png   180x180 full-bleed red square for iOS home screens

The hat path is rasterised directly from the SVG (even-odd scanline fill,
4x supersampled, Lanczos downscale) so the PNGs match the SVG favicon.

Requires Pillow:  pip install pillow
Usage:            python config/tools/generate_icons.py
"""
from __future__ import annotations

import math
import re
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
SVG_PATH = ROOT / "config" / "images" / "chef-hat-icon.svg"
OUT_DIR = SVG_PATH.parent

CANVAS = 512  # SVG viewBox size
SCALE = 0.35  # hat scale used inside the SVG
SS = 4        # supersample factor
RED = (230, 57, 70, 255)  # #E63946

TOKEN = re.compile(r"[MmCcLlHhVvZz]|-?\d*\.?\d+(?:[eE][+-]?\d+)?")
ARGC = {"M": 2, "m": 2, "L": 2, "l": 2, "H": 1, "h": 1,
        "V": 1, "v": 1, "C": 6, "c": 6, "Z": 0, "z": 0}


def flatten_path(d: str):
    """Parse an SVG path and return subpaths as flat point lists."""
    tokens = TOKEN.findall(d)
    cmds = []
    pending = None
    args: list[float] = []
    for tok in tokens:
        if tok.isalpha():
            if pending and (args or pending in "Zz"):
                cmds.append((pending, args))
            pending, args = tok, []
        else:
            args.append(float(tok))
            while pending and ARGC[pending] and len(args) >= ARGC[pending]:
                cmds.append((pending, args[: ARGC[pending]]))
                args = args[ARGC[pending]:]
                if pending == "M":
                    pending = "L"
                elif pending == "m":
                    pending = "l"
    if pending and (args or pending in "Zz"):
        cmds.append((pending, args))

    def cubic(p0, p1, p2, p3, steps=28):
        pts = []
        for i in range(1, steps + 1):
            t = i / steps
            u = 1 - t
            x = u**3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0]
            y = u**3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1]
            pts.append((x, y))
        return pts

    subpaths: list[list[tuple[float, float]]] = []
    cur: list[tuple[float, float]] = []
    cx = cy = start_x = start_y = 0.0
    for cmd, a in cmds:
        if cmd in "Mm":
            if len(cur) > 1:
                cur.append(cur[0])
                subpaths.append(cur)
            if cmd == "M":
                cx, cy = a
            else:
                cx, cy = cx + a[0], cy + a[1]
            start_x, start_y = cx, cy
            cur = [(cx, cy)]
        elif cmd in "Ll":
            if cmd == "L":
                cx, cy = a
            else:
                cx, cy = cx + a[0], cy + a[1]
            cur.append((cx, cy))
        elif cmd in "Hh":
            cx = a[0] if cmd == "H" else cx + a[0]
            cur.append((cx, cy))
        elif cmd in "Vv":
            cy = a[0] if cmd == "V" else cy + a[0]
            cur.append((cx, cy))
        elif cmd in "Cc":
            if cmd == "c":
                p1 = (cx + a[0], cy + a[1])
                p2 = (cx + a[2], cy + a[3])
                p3 = (cx + a[4], cy + a[5])
            else:
                p1, p2, p3 = (a[0], a[1]), (a[2], a[3]), (a[4], a[5])
            cur.extend(cubic((cx, cy), p1, p2, p3))
            cx, cy = p3
        elif cmd in "Zz":
            if len(cur) > 1:
                cur.append(cur[0])
                subpaths.append(cur)
            cur = []
            cx, cy = start_x, start_y
    if len(cur) > 1:
        cur.append(cur[0])
        subpaths.append(cur)

    # Apply the SVG's transform (scale about centre) and supersample.
    out = []
    for sp in subpaths:
        out.append([
            (((x - CANVAS / 2) * SCALE + CANVAS / 2) * SS,
             ((y - CANVAS / 2) * SCALE + CANVAS / 2) * SS)
            for x, y in sp
        ])
    return out


def rasterize_nonzero(subpaths, size) -> Image.Image:
    """Scanline nonzero-winding fill (matches SVG default fill rule).

    Returns an L-mode mask.
    """
    edges = []
    for sp in subpaths:
        for (x1, y1), (x2, y2) in zip(sp, sp[1:]):
            if y1 != y2:
                edges.append((x1, y1, x2, y2))
    mask = Image.new("L", (size, size), 0)
    data = bytearray(size * size)
    for row in range(size):
        yc = row + 0.5
        xs = []
        for x1, y1, x2, y2 in edges:
            if (y1 <= yc < y2) or (y2 <= yc < y1):
                x = x1 + (yc - y1) * (x2 - x1) / (y2 - y1)
                xs.append((x, 1 if y2 > y1 else -1))
        if not xs:
            continue
        xs.sort()
        base = row * size
        wind = 0
        prev = 0.0
        for x, direction in xs:
            if wind != 0:
                a, b = int(prev), math.ceil(x)
                if b > a:
                    data[base + a: base + b] = b"\xff" * (b - a)
            wind += direction
            prev = x
    mask.putdata(data)
    return mask


def compose(full_bleed: bool) -> Image.Image:
    size = CANVAS * SS
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    if full_bleed:
        draw = ImageDraw.Draw(img)
        draw.rectangle([0, 0, size, size], fill=RED)
    else:
        draw = ImageDraw.Draw(img)
        draw.ellipse([0, 0, size - 1, size - 1], fill=RED)
    white = Image.new("RGBA", (size, size), (255, 255, 255, 255))
    svg_d = SVG_PATH.read_text(encoding="utf-8")
    d = re.search(r'\bd="([^"]+)"', svg_d).group(1)
    mask = rasterize_nonzero(flatten_path(d), size)
    img.paste(white, (0, 0), mask)
    return img


def main():
    any_icon = compose(full_bleed=False)
    bleed = compose(full_bleed=True)

    any_icon.resize((512, 512), Image.LANCZOS).save(OUT_DIR / "icon-512.png")
    any_icon.resize((192, 192), Image.LANCZOS).save(OUT_DIR / "icon-192.png")
    bleed.resize((512, 512), Image.LANCZOS).save(OUT_DIR / "icon-512-maskable.png")
    bleed.resize((180, 180), Image.LANCZOS).save(OUT_DIR / "apple-touch-icon.png")
    print("Wrote icon-192.png, icon-512.png, icon-512-maskable.png, apple-touch-icon.png")


if __name__ == "__main__":
    main()
