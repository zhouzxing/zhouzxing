#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
snake_activity_fetch.py
=======================
Aggregate recent weekly commit counts from several repositories and write
`snake_data.json` for `snake_gen.py`.

Why aggregate?  The profile repository `zhouzxing/zhouzxing` only receives a
few commits a year (it is a static profile page), so a snake driven by it
alone is almost always empty.  Summing the active repositories — where the
real work happens — gives a meaningful activity picture.

Repositories are listed in `REPOS` below.  Add or remove freely.

Usage
-----
    python3 snake_activity_fetch.py                # writes ./snake_data.json
    python3 snake_activity_fetch.py --print        # dry run, prints the payload

Requires network access to api.github.com and a `GH_TOKEN`/`GITHUB_TOKEN`
environment variable (a classic PAT or GitHub Actions token).  If no token is
available the script degrades gracefully to the profile repository alone.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date, timedelta
from typing import Dict, List, Optional

API = "https://api.github.com"
REPOS = [
    "zhouzxing/zhouzxing",            # profile (anchor, always included)
    "zhouzxing/infor_ai",             # AI intelligence aggregator
    "zhouzxing/python_tech_research", # python / AI research
    "zhouzxing/resume",               # resume + cultivation paths
]
WEEKS = 8                            # weeks of history to keep
_OUTPUT = "snake_data.json"


def _header() -> Dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _week_start(offset: int) -> date:
    """Monday of the week `offset` weeks before today.  0 = current week."""
    today = date.today()
    # weekday(): Monday == 0
    days_back = today.weekday()
    return today - timedelta(days=days_back + offset * 7)


def _commits_between(repo: str, since: date, until: date) -> int:
    """Count commits authored in a half-open [since, until) interval."""
    params = (
        f"since={since.isoformat()}T00:00:00Z"
        f"&until={until.isoformat()}T00:00:00Z"
        "&per_page=100"
    )
    url = f"{API}/repos/{repo}/commits?{params}"
    req = urllib_request(url, _header())
    if req is None:
        return 0
    try:
        body = req.read()
        status = req.status if hasattr(req, "status") else getattr(req, "code", 0)
    finally:
        try:
            req.close()
        except Exception:                                   # noqa: BLE001
            pass
    if status != 200:
        return 0
    try:
        return len(json.loads(body.decode("utf-8")))
    except Exception:                                      # noqa: BLE001
        return 0


def urllib_request(url: str, headers: Dict[str, str]):
    """Small wrapper so we can swap in a stub during tests."""
    import urllib.error
    import urllib.request

    req = urllib.request.Request(url, headers=headers)
    try:
        return urllib.request.urlopen(req, timeout=25)
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 429):
            print(f"[warn] rate-limited fetching {url}", file=sys.stderr)
        return None
    except Exception as exc:                               # noqa: BLE001
        print(f"[warn] {url}: {exc}", file=sys.stderr)
        return None


def fetch_repo(repo: str) -> Optional[List[Dict]]:
    """Return per-week commit counts (newest first) for one repository."""
    out: List[Dict] = []
    for offset in range(WEEKS, -1, -1):
        since = _week_start(offset)
        until = _week_start(offset - 1)
        total = _commits_between(repo, since, until)
        out.append({"week": int(since.strftime("%Y%W")), "total": total})
        time.sleep(0.25)                                   # be gentle
    return out


def build_payload() -> Dict:
    """Aggregate every configured repo into one week-aligned series."""
    aggregated: Dict[int, int] = {}
    anchor_name = REPOS[0]

    for repo in REPOS:
        weeks = fetch_repo(repo)
        if weeks is None:
            print(f"[warn] {repo}: unavailable, skipped", file=sys.stderr)
            continue
        repo_total = sum(w["total"] for w in weeks)
        print(f"  {repo:<34} {repo_total:>4} commits")
        for w in weeks:
            aggregated[w["week"]] = aggregated.get(w["week"], 0) + w["total"]

    series = [
        {"week": week, "total": aggregated[week]}
        for week in sorted(aggregated.keys())
    ]
    # Newest last, matching what snake_gen.py expects internally.
    series.sort(key=lambda w: w["week"])

    return {
        "repo": anchor_name,
        "repos": list(REPOS),
        "weeks": series,
        "fetched_at": date.today().isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--print", action="store_true", dest="show",
                        help="print the payload instead of writing it")
    args = parser.parse_args()

    print(f"Aggregating {WEEKS} weeks from {len(REPOS)} repos ...")
    payload = build_payload()

    total = sum(w["total"] for w in payload["weeks"])
    active = sum(1 for w in payload["weeks"] if w["total"] > 0)
    print(f"Total: {total} commits over {active} active weeks")

    if args.show:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    with open(_OUTPUT, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    print(f"[ok] wrote {_OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
