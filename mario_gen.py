#!/usr/bin/env python3
"""Generate a 3D Mario-style GitHub profile banner SVG.

Output is intentionally standalone and does not touch snake.svg / snake_gen.py.
Style:
- 3D isometric blocky tiles (top / front / right faces)
- side-scroller banner: ground platform, coins, brick + question blocks, mushroom
- SMIL animations only, so GitHub <img> keeps them
"""
from __future__ import annotations

import json
import os
import xml.dom.minidom
from typing import List, Dict, Tuple, Optional

# ---------------------------------------------------------------------------
# Geometry / palette
# ---------------------------------------------------------------------------
W, H = 664, 240

BG_TOP, BG_BOT = "#0b1020", "#070a12"
GROUND_Y = 186                 # top of ground platform
GROUND_H = 34

# Isometric block metrics
BW, BH = 34, 34                # top-face width / height
DEPTH = 16                      # depth offset for side faces

# palette
PAL = {
    "grass_top": "#5fd14a",
    "grass_front": "#2f9f30",
    "dirt_top": "#c07a38",
    "dirt_front": "#8a4f1f",
    "dirt_side": "#6b3b17",
    "brick_top": "#b3562a",
    "brick_front": "#8a3d1e",
    "brick_side": "#642d16",
    "q_top": "#ffc24a",
    "q_front": "#e08a1a",
    "q_side": "#a85f0e",
    "coin_face": "#ffd84a",
    "coin_edge": "#b98a00",
    "mush_cap": "#e0352a",
    "mush_stem": "#ffe9c8",
    "pipe_top": "#2faa4a",
    "pipe_front": "#1f7a33",
    "pipe_side": "#14531f",
    "sky_a": "#2b6cb0",
    "sky_b": "#1b3f6b",
    "star": "#fff3a0",
}


def iso_cube(cx: float, cy: float, w: float = BW, d: float = DEPTH) -> Dict[str, str]:
    """Isometric cube face point-lists centred on (cx, cy).

    top    : diamond above the centre
    front  : rectangle below top-left/top-right
    right  : parallelogram to the right
    """
    half = w * 0.5
    top = [
        (cx - half, cy),
        (cx, cy - half),
        (cx + half, cy),
        (cx, cy + half),
    ]
    # side depth vector: back-right, up
    dx, dy = d, -d * 0.5

    # build face polys
    def poly(pts):
        return " ".join(f"{p[0]:.1f},{p[1]:.1f}" for p in pts)

    top_poly = poly(top)

    # front face: the two front corners of the top diamond, dropped down
    front = [top[0], top[2], (top[2][0], top[2][1] + BH), (top[0][0], top[0][1] + BH)]
    front_poly = poly(front)

    # right face: right corner + back-right, dropped down
    back = (top[2][0] + dx, top[2][1] + dy)
    right = [top[2], back, (back[0], back[1] + BH), (top[2][0], top[2][1] + BH)]
    right_poly = poly(right)

    return {"top": top_poly, "front": front_poly, "right": right_poly}


def shade(hexcol: str, f: float) -> str:
    """Lighten (f>0) or darken (f<0) a #rrggbb colour."""
    r, g, b = _h2rgb(hexcol)
    def cl(v): return max(0, min(255, int(round(v))))
    if f >= 0:
        r, g, b = cl(r + (255 - r) * f), cl(g + (255 - g) * f), cl(b + (255 - b) * f)
    else:
        r, g, b = cl(r * (1 + f)), cl(g * (1 + f)), cl(b * (1 + f))
    return "#%02x%02x%02x" % (r, g, b)


def _h2rgb(h):
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def mix(a: str, b: str, t: float) -> str:
    ar, ag, ab = _h2rgb(a)
    br, bg, bb = _h2rgb(b)
    return "#%02x%02x%02x" % (int(ar + (br-ar)*t), int(ag + (bg-ag)*t), int(ab + (bb-ab)*t))


# ---------------------------------------------------------------------------
# SVG pieces
# ---------------------------------------------------------------------------
def defs() -> str:
    p: List[str] = ["<defs>"]
    p.append(f'<linearGradient id="gSky" x1="0" y1="0" x2="0" y2="1">'
             f'<stop offset="0%" stop-color="{BG_TOP}"/>'
             f'<stop offset="100%" stop-color="{BG_BOT}"/></linearGradient>')
    p.append(f'<linearGradient id="gCard" x1="0" y1="0" x2="0" y2="1">'
             f'<stop offset="0%" stop-color="{BG_TOP}"/>'
             f'<stop offset="100%" stop-color="#05070d"/></linearGradient>')
    # ambient halo
    p.append('<radialGradient id="gAmbient" cx="50%" cy="40%" r="62%">'
             '<stop offset="0%" stop-color="#1e4a7a" stop-opacity="0.45"/>'
             '<stop offset="60%" stop-color="#0e2440" stop-opacity="0.15"/>'
             '<stop offset="100%" stop-color="#000000" stop-opacity="0"/></radialGradient>')
    # soft shadow filter
    p.append('<filter id="fSoft" filterUnits="userSpaceOnUse" x="-80" y="-80" width="820" height="400">'
             '<feGaussianBlur in="SourceAlpha" stdDeviation="3"/>'
             '<feOffset dx="0" dy="4" result="off"/>'
             '<feFlood flood-color="#000000" flood-opacity="0.5"/>'
             '<feComposite in2="off" operator="in" result="s"/>'
             '<feMerge><feMergeNode in="s"/><feMergeNode in="SourceGraphic"/></feMerge></filter>')
    p.append("</defs>")
    return "".join(p)


def plate() -> str:
    return (
        f'<rect x="0" y="0" width="{W}" height="{H}" fill="url(#gCard)"/>'
        f'<rect x="0" y="0" width="{W}" height="{H}" fill="url(#gAmbient)"/>'
        f'<rect x="0.5" y="0.5" width="{W-1}" height="{H-1}" fill="none" stroke="#1d2a3a" stroke-width="1"/>'
    )


def clouds() -> str:
    """A few puffy 3D clouds for the side-scroller sky."""
    out: List[str] = []
    cloud_pts = [(90, 56), (250, 44), (470, 60), (600, 48)]
    for cx, cy in cloud_pts:
        out.append(f'<g opacity="0.85" transform="translate({cx},{cy})">')
        for dx, dy, r in [(-16, 2, 10), (-6, -6, 12), (8, -3, 13), (18, 3, 9)]:
            out.append(f'<ellipse cx="{dx}" cy="{dy}" rx="{r}" ry="{r*0.7:.1f}" fill="#dfe9f5"/>')
        out.append("</g>")
    return "".join(out)


def hills() -> str:
    """Distant rounded hills behind the ground."""
    return (
        '<g opacity="0.55">'
        '<path d="M0,168 Q60,128 120,160 Q180,196 240,156 Q300,118 360,160 Q420,200 480,154 Q540,120 600,160 Q660,196 700,168 L700,200 L0,200 Z" fill="#2a4a6a"/>'
        '<path d="M0,180 Q80,150 160,176 Q240,202 320,170 Q400,142 480,176 Q560,204 640,172 Q680,158 700,176 L700,200 L0,200 Z" fill="#1d3a5a"/>'
        '</g>'
    )


def ground_row() -> str:
    """A row of isometric ground tiles with a grass top + dirt front."""
    tiles: List[str] = []
    n = 20
    tw = (W + 30) / n
    for i in range(n):
        cx = i * tw + tw / 2 - 15
        cy = GROUND_Y
        c = iso_cube(cx, cy, w=tw, d=DEPTH)
        tiles.append(f'<polygon points="{c["top"]}" fill="{PAL["grass_top"]}"/>')
        tiles.append(f'<polygon points="{c["top"]}" fill="#ffffff" opacity="0.18"/>')  # glint
        tiles.append(f'<polygon points="{c["front"]}" fill="{PAL["grass_front"]}"/>')
        tiles.append(f'<polygon points="{c["right"]}" fill="{shade(PAL["grass_front"], -0.3)}"/>')
        # dirt layer below grass (front + right, lower)
        tiles.append(f'<polygon points="{c["front"]}" fill="{PAL["dirt_front"]}" '
                     f'transform="translate(0,18)" opacity="0.0"/>')
    return "".join(tiles)


def dirt_underlay() -> str:
    """Solid dirt band under the grass row so the ground reads as solid."""
    return (
        f'<rect x="0" y="{GROUND_Y+18}" width="{W}" height="{GROUND_H-18}" fill="{PAL["dirt_front"]}"/>'
        f'<rect x="0" y="{GROUND_Y+18}" width="{W}" height="4" fill="{PAL["dirt_top"]}"/>'
        f'<rect x="0" y="{GROUND_Y+GROUND_H-2}" width="{W}" height="2" fill="{shade(PAL["dirt_front"],-0.35)}"/>'
    )


def block(cx: float, cy: float, kind: str = "brick") -> str:
    """A 3D block (brick / question) centred at (cx, cy)."""
    if kind == "question":
        top, front, side = PAL["q_top"], PAL["q_front"], PAL["q_side"]
    else:
        top, front, side = PAL["brick_top"], PAL["brick_front"], PAL["brick_side"]
    c = iso_cube(cx, cy, w=BW, d=DEPTH)
    out: List[str] = []
    out.append(f'<g filter="url(#fSoft)">')
    out.append(f'<polygon points="{c["top"]}" fill="{top}"/>')
    out.append(f'<polygon points="{c["front"]}" fill="{front}"/>')
    out.append(f'<polygon points="{c["right"]}" fill="{side}"/>')
    # bevel highlight on top face
    out.append(f'<polygon points="{c["top"]}" fill="#ffffff" opacity="0.22"/>')
    # face details
    if kind == "question":
        # question mark glyph (use a real text element so it renders)
        out.append(f'<text x="{cx}" y="{cy+8}" font-family="\'JetBrains Mono\',monospace" '
                   f'font-size="20" font-weight="800" text-anchor="middle" '
                   f'fill="#3a1e00" stroke="#ffe9a0" stroke-width="0.5">?</text>')
        # rivets at corners
        for dx, dy in [(-12, 8), (12, 8)]:
            out.append(f'<circle cx="{cx+dx}" cy="{cy+dy}" r="2.2" fill="#3a1e00"/>')
    else:
        # brick mortar lines
        out.append(f'<line x1="{cx-BW/2}" y1="{cy+BH/2*0.33}" x2="{cx+BW/2}" y2="{cy+BH/2*0.33}" '
                   f'stroke="#3a1a08" stroke-width="1.4" opacity="0.55"/>')
        out.append(f'<line x1="{cx-BW/2}" y1="{cy+BH/2*0.66}" x2="{cx+BW/2}" y2="{cy+BH/2*0.66}" '
                   f'stroke="#3a1a08" stroke-width="1.4" opacity="0.55"/>')
        out.append(f'<line x1="{cx}" y1="{cy+BH/2*0.33}" x2="{cx}" y2="{cy+BH/2*0.66}" '
                   f'stroke="#3a1a08" stroke-width="1.4" opacity="0.55"/>')
        out.append(f'<line x1="{cx-BW/2}" y1="{cy+BH/2*0.66}" x2="{cx-BW/2}" y2="{cy+BH}" '
                   f'stroke="#3a1a08" stroke-width="1.4" opacity="0.55"/>')
        out.append(f'<line x1="{cx+BW/2}" y1="{cy+BH/2*0.66}" x2="{cx+BW/2}" y2="{cy+BH}" '
                   f'stroke="#3a1a08" stroke-width="1.4" opacity="0.55"/>')
    out.append("</g>")
    return "".join(out)


def coin(cx: float, cy: float, phase: float = 0.0) -> str:
    """A spinning coin (animate the rx of an ellipse)."""
    out: List[str] = []
    out.append(f'<g transform="translate({cx},{cy})">')
    # shadow on ground
    out.append(f'<ellipse cx="0" cy="14" rx="9" ry="2.4" fill="#000000" opacity="0.4"/>')
    # outer rim
    out.append(f'<ellipse cx="0" cy="0" rx="10" ry="10" fill="{PAL["coin_edge"]}"/>')
    # face
    out.append(f'<ellipse cx="0" cy="0" rx="8" ry="10" fill="{PAL["coin_face"]}"/>')
    # shine
    out.append(f'<ellipse cx="-3" cy="-3" rx="2.5" ry="4" fill="#fff6c8" opacity="0.85"/>')
    # spin animation: squish rx
    out.append(f'<animate attributeName="rx" values="10;3;10" dur="1.2s" '
               f'begin="{phase}s" repeatCount="indefinite"/>')
    out.append("</g>")
    return "".join(out)


def mushroom(cx: float, cy: float) -> str:
    """A mushroom power-up."""
    out: List[str] = []
    out.append(f'<g transform="translate({cx},{cy})">')
    out.append('<ellipse cx="0" cy="14" rx="11" ry="2.6" fill="#000000" opacity="0.45"/>')
    # stem
    out.append(f'<rect x="-7" y="-2" width="14" height="14" rx="3" fill="{PAL["mush_stem"]}"/>')
    out.append(f'<rect x="-7" y="-2" width="4" height="14" rx="3" fill="#ffffff" opacity="0.4"/>')
    # cap
    out.append(f'<path d="M-12,2 Q-12,-10 0,-12 Q12,-10 12,2 Z" fill="{PAL["mush_cap"]}"/>')
    out.append(f'<ellipse cx="-5" cy="-7" rx="3" ry="2.4" fill="#ffffff"/>')
    out.append(f'<ellipse cx="5" cy="-5" rx="2.4" ry="2" fill="#ffffff"/>')
    out.append(f'<ellipse cx="0" cy="-2" rx="2" ry="1.6" fill="#ffffff"/>')
    out.append("</g>")
    return "".join(out)


def pipe(cx: float, cy: float, h: int = 60) -> str:
    """A green warp pipe."""
    out: List[str] = []
    out.append(f'<g transform="translate({cx},{cy})">')
    # body
    out.append(f'<rect x="0" y="0" width="34" height="{h}" fill="{PAL["pipe_front"]}"/>')
    out.append(f'<rect x="0" y="0" width="10" height="{h}" fill="{PAL["pipe_top"]}"/>')
    out.append(f'<rect x="26" y="0" width="8" height="{h}" fill="{PAL["pipe_side"]}"/>')
    # rim (top band)
    out.append(f'<rect x="-4" y="-10" width="42" height="14" rx="3" fill="{PAL["pipe_front"]}"/>')
    out.append(f'<rect x="-4" y="-10" width="14" height="14" rx="3" fill="{PAL["pipe_top"]}"/>')
    out.append(f'<rect x="26" y="-10" width="12" height="14" rx="3" fill="{PAL["pipe_side"]}"/>')
    out.append(f'<rect x="-4" y="-10" width="42" height="4" fill="#ffffff" opacity="0.3"/>')
    out.append("</g>")
    return "".join(out)


def stars() -> str:
    """A few twinkling stars."""
    out: List[str] = []
    for x, y, s, d in [(140, 28, 3, 0.0), (330, 20, 2.5, 0.6), (560, 32, 2.8, 1.1), (80, 18, 2, 0.3)]:
        out.append(f'<g transform="translate({x},{y})">')
        out.append(f'<path d="M0,-{s} L1.2,-0.4 L3.6,0 L1.2,0.6 L0,{s} L-1.2,0.6 L-3.6,0 L-1.2,-0.4 Z" fill="{PAL["star"]}"/>')
        out.append(f'<animate attributeName="opacity" values="1;0.3;1" dur="1.8s" begin="{d}s" repeatCount="indefinite"/>')
        out.append("</g>")
    return "".join(out)


def footer(left: str, right: str) -> str:
    y = H - 11
    return (
        f'<g font-family="\'JetBrains Mono\',monospace" font-size="12" font-weight="700">'
        f'<text x="14" y="{y}" text-anchor="start" fill="#9fb0d4">{left}</text>'
        f'<text x="{W-14}" y="{y}" text-anchor="end" fill="#6e7a99">{right}</text>'
        '</g>'
    )


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------
def build_svg(data: Optional[Dict] = None) -> str:
    repo = (data or {}).get("repo") or "zhouzxing/zhouzxing"
    weeks = (data or {}).get("weeks") or []
    total = sum(int(w.get("total", 0)) for w in weeks)
    active = sum(1 for w in weeks if int(w.get("total", 0)) > 0)
    left = f"{repo.split('/')[-1]}/  {total} commits"
    right = f"{active} 周"

    parts: List[str] = []
    parts.append(f'<svg width="{W}" height="{H}" fill="#c9d1d9" '
                 f'xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
                 f'style="color-scheme: light dark" '
                 f'data-dark-background="#080b16" data-light-background="#f6f8fa">')
    parts.append(defs())
    parts.append(plate())
    parts.append(clouds())
    parts.append(stars())
    parts.append(hills())
    parts.append(dirt_underlay())
    parts.append(ground_row())
    # blocks floating above ground
    parts.append(block(180, 120, "brick"))
    parts.append(block(218, 120, "brick"))
    parts.append(block(256, 120, "question"))
    parts.append(block(180, 86, "brick"))
    # coins
    parts.append(coin(120, 150, 0.0))
    parts.append(coin(330, 150, 0.3))
    parts.append(coin(360, 150, 0.6))
    # mushroom
    parts.append(mushroom(430, 156))
    # pipe
    parts.append(pipe(520, GROUND_Y - 58))
    parts.append(footer(left, right))
    parts.append("</svg>")

    svg = "".join(parts)
    _validate(svg)
    return svg


def _validate(svg: str) -> None:
    try:
        xml.dom.minidom.parseString(svg)
    except Exception as exc:
        raise SystemExit(f"ERROR: SVG not well-formed: {exc}") from exc


def load_data(path: str = "snake_data.json") -> Dict:
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fh:
                d = json.load(fh)
            if isinstance(d, dict) and isinstance(d.get("weeks"), list):
                return d
        except Exception as exc:
            print(f"[warn] cannot load {path}: {exc}")
    return {"repo": "zhouzxing/zhouzxing", "weeks": []}


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    data_path = os.path.join(os.path.dirname(here), "gh_probe", "probe_repo", "snake_data.json")
    data = load_data(data_path)
    svg = build_svg(data)
    out = os.path.join(here, "mario.svg")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(svg)
    print(f"mario.svg: {len(svg)} bytes  {W}x{H}  XML OK")
