#!/usr/bin/env python3
"""Generate a The Legend of Zelda: Wind Waker style 3D banner SVG.

Trajectory is driven by git commit data — each commit becomes a waypoint
for Link's sailboat across the Great Sea.  SMIL animations only so
GitHub <img> keeps them.  Does NOT touch snake.svg / snake_gen.py.
"""
from __future__ import annotations

import json
import os
import xml.dom.minidom
import hashlib
from typing import List, Dict, Tuple

W, H = 664, 240

BG_TOP, BG_BOT = "#1a3a6a", "#0a1830"
OCEAN_TOP, OCEAN_BOT = "#0e4478", "#062040"
WAVE_COLOR = "#145890"
GROUND_Y = 186

PAL = {
    "sky_top": "#3a78c8",
    "sky_bot": "#0e2840",
    "ocean_a": "#0e4478",
    "ocean_b": "#062040",
    "grass": "#4a9a3a",
    "grass_dark": "#2a6a20",
    "dirt": "#9a6a30",
    "wood": "#5a3a1a",
    "wood_light": "#7a5a2a",
    "sail": "#c83020",
    "sail_dark": "#8a1810",
    "link_tunic": "#2a8a30",
    "link_skin": "#f5c8a0",
    "link_hat": "#c8a050",
    "triforce_gold": "#ffd84a",
    "triforce_dark": "#b08800",
}

# ─── geometry helpers ───────────────────────────────────────────────

def iso_cube(cx, cy, w=30, d=14):
    half, th = w * 0.5, d * 0.5
    top = f"{cx-half},{cy} {cx},{cy-th} {cx+half},{cy} {cx},{cy+th}"
    front = f"{cx-half},{cy} {cx+half},{cy} {cx+half},{cy+w} {cx-half},{cy+w}"
    right = f"{cx+half},{cy} {cx+half+th},{cy-th} {cx+half+th},{cy+w-th} {cx+half},{cy+w}"
    return {"top": top, "front": front, "right": right}


def shade(hexcol, f):
    r, g, b = _h2rgb(hexcol)
    if f >= 0:
        r, g, b = int(r + (255-r)*f), int(g + (255-g)*f), int(b + (255-b)*f)
    else:
        r, g, b = int(r*(1+f)), int(g*(1+f)), int(b*(1+f))
    return f"#{r:02x}{g:02x}{b:02x}"

def _h2rgb(h):
    h = h.lstrip("#")
    return int(h[0:2],16), int(h[2:4],16), int(h[4:6],16)

def mix(a, b, t):
    ar,ag,ab = _h2rgb(a); br,bg,bb = _h2rgb(b)
    return f"#{int(ar+(br-ar)*t):02x}{int(ag+(bg-ag)*t):02x}{int(ab+(bb-ab)*t):02x}"

# ─── commit-driven trajectory ───────────────────────────────────────

def _load_commits():
    path = "/home/geeker/.hermes/cache/scratch/gh_probe/probe_repo/snake_data.json"
    try:
        with open(path) as f:
            d = json.load(f)
        if isinstance(d, dict) and isinstance(d.get("weeks"), list):
            return d["weeks"]
    except Exception:
        pass
    return []


def build_trajectory(weeks, max_pts=60):
    """Turn commit weeks into sea waypoints.

    Each week becomes a point.  x = week index * step, y = sin-based wave
    whose amplitude/frequency is seeded by the week's commit total (hash).
    Fewer commits → calmer water; more commits → bigger waves / sharper turns.
    y is clamped to stay on-screen.
    Returns list of (x, y) in SVG coords.
    """
    if not weeks:
        import math
        return [(i*12, 140 + int(8*math.sin(i*0.4))) for i in range(20)]

    def seed_for(w):
        h = hashlib.md5((str(w.get("week",""))+"|zorg").encode()).digest()
        return h[0] + (h[1]<<8)

    import math
    pts = []
    n = len(weeks)
    step = (W - 80) / max(n - 1, 1)
    y_min = GROUND_Y - 80    # don't go above the sky
    y_max = GROUND_Y - 10    # don't sink into the ground
    for i, w in enumerate(weeks[:max_pts]):
        total = int(w.get("total", 0))
        s = seed_for(w)
        amp = 6 + (s % 24)
        freq = 0.3 + (s % 7) * 0.1
        phase = (s >> 4) % 6.28
        x = 40 + i * step
        y = GROUND_Y - 30 - amp*math.sin(i*freq + phase)
        y = max(y_min, min(y_max, y))   # clamp on-screen
        pts.append((round(x,1), round(y,1)))
    return pts


def build_path_simple(pts):
    """SVG path through pts with plain L segments (no overshoot)."""
    if not pts:
        return ""
    d = [f"M{pts[0][0]},{pts[0][1]}"]
    for x, y in pts[1:]:
        d.append(f"L{x},{y}")
    return " ".join(d)


def smooth_path(pts, tension=0.4):
    """Catmull-Rom -> cubic Bézier smooth path through pts.

    NOTE: can overshoot waypoint bounds.  Prefer build_path_simple
    when clamped waypoints are required (e.g. sea trajectories).
    """
    if len(pts) < 2:
        return f"M{pts[0][0]},{pts[0][1]}" if pts else ""
    d = [f"M{pts[0][0]},{pts[0][1]}"]
    for i in range(len(pts)):
        p0 = pts[i-1] if i > 0 else pts[0]
        p1 = pts[i]
        p2 = pts[i+1] if i < len(pts)-1 else pts[-1]
        p3 = pts[i+2] if i < len(pts)-2 else pts[-1]
        cp1x = p1[0] + (p2[0]-p0[0])*tension
        cp1y = p1[1] + (p2[1]-p0[1])*tension
        cp2x = p2[0] - (p3[0]-p1[0])*tension
        cp2y = p2[1] - (p3[1]-p1[1])*tension
        d.append(f"C{cp1x:.1f},{cp1y:.1f} {cp2x:.1f},{cp2y:.1f} {p2[0]:.1f},{p2[1]:.1f}")
    return " ".join(d)

# ─── SVG pieces ─────────────────────────────────────────────────────

def defs():
    return ("<defs>"
        f'<linearGradient id="gSky" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0%" stop-color="{PAL["sky_top"]}"/>'
        f'<stop offset="100%" stop-color="{PAL["sky_bot"]}"/></linearGradient>'
        f'<linearGradient id="gOcean" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0%" stop-color="{PAL["ocean_a"]}"/>'
        f'<stop offset="100%" stop-color="{PAL["ocean_b"]}"/></linearGradient>'
        '<radialGradient id="gSun" cx="50%" cy="50%" r="50%">'
        '<stop offset="0%" stop-color="#ffe880" stop-opacity="0.9"/>'
        '<stop offset="40%" stop-color="#ffb840" stop-opacity="0.5"/>'
        '<stop offset="100%" stop-color="#ff6020" stop-opacity="0"/></radialGradient>'
        '<filter id="fBloom" x="-20%" y="-20%" width="140%" height="140%">'
        '<feGaussianBlur in="SourceGraphic" stdDeviation="2.5" result="b"/>'
        '<feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>'
        '<filter id="fShadow" x="-10%" y="-10%" width="130%" height="150%">'
        '<feGaussianBlur in="SourceAlpha" stdDeviation="3"/>'
        '<feOffset dx="1" dy="4"/><feFlood flood-color="#000" flood-opacity="0.5"/>'
        '<feComposite in2="off" operator="in"/>'
        '<feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge></filter>'
        "</defs>")

def plate():
    return (f'<rect width="{W}" height="{H}" fill="url(#gSky)"/>'
            f'<rect width="{W}" height="{H}" fill="url(#gOcean)"/>')

def sun():
    return (f'<circle cx="560" cy="42" r="34" fill="url(#gSun)" filter="url(#fBloom)"/>'
            f'<circle cx="560" cy="42" r="22" fill="#ffe880" opacity="0.7"/>')

def clouds():
    out=[]
    for cx,cy,s in [(80,48,1.0),(300,34,0.7),(520,56,0.9)]:
        out.append(f'<g transform="translate({cx},{cy})" opacity="0.8">')
        for dx,dy,r in [(-12*s,2*s,8*s),(-2*s,-8*s,10*s),(10*s,-5*s,11*s),(22*s,3*s,8*s)]:
            out.append(f'<ellipse cx="{dx}" cy="{dy}" rx="{r}" ry="{r*0.6}" fill="#dfe9f5"/>')
        out.append("</g>")
    return "".join(out)

def islands():
    """Small isometric islands peeking above the ocean."""
    out=[]
    # island 1 - left
    c = iso_cube(110, 178, w=40, d=16)
    out.append(f'<g filter="url(#fShadow)">')
    out.append(f'<polygon points="{c["top"]}" fill="{PAL["grass"]}"/>')
    out.append(f'<polygon points="{c["front"]}" fill="{PAL["grass_dark"]}"/>')
    out.append(f'<polygon points="{c["right"]}" fill="{shade(PAL["grass_dark"],-0.3)}"/>')
    # palm trunk
    out.append(f'<line x1="110" y1="168" x2="110" y2="146" stroke="{PAL["wood"]}" stroke-width="3"/>')
    # palm fronds
    out.append(f'<path d="M110,146 Q124,134 136,140 Q130,148 110,146Z" fill="{PAL["grass"]}"/>')
    out.append(f'<path d="M110,146 Q96,134 84,140 Q90,148 110,146Z" fill="{PAL["grass_dark"]}"/>')
    out.append("</g>")
    # island 2 - right
    c = iso_cube(480, 182, w=34, d=14)
    out.append(f'<g filter="url(#fShadow)">')
    out.append(f'<polygon points="{c["top"]}" fill="{PAL["grass"]}"/>')
    out.append(f'<polygon points="{c["front"]}" fill="{PAL["grass_dark"]}"/>')
    out.append(f'<polygon points="{c["right"]}" fill="{shade(PAL["grass_dark"],-0.3)}"/>')
    out.append(f'<line x1="480" y1="172" x2="480" y2="154" stroke="{PAL["wood"]}" stroke-width="2.5"/>')
    out.append(f'<path d="M480,154 Q492,144 502,148 Q498,154 480,154Z" fill="{PAL["grass"]}"/>')
    out.append("</g>")
    return "".join(out)

def ocean_waves():
    """Animated wave lines — the signature Wind Waker ocean."""
    out=[]
    for i, (base_y, amp, spd, phase) in enumerate([
        (172, 5, 2.5, 0), (178, 4, 2.0, 1.2), (184, 3, 1.6, 2.4)]):
        pts = []
        for x in range(0, W+20, 8):
            y = base_y + amp*__import__("math").sin(x*0.035*spd + phase)
            pts.append(f"L{x},{y:.1f}")
        out.append(f'<polyline points="0,{base_y} {" ".join(pts)}" fill="none" '
                   f'stroke="{WAVE_COLOR}" stroke-width="2" opacity="0.6">'
                   f'<animate attributeName="points" dur="{3.5+i*0.8}s" '
                   f'values="0,{base_y} {" ".join(pts)};0,{base_y} {" ".join(pts[:0:-1])}" '
                   f'repeatCount="indefinite"/></polyline>')
    return "".join(out)

def sailboat(path_d, commits):
    """Red sailboat (King of Red Lions) following the commit trajectory.

    Link stands on the boat deck; the whole group follows the path.
    """
    dur = max(12.0, len(commits) * 1.2)
    body = (
        # hull - dark wood
        f'<path d="M-16,0 L16,0 L12,-5 L-12,-5 Z" fill="{PAL["wood"]}"/>'
        # hull top rim
        f'<path d="M-12,-5 L12,-5 L10,-3 L-10,-3 Z" fill="{PAL["wood_light"]}"/>'
        # sail - red canvas
        f'<path d="M0,-3 L0,-28 L14,-16 Z" fill="{PAL["sail"]}" filter="url(#fBloom)"/>'
        # sail shadow
        f'<path d="M0,-3 L0,-28 L6,-16 Z" fill="{PAL["sail_dark"]}" opacity="0.5"/>'
        # sail ripples
        f'<path d="M3,-10 L8,-14 L3,-18" fill="none" stroke="#fff" stroke-width="0.8" opacity="0.7">'
        f'<animate attributeName="d" dur="0.8s" repeatCount="indefinite"'
        f' values="M3,-10 L8,-14 L3,-18;M3,-10 L6,-12 L3,-16;M3,-10 L8,-14 L3,-18"/></path>'
        # flag pole + triforce flag
        f'<line x1="0" y1="-28" x2="0" y2="-36" stroke="{PAL["wood"]}" stroke-width="1.5"/>'
        f'<polygon points="0,-38 10,-34 0,-30" fill="{PAL["triforce_gold"]}">'
        f'<animate attributeName="opacity" values="1;0.8;1" dur="2s" repeatCount="indefinite"/></polygon>'
        # Link on deck
        f'<g transform="translate(0,-5)">'
        f'<rect x="-5" y="10" width="5" height="10" fill="#3a2a10" rx="1"/>'
        f'<rect x="1" y="10" width="5" height="10" fill="#3a2a10" rx="1"/>'
        f'<polygon points="-11,0 1,0 1,22 -11,22" fill="{PAL["link_tunic"]}"/>'
        f'<polygon points="-11,0 1,0 0,-2  -11,2" fill="{mix(PAL["link_tunic"], "#ffffff", 0.2)}"/>'
        f'<path d="M-11,-2 Q-11,-14 0,-16 Q11,-14 11,-2 Z" fill="#1a6a20"/>'
        f'<path d="M-11,-2 Q0,-4 11,-2 Z" fill="#2a8a30"/>'
        f'<ellipse cx="0" cy="-2" rx="10" ry="3" fill="#1a5a18"/>'
        f'<line x1="13" y1="-2" x2="23" y2="-14" stroke="#c0c0c0" stroke-width="2" stroke-linecap="round">'
        f'<animateTransform attributeName="transform" type="rotate"'
        f' values="0 13,-2;12 13,-2;0 13,-2;-10 13,-2;0 13,-2" dur="1.6s" repeatCount="indefinite"/></line>'
        f'<circle cx="-3" cy="-6" r="2" fill="#1a0500"/>'
        f'<circle cx="3" cy="-6" r="2" fill="#1a0500"/>'
        f'<circle cx="-2.5" cy="-6.5" r="0.7" fill="#ffffff"/>'
        f'<circle cx="3.5" cy="-6.5" r="0.7" fill="#ffffff"/>'
        f'</g>'
    )
    return (f'<g filter="url(#fShadow)">'
            f'<animateMotion dur="{dur}s" repeatCount="indefinite" rotate="auto">'
            f'<mpath xlink:href="#traj"/>'
            f'</animateMotion>{body}</g>')

def link_character(cx, cy):
    """Simplified Toon Link — green tunic, brown pants, cap, sword."""
    c = iso_cube(cx, cy, w=22, d=10)
    body = (
        # legs (pants)
        f'<rect x="{cx-5}" y="{cy+10}" width="5" height="10" fill="#3a2a10" rx="1"/>'
        f'<rect x="{cx+1}" y="{cy+10}" width="5" height="10" fill="#3a2a10" rx="1"/>'
        # tunic (body)
        f'<polygon points="{c["front"]}" fill="{PAL["link_tunic"]}"/>'
        f'<polygon points="{c["top"]}" fill="{mix(PAL["link_tunic"], "#ffffff", 0.25)}"/>'
        # cap
        f'<path d="M{cx-9},{cy-2} Q{cx-9},{cy-14} {cx},{cy-16} Q{cx+9},{cy-14} {cx+9},{cy-2} Z" '
        f'fill="#1a6a20"/>'
        f'<path d="M{cx-9},{cy-2} Q{cx},{cy-4} {cx+9},{cy-2} Z" fill="#2a8a30"/>'
        # hat brim
        f'<ellipse cx="{cx}" cy="{cy-2}" rx="10" ry="3" fill="#1a5a18"/>'
        # sword (animated - swinging)
        f'<line x1="{cx+12}" y1="{cy-2}" x2="{cx+22}" y2="{cy-14}" '
        f'stroke="#c0c0c0" stroke-width="2" stroke-linecap="round">'
        f'<animateTransform attributeName="transform" type="rotate" '
        f'values="0 {cx+12},{cy-2};12 {cx+12},{cy-2};0 {cx+12},{cy-2};-10 {cx+12},{cy-2};0 {cx+12},{cy-2}" '
        f'dur="1.6s" repeatCount="indefinite"/></line>'
        # eyes
        f'<circle cx="{cx-3}" cy="{cy-6}" r="2" fill="#1a0500"/>'
        f'<circle cx="{cx+3}" cy="{cy-6}" r="2" fill="#1a0500"/>'
        f'<circle cx="{cx-2.5}" cy="{cy-6.5}" r="0.7" fill="#ffffff"/>'
        f'<circle cx="{cx+3.5}" cy="{cy-6.5}" r="0.7" fill="#ffffff"/>'
    )
    return body

def floating_elements():
    """Bubble particles + distant seagulls for atmosphere."""
    out=[]
    # bubbles
    for bx, by, r, spd in [(60,150,3,1.5), (180,130,2,1.2), (350,160,4,1.8), (500,120,2.5,1.4), (600,140,3,1.6)]:
        out.append(f'<circle cx="{bx}" cy="{by}" r="{r}" fill="none" stroke="#8ac8e8" stroke-width="1" opacity="0.5">')
        out.append(f'<animate attributeName="cy" values="{by};{by-20};{by}" dur="{spd}s" repeatCount="indefinite"/>')
        out.append(f'<animate attributeName="opacity" values="0.5;0.2;0.5" dur="{spd}s" repeatCount="indefinite"/></circle>')
    # seagulls
    for gx, gy, spd in [(200,50,4), (400,42,5), (550,55,3.5)]:
        out.append(f'<g transform="translate({gx},{gy})" opacity="0.6">')
        out.append(f'<path d="M0,0 Q5,-3 10,0 Q5,3 0,0" fill="none" stroke="#333" stroke-width="1.2">')
        out.append(f'<animateTransform attributeName="transform" type="translate" '
                   f'values="0,0;{spd*2},-4;{spd*2},4;0,0" dur="{spd}s" repeatCount="indefinite"/></path>')
        out.append("</g>")
    return "".join(out)

def footer(left, right):
    y = H - 11
    return (f'<g font-family="\'JetBrains Mono\',monospace" font-size="12" font-weight="700">'
            f'<text x="14" y="{y}" text-anchor="start" fill="#9fb0d4">{left}</text>'
            f'<text x="{W-14}" y="{y}" text-anchor="end" fill="#6e7a99">{right}</text>'
            '</g>')

# ─── assembly ───────────────────────────────────────────────────────

def build_svg(data=None):
    weeks = (data or {}).get("weeks") or []
    repo = (data or {}).get("repo") or "zhouzxing/zhouzxing"
    total = sum(int(w.get("total",0)) for w in weeks)
    active = sum(1 for w in weeks if int(w.get("total",0))>0)
    left = f"{repo.split('/')[-1]}/  {total} commits"
    right = f"{active} 周"

    pts = build_trajectory(weeks)
    path_d = smooth_path(pts)

    p = [f'<svg width="{W}" height="{H}" fill="#c9d1d9" xmlns="http://www.w3.org/2000/svg" '
         f'xmlns:xlink="http://www.w3.org/1999/xlink" style="color-scheme: light dark" '
         f'data-dark-background="#080b16" data-light-background="#f6f8fa">']
    p.append(defs())
    p.append(plate())
    p.append(sun())
    p.append(clouds())
    p.append(islands())
    p.append(ocean_waves())
    p.append(f'<g shape-rendering="geometricPrecision">')
    # hidden trajectory path used by animateMotion
    p.append(f'<path id="traj" d="{build_path_simple(pts)}" fill="none" stroke="none"/>')
    p.append(sailboat(path_d, weeks))
    p.append("</g>")
    p.append(floating_elements())
    p.append(footer(left, right))
    p.append("</svg>")
    svg = "".join(p)
    _validate(svg)
    return svg

def _validate(svg):
    try:
        xml.dom.minidom.parseString(svg)
    except Exception as exc:
        raise SystemExit(f"ERROR: SVG not well-formed: {exc}") from exc

def load_data(path="snake_data.json"):
    if os.path.isfile(path):
        try:
            with open(path) as f:
                d = json.load(f)
            if isinstance(d, dict) and isinstance(d.get("weeks"), list):
                return d
        except Exception as exc:
            print(f"[warn] {exc}")
    return {"repo":"zhouzxing/zhouzxing","weeks":[]}

if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    data_path = os.path.join(os.path.dirname(here), "gh_probe", "probe_repo", "snake_data.json")
    data = load_data(data_path)
    svg = build_svg(data)
    out = os.path.join(here, "zelda.svg")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(svg)
    print(f"zelda.svg: {len(svg)} bytes  {W}x{H}  XML OK")
