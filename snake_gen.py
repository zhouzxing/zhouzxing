#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
snake_gen.py
============
Generate the GitHub README commit-activity "snake" animation SVG.

Self-contained: no third-party dependencies.  The layout matches the canonical
`github-readme-stats/README-snake` output (a 13×46 heatmap grid covered by an
animated snake body and a following head), but the SVG is produced locally so
the README never depends on an external stats service.

Usage
-----
    python3 snake_gen.py                 # writes ./snake.svg, prints a summary
    python3 snake_gen.py README.md path # embed the SVG into an existing markdown file

Data source, in order of preference
-----------------------------------
1. `./snake_data.json` produced by `snake_activity_fetch.py`
   (aggregated weekly commit counts, as returned by the GitHub REST API).
2. A small hard-coded fallback so the README always renders something.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Layout constants
# ---------------------------------------------------------------------------
COLS = 46                      # cells per row
ROWS = 13                      # rows of the heatmap
CELL_W = CELL_H = 8            # one cell is 8px wide/tall
GRID_GAP = 6                   # spacing between the title and the grid
PAD = 10
PAD_BOTTOM = 26

SNAKE_CELLS = 511              # how many cells the body path covers
SNAKE_HEAD_CELLS = 89          # hidden path cells ahead of the visible head

TITLE_H = 20                   # reserved height for the title line
FOOTER_OFFSET = 11             # distance of the footer text from the grid bottom

# Monospace glyph metrics used to lay out the footer line.
FONT_CHAR_W = 6.4
FONT_CHAR_H = 12.0
FONT_CHAR_GAP = 0.5

GRID_W = COLS * CELL_W + (COLS - 1) * GRID_GAP + 2 * PAD
GRID_H = ROWS * CELL_H + (ROWS - 1) * GRID_GAP + 2 * PAD + 4
X_OFF = PAD - (ROWS + 2)
Y_OFF = TITLE_H + GRID_GAP + PAD - (COLS + 2)
BODY_H = GRID_H + 26


# ---------------------------------------------------------------------------
# Default data (used when no fetched data file is present)
# ---------------------------------------------------------------------------
_DEFAULT_REPO_NAME = "zhouzxing/zhouzxing"
# ISO-8601 week numbers of the most recent 8 weeks (UTC) + aggregated commits.
_DEFAULT_WEEKS: List[Tuple[int, int]] = [
    (-7, 0), (-6, 0), (-5, 0), (-4, 0),
    (-3, 1), (-2, 1), (-1, 4), (0, 2),
]


def _iso_weeks(back: List[int]) -> List[int]:
    """Return opaque ordering keys for the given week offsets from *today*."""
    today = datetime.now(timezone.utc).date()
    out = []
    for offset in back:
        d = today + timedelta(days=offset * 7)
        y, w, _ = d.isocalendar()
        out.append(w * 100 + y)          # opaque ordering key
    return out


def _default_data() -> Dict:
    offsets = [offset for offset, _ in _DEFAULT_WEEKS]
    weeks = _iso_weeks(offsets)
    return {
        "repo": _DEFAULT_REPO_NAME,
        "weeks": [
            {"week": weeks[i], "total": total}
            for i, (_, total) in enumerate(_DEFAULT_WEEKS)
        ],
    }


def load_data(path: str = "snake_data.json") -> Dict:
    """Load aggregated activity data, falling back to the default set."""
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict) and isinstance(data.get("weeks"), list):
                return data
        except Exception as exc:                       # noqa: BLE001
            print(f"[warn] cannot load {path}: {exc}", file=sys.stderr)
    return _default_data()


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------
def cell_positions() -> List[List[int]]:
    """Position of the top-left corner of every cell, row by row."""
    positions = []
    for y in range(ROWS):
        row = []
        for x in range(COLS):
            row.append([x * (CELL_W + GRID_GAP) + X_OFF,
                        y * (CELL_H + GRID_GAP) + Y_OFF])
        positions.append(row)
    return positions


def week_cells(data: Dict, max_weeks: int = 100) -> List[int]:
    """Flatten weekly totals into a per-week cell count list.

    A week with `n` commits contributes up to 53 cells (a full GitHub
    contribution week); the list is padded with zeros to at least *max_weeks*.
    """
    weeks = list(reversed(data.get("weeks") or []))[:max_weeks]
    counts: List[int] = [min(53, max(0, int(w.get("total", 0)))) for w in weeks]
    while len(counts) < max_weeks:
        counts.append(0)
    return counts


def build_path(positions: List[List[int]], visible: int = SNAKE_CELLS) -> str:
    """Build the SVG path string the snake body follows."""
    total_cells = ROWS * COLS
    cells: List[List[int]] = []
    idx = 0
    for row in range(ROWS):
        for col in range(COLS):
            if idx < visible:
                cells.append(positions[row][col])
            idx += 1
            if idx >= total_cells:
                break
        if idx >= total_cells:
            break

    path = [f"M{cells[0][0]}{cells[0][1]}"]
    for a, b in zip(cells, cells[1:]):
        path.append(f"V{b[1]}")
        path.append(f"H{b[0]}")
    path.append(f"V{positions[ROWS - 1][0][1]}")
    for row in range(ROWS):
        for col in range(COLS):
            if (row, col) != (ROWS - 1, 0):
                path.append(f"H{positions[row][col][0]}")
                path.append(f"V{positions[row][col][1]}")
    return "".join(path)


def footer_parts(data: Dict) -> Tuple[str, str]:
    """Return (left_text, right_text) for the footer line.

    Left text is anchored at the left edge, right text at the right edge.
    No manual glyph-width computation is needed — the SVG renderer lays out
    each text element natively.
    """
    repo = data.get("repo") or _DEFAULT_REPO_NAME
    total = sum(int(w.get("total", 0)) for w in data.get("weeks") or [])
    active = sum(1 for w in data.get("weeks") or [] if int(w.get("total", 0)) > 0)
    repo_short = repo.split('/')[-1]
    left = f"{repo_short}/  {total} commits"
    right = f"{active} 周"
    return left, right


# ---------------------------------------------------------------------------
# SVG assembly
# ---------------------------------------------------------------------------
def _grid_rects(weeks: List[int]) -> str:
    cells = week_cells({"weeks": [{"total": c} for c in weeks]})
    parts: List[str] = []
    for row in range(ROWS):
        parts.append(f'<g transform="translate(0,{row * (CELL_H + GRID_GAP)})">')
        for col in range(COLS):
            parts.append(
                f'<rect fill="none" stroke="#0e6479" stroke-width="2" '
                f'rx="4" x="{col * (CELL_W + GRID_GAP)}" y="0" width="8" height="8"></rect>'
            )
        parts.append("</g>")
    return "".join(parts)


# Palette (GitHub contribution-green ramp, tuned for dark mode)
_COLOR = {
    "title_a": "#5cc862",   # title gradient top
    "title_b": "#1a8f3a",   # title gradient bottom
    "grid_a":  "#56d364",   # grid cell fill top
    "grid_b":  "#1e6f51",   # grid cell fill bottom
    "body_a":  "#39c561",   # snake body gradient top
    "body_b":  "#0e6479",   # snake body gradient bottom
    "head_a":  "#56d364",   # head highlight
    "head_b":  "#238636",   # head edge
    "grid_stroke": "#0e6479",
    "footer": "#586076",
}

_LG = '<linearGradient id="{id}" x2="0" y2="100%"><stop stop-color="{a}" stop-opacity="{oa}" offset="0"/><stop stop-color="{b}" stop-opacity="{ob}" offset="1"/></linearGradient>'


def _gradient_defs() -> str:
    """Gradient definitions that adapt to GitHub's dark mode.

    Built by plain concatenation (not str.format) so that literal ``#`` in
    colour literals is never confused with a format placeholder.
    """
    c = _COLOR
    parts = ["<defs>"]

    # grid cell fill
    parts.append(_LG.format(id="b", a=c["grid_a"], b=c["grid_b"], oa="0.4", ob="0.4"))
    # snake body
    parts.append(_LG.format(id="c", a=c["body_a"], b=c["body_b"], oa="1", ob="1"))
    # title
    parts.append(_LG.format(id="d", a=c["title_a"], b=c["title_b"], oa="1", ob="1"))
    # head (radial)
    parts.append(
        f'<radialGradient id="j" cx="50%" cy="50%" r="50%">'
        f'<stop stop-color="{c["head_a"]}" stop-opacity="1" offset="0"/>'
        f'<stop stop-color="{c["head_b"]}" stop-opacity="1" offset="1"/>'
        "</radialGradient>"
    )
    # light background
    parts.append(_LG.format(id="h", a="#fffef5", b="#d2e2e7", oa="0.08", ob="0.08"))
    # dark background
    parts.append(_LG.format(id="i", a="#0d1117", b="#161b22", oa="0.08", ob="0.08"))

    parts.append("</defs>")
    return "".join(parts)


def build_svg(data: Dict) -> str:
    """Render the complete snake SVG document."""
    repo = data.get("repo") or _DEFAULT_REPO_NAME
    total = sum(int(w.get("total", 0)) for w in data.get("weeks") or [])
    active = sum(1 for w in data.get("weeks") or [] if int(w.get("total", 0)) > 0)

    positions = cell_positions()
    path = build_path(positions)
    foot_left, foot_right = footer_parts(data)

    # Theme attributes live on the root element.  Nesting them inside
    # style="..." needs escaped quotes and turns the document into invalid
    # XML, which GitHub silently drops (the image just does not render).
    root_attrs = (
        ' data-dark-background="#0d1117" data-light-background="#f6f8fa"'
        if total > 0 else ''
    )

    parts: List[str] = []
    parts.append(
        f'<svg width="{GRID_W}" height="{GRID_H}" fill="#c9d1d9" '
        f'xmlns="http://www.w3.org/2000/svg" '
        f'xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'style="color-scheme: light dark"{root_attrs}>'
    )
    parts.append(_gradient_defs())

    # background plate
    parts.append(
        f'<rect width="100%" height="100%" rx="8" fill="url(#h)"></rect>'
        f'<rect width="100%" height="100%" rx="8" fill="url(#i)"></rect>'
    )

    # grid
    parts.append('<g fill="#20262c">')
    parts.append(_grid_rects([0] * (ROWS * COLS)))
    parts.append("</g>")

    # body
    parts.append(
        f'<g stroke="url(#c)" stroke-width="2" fill="none" fill-rule="evenodd">'
        f'<path id="snake-body" d="{path}" stroke-linejoin="round"></path>'
        "</g>"
    )

    # head (following the body)
    parts.append(
        '<g fill="url(#j)">'
        '<circle r="5" cx="0" cy="0">'
        '<animate attributeName="cx" values="0;-40" begin="0s" dur="4s" '
        'repeatCount="indefinite"></animate>'
        '<animate attributeName="cy" values="0;40" begin="0s" dur="4s" '
        'repeatCount="indefinite"></animate>'
        "</circle>"
        '<animateMotion dur="40s" repeatCount="indefinite" rotate="auto">'
        '<mpath xlink:href="#snake-body"></mpath>'
        "</animateMotion>"
        "</g>"
    )

    # footer — two natively-anchored text elements (no glyph-width math)
    foot_y = GRID_H - FOOTER_OFFSET
    parts.append(
        '<g font-family="\'JetBrains Mono\',\'Fira Code\',monospace" '
        f'font-size="{FONT_CHAR_H}" font-weight="600" fill="#586076">'
        f'<text x="{PAD + 2}" y="{foot_y}" text-anchor="start">{foot_left}</text>'
        f'<text x="{GRID_W - PAD - 2}" y="{foot_y}" text-anchor="end">{foot_right}</text>'
        "</g>"
    )

    parts.append("</svg>")
    svg_text = "".join(parts)

    # Sanity check: GitHub drops an invalid SVG silently, so a broken document
    # would look like "the snake vanished".  Fail loudly instead of emitting it.
    _validate_xml(svg_text)
    return svg_text


def _validate_xml(svg_text: str) -> None:
    """Raise if the SVG is not well-formed XML.

    Well-formedness is what matters here: an unescaped ``"`` inside an
    attribute value (say, a ``data-*`` attribute spliced into ``style="..."``)
    is a well-formedness error, and GitHub's sanitizer will refuse to render
    such an image at all.
    """
    import xml.dom.minidom

    try:
        xml.dom.minidom.parseString(svg_text)
    except Exception as exc:                                   # noqa: BLE001
        raise SystemExit(f"ERROR: generated SVG is not well-formed XML: {exc}") from exc


def embed_svg(markdown_path: str, svg_path: str) -> bool:
    """Replace an existing embedded snake SVG inside *markdown_path*."""
    with open(markdown_path, encoding="utf-8") as fh:
        md = fh.read()
    marker = "<!-- BEGIN snake -->"
    start = md.find(marker)
    if start < 0:
        return False
    end = md.find("<!-- END snake -->", start)
    if end < 0:
        return False
    end += len("<!-- END snake -->")
    with open(svg_path, encoding="utf-8") as fh:
        svg = fh.read()
    new = md[:start] + marker + "\n" + svg + "\n<!-- END snake -->" + md[end:]
    with open(markdown_path, "w", encoding="utf-8") as fh:
        fh.write(new)
    return True


def main() -> int:
    svg_path = "snake.svg"
    data = load_data()

    svg = build_svg(data)
    with open(svg_path, "w", encoding="utf-8") as fh:
        fh.write(svg)

    total = sum(int(w.get("total", 0)) for w in data.get("weeks") or [])
    active = sum(1 for w in data.get("weeks") or [] if int(w.get("total", 0)) > 0)
    print(f"[ok] wrote {svg_path}: {len(svg)} bytes")
    print(f"     {data.get('repo', '?')} | {total} commits over {active} active weeks")
    print(f"     size {GRID_W}x{GRID_H}px")

    if len(sys.argv) > 1 and sys.argv[1] != "snake.svg":
        md = sys.argv[1]
        if os.path.isfile(md) and embed_svg(md, svg_path):
            print(f"[ok] embedded SVG into {md}")
        elif os.path.isfile(md):
            print(f"[warn] {md} has no snake markers; embed it manually")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
