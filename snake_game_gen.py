#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
snake_game_gen.py
=================
Turn the commit history into a **playable-looking snake game** rendered as a
self-contained animated SVG (`snake_game.svg`).

What it does
------------
1. Reads `snake_game_data.json` (from `snake_game_fetch.py`) — one record per
   commit.  Falls back to `snake_data.json` weekly totals, then to a tiny
   built-in sample, so the generator never produces an empty banner.
2. Drops one **food dot per commit** on the contribution grid.  The cell is
   derived from the commit hash, so it is stable across runs but looks random.
3. Simulates a snake that **runs the board and eats the dots**: it starts far
   from every dot, routes to the dots one after another (L-shaped legs, like
   the classic game), and returns home so the animation loops seamlessly.
4. Bakes the whole replay into SMIL — the only animation GitHub keeps inside
   an `<img>` SVG (it strips `<script>`):
   * head      — `<animateMotion>` along the route, `rotate="auto"`
   * body      — a moving `stroke-dasharray` window on the route path
   * food dot  — staggered fade-in, then a "gulp" pop and fade-out on the
                 frame the head arrives

Geometry, palette and the 3D head are the ones already used by `snake.svg`,
so the two banners look like siblings.

Usage
-----
    python3 snake_game_gen.py                # writes ./snake_game.svg
    python3 snake_game_gen.py --preview 12   # also writes static frames
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import xml.dom.minidom
from collections import OrderedDict
from typing import Dict, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Layout (identical to the existing snake.svg)
# ---------------------------------------------------------------------------
COLS, ROWS = 46, 13
PITCH = 14                      # distance between two cell origins
CELL = 10                       # cell body size
GRID_X0, GRID_Y0 = 12, 32       # top-left corner of cell (0, 0)
PAD_LEFT = 12
WIDTH, HEIGHT = 664, 240
UNDERLAY = (8, 28, 648, 186)    # x, y, w, h of the grid backing plate

SNAKE_CELLS = 7                 # visible body length, in cells
Z = CELL / 2.0                  # cell centre offset

# replay pacing
TARGET_LOOP = 56.0              # seconds for one full replay
MIN_STEP, MAX_STEP = 0.028, 0.140
SPAWN_GAP = 0.42                # cascade stagger between dots
MIN_VISIBLE = 1.6               # a dot stays visible at least this long

OUTPUT = "snake_game.svg"
DATA_FILE = "snake_game_data.json"
FALLBACK_DATA = "snake_data.json"

REPO_COLORS = {
    "zhouzxing/zhouzxing": "#4dd8ff",
    "zhouzxing/infor_ai": "#ff5fa8",
    "zhouzxing/python_tech_research": "#b06bff",
    "zhouzxing/resume": "#7cf29b",
}
PALETTE = ["#4dd8ff", "#ff5fa8", "#b06bff", "#7cf29b", "#ffd166", "#ff8f6b"]

# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
_SAMPLE = [
    {"repo": "zhouzxing/zhouzxing", "sha": "a1b2c3d4e5", "date": "2026-09-01T10:00:00Z", "subject": "docs"},
    {"repo": "zhouzxing/infor_ai", "sha": "b2c3d4e5f6", "date": "2026-09-08T10:00:00Z", "subject": "feat"},
    {"repo": "zhouzxing/zhouzxing", "sha": "c3d4e5f6a7", "date": "2026-09-15T10:00:00Z", "subject": "fix"},
    {"repo": "zhouzxing/resume", "sha": "d4e5f6a7b8", "date": "2026-09-22T10:00:00Z", "subject": "update"},
    {"repo": "zhouzxing/python_tech_research", "sha": "e5f6a7b8c9", "date": "2026-09-29T10:00:00Z", "subject": "notes"},
]


def load_commits() -> Tuple[List[Dict], str]:
    """Return (commits, source_description)."""
    if os.path.isfile(DATA_FILE):
        try:
            with open(DATA_FILE, encoding="utf-8") as fh:
                payload = json.load(fh)
            commits = [c for c in payload.get("commits") or []
                       if isinstance(c, dict) and c.get("repo")]
            if commits:
                commits.sort(key=lambda c: c.get("date", ""))
                return commits, DATA_FILE
        except Exception as exc:                            # noqa: BLE001
            print(f"[warn] cannot read {DATA_FILE}: {exc}", file=sys.stderr)

    # Fall back to the weekly totals the original fetcher produces.
    if os.path.isfile(FALLBACK_DATA):
        try:
            with open(FALLBACK_DATA, encoding="utf-8") as fh:
                payload = json.load(fh)
            repos = payload.get("repos") or ["zhouzxing/zhouzxing"]
            commits: List[Dict] = []
            for w in payload.get("weeks") or []:
                for i in range(min(int(w.get("total", 0)), 53)):
                    repo = repos[(int(w.get("week", 0)) + i) % len(repos)]
                    commits.append({
                        "repo": repo,
                        "sha": hashlib.sha1(f"{w.get('week')}-{i}".encode()).hexdigest()[:10],
                        "date": str(w.get("week", "")),
                        "subject": "",
                    })
            if commits:
                return commits, f"{FALLBACK_DATA} (weekly totals)"
        except Exception as exc:                            # noqa: BLE001
            print(f"[warn] cannot read {FALLBACK_DATA}: {exc}", file=sys.stderr)

    return list(_SAMPLE), "built-in sample"


def color_for(repo: str, index: int = 0) -> str:
    if repo in REPO_COLORS:
        return REPO_COLORS[repo]
    return PALETTE[index % len(PALETTE)]


# ---------------------------------------------------------------------------
# Board simulation
# ---------------------------------------------------------------------------
def cell_center(cell: Tuple[int, int]) -> Tuple[int, int]:
    c, r = cell
    return (int(GRID_X0 + PITCH * c + Z), int(GRID_Y0 + PITCH * r + Z))


def dist(a: Tuple[int, int], b: Tuple[int, int]) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def place_foods(commits: Sequence[Dict]) -> List[Dict]:
    """Give every commit a stable, collision-free cell on the grid.

    The cell comes from the commit hash, so it looks random but never moves
    between runs (the same commit always eats the same square).
    """
    foods: List[Dict] = []
    occupied = set()
    for idx, cm in enumerate(commits):
        salt = 0
        while True:
            digest = hashlib.sha256(
                f"{cm.get('repo')}|{cm.get('sha')}|{idx}|{salt}".encode()).digest()
            cell = (((digest[0] << 8) | digest[1]) % COLS,
                    ((digest[2] << 8) | digest[3]) % ROWS)
            if cell not in occupied:
                occupied.add(cell)
                break
            salt += 1
        foods.append({
            "repo": cm.get("repo", ""),
            "sha": cm.get("sha", ""),
            "date": cm.get("date", ""),
            "subject": cm.get("subject", ""),
            "cell": cell,
            "color": color_for(cm.get("repo", ""), idx),
        })
    return foods


def leg(a: Tuple[int, int], b: Tuple[int, int]) -> List[Tuple[int, int]]:
    """L-shaped run of cells from *a* to *b* (horizontal first)."""
    out: List[Tuple[int, int]] = []
    c, r = a
    sc = 1 if b[0] > c else -1
    while c != b[0]:
        c += sc
        out.append((c, r))
    sr = 1 if b[1] > r else -1
    while r != b[1]:
        r += sr
        out.append((c, r))
    return out


def build_route(start, order, foods) -> List[Tuple[int, int]]:
    route = [start]
    cur = start
    for i in order:
        target = foods[i]["cell"]
        if target != cur:
            route.extend(leg(cur, target))
            cur = target
    if cur != start:                       # close the loop -> seamless restart
        route.extend(leg(cur, start))
    return route


def choose_start(foods) -> Tuple[int, int]:
    """Start as far as possible from every dot: a long, readable first run."""
    occupied = {f["cell"] for f in foods}
    best, best_d = (0, ROWS - 1), -1
    for r in range(ROWS):
        for c in range(COLS):
            if (c, r) in occupied:
                continue
            d = min((dist((c, r), f["cell"]) for f in foods), default=0)
            if d > best_d:
                best_d, best = d, (c, r)
    return best


def simulate(foods):
    """Return (route, eat_index_per_food, order_used)."""
    if not foods:
        start = (0, ROWS - 1)
        return [start, (1, ROWS - 1), start], [], "none"

    start = choose_start(foods)
    chrono = list(range(len(foods)))
    sweep = sorted(chrono, key=lambda i: (
        foods[i]["cell"][1],
        foods[i]["cell"][0] if foods[i]["cell"][1] % 2 == 0 else -foods[i]["cell"][0],
    ))

    candidates = []
    for name, order in (("chrono", chrono), ("sweep", sweep)):
        route = build_route(start, order, foods)
        candidates.append((len(route), name, order, route))
    candidates.sort(key=lambda t: t[0])
    _m, name, order, route = candidates[0]

    # first time the snake stands on each dot
    first_visit: Dict[Tuple[int, int], int] = {}
    for idx, cell in enumerate(route):
        if idx and cell not in first_visit:
            first_visit[cell] = idx
    eats = [first_visit.get(f["cell"], len(route) - 1) for f in foods]
    return route, eats, name


# ---------------------------------------------------------------------------
# SVG helpers
# ---------------------------------------------------------------------------
def _f(v: float, nd: int = 4) -> str:
    return f"{v:.{nd}f}".rstrip("0").rstrip(".") or "0"


def grid_markup() -> str:
    """The pixel-bevel cube grid (same recipe as snake.svg)."""
    parts: List[str] = ['<g shape-rendering="crispEdges">']
    for r in range(ROWS):
        y = GRID_Y0 + PITCH * r
        for c in range(COLS):
            x = GRID_X0 + PITCH * c
            parts.append(
                f'<rect x="{x}" y="{y}" width="10" height="10" rx="2.5" fill="url(#gCell)" '
                f'stroke="#08152a" stroke-width="0.8"/>'
                f'<rect x="{x + 0.9}" y="{y + 0.9}" width="8.2" height="2" rx="1" fill="#5ba8d8" opacity="0.95"/>'
                f'<rect x="{x + 0.9}" y="{y + 0.9}" width="1.7" height="8.2" rx="0.8" fill="#4088b8" opacity="0.85"/>'
                f'<rect x="{x + 7.4}" y="{y + 0.9}" width="1.7" height="8.2" rx="0.8" fill="#12355a" opacity="0.9"/>'
                f'<rect x="{x + 0.9}" y="{y + 7.1}" width="8.2" height="2" rx="1" fill="#0a1e38" opacity="0.92"/>'
            )
    parts.append("</g>")
    return "".join(parts)


def food_markup(food: Dict, spawn_t: float, eat_t: float, loop: float) -> str:
    """One commit dot: staggered fade-in, gulp-pop and fade-out when eaten."""
    eps = 1e-4
    k1 = min(max(spawn_t / loop, 0.0), 0.985)
    gap = max(eat_t - spawn_t, 0.05)
    fade_in = min(0.32, gap * 0.35)
    fade_out = min(0.45, gap * 0.6)
    k2 = min(max((spawn_t + fade_in) / loop, k1 + eps), 0.99)
    k4 = min(max(eat_t / loop, k2 + eps), 0.9985)
    k5 = min(max((eat_t + fade_out) / loop, k4 + eps), 0.9999)
    pop = min(max((eat_t + 0.22) / loop, k4 + eps), 1.0)

    x, y = cell_center(food["cell"])
    color = food["color"]
    title = f"{food['repo']}@{food['sha'][:8]} {food['date'][:10]}"
    return (
        f'<g transform="translate({x},{y})" opacity="0">'
        f'<title>{_esc(title)}</title>'
        f'<animate attributeName="opacity" dur="{_f(loop, 3)}s" repeatCount="indefinite" '
        f'values="0;0;1;1;0;0" '
        f'keyTimes="0;{_f(k1)};{_f(k2)};{_f(k4)};{_f(k5)};1"/>'
        f'<g>'
        f'<animateTransform attributeName="transform" type="scale" '
        f'dur="{_f(loop, 3)}s" repeatCount="indefinite" '
        f'values="1;1;1.9;1" keyTimes="0;{_f(k4)};{_f(pop)};1"/>'
        f'<circle r="6.6" fill="{color}" opacity="0.22"/>'
        f'<rect x="-3.6" y="-3.6" width="7.2" height="7.2" rx="2" fill="{color}"/>'
        f'<rect x="-3.6" y="-3.6" width="7.2" height="2.2" rx="1" fill="#ffffff" opacity="0.5"/>'
        f'</g></g>'
    )


_HEAD_SHAPES = (
    '<ellipse cx="0" cy="11" rx="17" ry="4" fill="#000000" opacity="0.55" filter="url(#fSoft)"/>'
    '<ellipse cx="0" cy="0" rx="23" ry="18" fill="url(#gHeadGlow)" opacity="0.85"/>'
    '<polygon points="-13.0,-5.5 -9.5,-12.5 7.5,-12.5 11.0,-5.5" fill="url(#gHeadTop)" stroke="#3a2a00" stroke-width="1" stroke-linejoin="round"/>'
    '<polygon points="-13.0,-5.5 11.0,-5.5 11.0,8.5 -13.0,8.5" fill="url(#gHeadFront)" stroke="#3a2a00" stroke-width="1" stroke-linejoin="round"/>'
    '<polygon points="11.0,-5.5 7.5,-12.5 7.5,1.5 11.0,8.5" fill="url(#gHeadRight)" stroke="#3a2a00" stroke-width="1" stroke-linejoin="round"/>'
    '<polygon points="-13.0,-5.5 -9.5,-12.5 -9.5,-8.4 -13.0,-1.4" fill="#ffffff" opacity="0.6"/>'
    '<polygon points="-9.5,-12.5 7.5,-12.5 6.4,-10.8 -10.6,-10.8" fill="#fffbe0" opacity="0.6"/>'
    '<circle cx="-5.8" cy="0.8" r="3.1" fill="url(#gEye)" stroke="#3a2a00" stroke-width="0.6"/>'
    '<circle cx="-4.95" cy="-0.1" r="0.95" fill="#ffffff" opacity="0.95"/>'
    '<circle cx="3.9" cy="0.8" r="3.1" fill="url(#gEye)" stroke="#3a2a00" stroke-width="0.6"/>'
    '<circle cx="4.75" cy="-0.1" r="0.95" fill="#ffffff" opacity="0.95"/>'
    '<circle cx="-0.9" cy="4.6" r="1.9" fill="#ffe880" opacity="0.9"/>'
)


def head_markup(loop: float, lead_seconds: float) -> str:
    return (
        '<g>' + _HEAD_SHAPES +
        '<animate attributeName="opacity" values="1;0.92;1" dur="1.4s" repeatCount="indefinite"/>'
        f'<animateMotion dur="{_f(loop, 3)}s" begin="-{_f(lead_seconds, 3)}s" '
        f'repeatCount="indefinite" rotate="auto">'
        '<mpath xlink:href="#snake-route"/>'
        '</animateMotion></g>'
    )


def body_markup(path_d: str, window: float, route_len: float, loop: float) -> str:
    """Multi-layer stroke body; a moving dash window is the snake itself."""
    dash = f'{_f(window, 1)} {_f(max(route_len - window, 1.0), 1)}'
    timing = (f'<animate attributeName="stroke-dashoffset" dur="{_f(loop, 3)}s" '
              f'repeatCount="indefinite" values="{_f(route_len, 1)};0" '
              f'calcMode="linear"/>')
    layers = [
        ("#000000", 3.0, 1.0),
        ("#072833", 3.6, 1.0),
        ("url(#gBody)", 3.0, 1.0),
        ("#ffe8b0", 1.4, 0.8),
        ("#fff8e0", 0.7, 1.0),
    ]
    parts = [f'<path id="snake-route" d="{path_d}" fill="none"/>']
    for stroke, width, opa in layers:
        parts.append(
            f'<path d="{path_d}" fill="none" stroke="{stroke}" stroke-width="{width}" '
            f'stroke-linecap="round" stroke-linejoin="round" opacity="{opa}" '
            f'stroke-dasharray="{dash}">{timing}</path>'
        )
    return "".join(parts)


def _esc(s: str) -> str:
    return (str(s) if s is not None else "").replace("&", "&amp;").replace("<", "&lt;") \
        .replace(">", "&gt;").replace('"', "&quot;")


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------
DEFS = (
    '<defs>'
    '<radialGradient id="gAmbient" cx="50%" cy="42%" r="62%">'
    '<stop offset="0%" stop-color="#3c738e" stop-opacity="0.42"/>'
    '<stop offset="55%" stop-color="#1a5a7a" stop-opacity="0.12"/>'
    '<stop offset="100%" stop-color="#0a0e1a" stop-opacity="0"/></radialGradient>'
    '<linearGradient id="gPlate" x1="0" y1="0" x2="0" y2="1">'
    '<stop offset="0%" stop-color="#1c2332"/><stop offset="100%" stop-color="#0a0e1a"/></linearGradient>'
    '<linearGradient id="gCell" x1="0" y1="0" x2="0" y2="1">'
    '<stop offset="0%" stop-color="#2e6ea4"/><stop offset="100%" stop-color="#20598a"/></linearGradient>'
    '<linearGradient id="gBody" x1="0" y1="0" x2="0" y2="1">'
    '<stop offset="0%" stop-color="#ffdf80"/><stop offset="50%" stop-color="#ff9840"/>'
    '<stop offset="100%" stop-color="#ee8536"/></linearGradient>'
    '<linearGradient id="gHalo" x1="0" y1="0" x2="0" y2="1">'
    '<stop offset="0%" stop-color="#ffb84a" stop-opacity="0.95"/>'
    '<stop offset="100%" stop-color="#c85a20" stop-opacity="0.45"/></linearGradient>'
    '<linearGradient id="gHeadTop" x1="0" y1="0" x2="0" y2="1">'
    '<stop offset="0%" stop-color="#fff7c8"/><stop offset="100%" stop-color="#fff4a8"/></linearGradient>'
    '<linearGradient id="gHeadFront" x1="0" y1="0" x2="0" y2="1">'
    '<stop offset="0%" stop-color="#ffdd63"/><stop offset="100%" stop-color="#b29734"/></linearGradient>'
    '<linearGradient id="gHeadRight" x1="0" y1="0" x2="0" y2="1">'
    '<stop offset="0%" stop-color="#d7a832"/><stop offset="100%" stop-color="#7b5d13"/></linearGradient>'
    '<radialGradient id="gEye" cx="50%" cy="36%" r="62%">'
    '<stop offset="0%" stop-color="#ffffff"/><stop offset="38%" stop-color="#1a0512"/>'
    '<stop offset="100%" stop-color="#000000"/></radialGradient>'
    '<radialGradient id="gHeadGlow" cx="50%" cy="42%" r="55%">'
    '<stop offset="0%" stop-color="#ffe880" stop-opacity="0.9"/>'
    '<stop offset="100%" stop-color="#ffe880" stop-opacity="0"/></radialGradient>'
    '<filter id="fSoft" filterUnits="userSpaceOnUse" x="-60" y="-60" width="784" height="360">'
    '<feGaussianBlur stdDeviation="3"/></filter>'
    '</defs>'
)


def build_svg(commits: List[Dict], source: str) -> str:
    foods = place_foods(commits)
    route, eats, order = simulate(foods)

    moves = max(len(route) - 1, 1)
    step = min(MAX_STEP, max(MIN_STEP, TARGET_LOOP / moves))
    loop = moves * step
    window = SNAKE_CELLS * PITCH
    route_len = moves * PITCH
    if window >= route_len:                    # degenerate short route
        window = max(PITCH, route_len * 0.5)

    pts = [cell_center(cell) for cell in route]
    path_d = f"M{pts[0][0]},{pts[0][1]}" + "".join(f"L{x},{y}" for x, y in pts[1:])

    # ── food dots ────────────────────────────────────────────────────────
    dot_parts: List[str] = []
    for i, food in enumerate(foods):
        eat_t = eats[i] * step
        spawn_t = max(min(i * SPAWN_GAP, eat_t - MIN_VISIBLE), 0.05)
        if eat_t - spawn_t < 0.9:              # never let a dot vanish instantly
            spawn_t = max(eat_t - MIN_VISIBLE, 0.05)
        dot_parts.append(food_markup(food, spawn_t, eat_t, loop))

    # ── legend + captions ────────────────────────────────────────────────
    used: "OrderedDict[str, int]" = OrderedDict()
    for f in foods:
        used[f["repo"]] = used.get(f["repo"], 0) + 1
    legend_items = list(used.items())
    if len(legend_items) > 4:                  # keep the strip inside the plate
        rest = sum(n for _r, n in legend_items[4:])
        legend_items = legend_items[:4] + [("其他", rest)]
    legend: List[str] = []
    for idx, (repo, count) in enumerate(legend_items):
        x = PAD_LEFT + idx * 118
        color = REPO_COLORS.get(repo, PALETTE[idx % len(PALETTE)])
        label = repo.split("/")[-1] if "/" in repo else repo
        if len(label) > 14:                    # keep the strip clear of the caption
            label = label[:13] + "…"
        legend.append(
            f'<circle cx="{x + 3.5}" cy="225.5" r="3.5" fill="{color}"/>'
            f'<text x="{x + 12}" y="229" text-anchor="start" fill="#9fb0d4">'
            f'{_esc(label)} {count}</text>'
        )

    total = len(foods)
    repos_n = len(used)
    title = (f'commit-snake · {total} commits · {repos_n} repos '
             f'· 自动重放')
    foot_right = '每个点 = 1 次 commit'

    body = body_markup(path_d, window, route_len, loop)
    head = head_markup(loop, SNAKE_CELLS * step)

    parts: List[str] = []
    parts.append(
        f'<svg width="{WIDTH}" height="{HEIGHT}" fill="#c9d1d9" '
        f'xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'style="color-scheme: light dark" data-dark-background="#0a0e1a" '
        f'data-light-background="#f6f8fa">'
    )
    parts.append(DEFS)
    parts.append(f'<rect width="{WIDTH}" height="{HEIGHT}" fill="#0a0e1a"/>')
    parts.append(f'<rect width="{WIDTH}" height="{HEIGHT}" rx="10" fill="url(#gAmbient)"/>')
    parts.append(f'<rect x="0.75" y="0.75" width="{WIDTH - 1.5}" height="{HEIGHT - 1.5}" '
                 f'rx="9.25" fill="none" stroke="#1a2b4a" stroke-width="1" opacity="0.85"/>')
    parts.append(f'<rect x="{UNDERLAY[0]}" y="{UNDERLAY[1]}" width="{UNDERLAY[2]}" '
                 f'height="{UNDERLAY[3]}" rx="6" fill="#0a0e1a"/>')
    parts.append(grid_markup())
    parts.append('<g>' + "".join(dot_parts) + '</g>')
    parts.append('<g>' + body + '</g>')
    parts.append(head)
    parts.append(
        '<g font-family="\'JetBrains Mono\',\'Fira Code\',monospace" font-size="11" '
        'font-weight="700">'
        f'<text x="{PAD_LEFT}" y="19" text-anchor="start" fill="#7f8fb3">{title}</text>'
        + "".join(legend) +
        f'<text x="{WIDTH - PAD_LEFT}" y="229" text-anchor="end" fill="#6e7a99">'
        f'{foot_right}</text>'
        '</g>'
    )
    parts.append('</svg>')
    svg = "".join(parts)

    validate(svg)
    meta = {
        "commits": total,
        "repos": repos_n,
        "dots": len(foods),
        "moves": moves,
        "loop_seconds": round(loop, 2),
        "order": order,
        "source": source,
    }
    return svg, meta


def validate(svg: str) -> None:
    """Fail loudly: GitHub silently drops an SVG it cannot parse."""
    try:
        xml.dom.minidom.parseString(svg)
    except Exception as exc:                                # noqa: BLE001
        raise SystemExit(f"ERROR: generated SVG is not well-formed XML: {exc}") from exc
    if len(svg) > 900_000:
        raise SystemExit(f"ERROR: SVG too large ({len(svg)} bytes) — GitHub may strip SMIL")
    for needle in ('id="snake-route"', "<animateMotion", 'xlink:href="#snake-route"'):
        if needle not in svg:
            raise SystemExit(f"ERROR: expected markup missing: {needle}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=OUTPUT, help=f"output path (default {OUTPUT})")
    args = ap.parse_args()

    commits, source = load_commits()
    print(f"[snake-game] {len(commits)} commits from {source}")

    svg, meta = build_svg(commits, source)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(svg)

    print(f"[ok] wrote {args.out}: {len(svg):,} bytes")
    print(f"     {meta['dots']} dots · {meta['moves']} moves · "
          f"loop {meta['loop_seconds']}s · order={meta['order']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
