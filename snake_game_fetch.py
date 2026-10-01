#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
snake_game_fetch.py
===================
Fetch **individual commit records** (one entry per commit) from the active
repositories and write `snake_game_data.json` for `snake_game_gen.py`.

Why a second fetcher?  `snake_activity_fetch.py` only keeps a weekly *count*
per repo — enough to colour a heatmap, but not enough to place one "food" dot
per commit.  The commit snake eats one dot per commit, so it needs the records
themselves: repo, sha, author date and subject.

The original scripts are untouched; this is an additive companion.

Usage
-----
    python3 snake_game_fetch.py             # writes ./snake_game_data.json
    python3 snake_game_fetch.py --print     # dry run, print the payload

Auth: `GH_TOKEN` / `GITHUB_TOKEN` (optional locally, injected in Actions).
Without a token the script still tries — it just runs into the anonymous
rate limit sooner.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date
from typing import Dict, List, Optional

API = "https://api.github.com"

# Same repository set as snake_activity_fetch.py.  Read from snake_data.json
# when it exists so the two scripts can never drift apart.
DEFAULT_REPOS = [
    "zhouzxing/zhouzxing",            # profile (anchor, always included)
    "zhouzxing/infor_ai",             # AI intelligence aggregator
    "zhouzxing/python_tech_research", # python / AI research
    "zhouzxing/resume",               # resume + cultivation paths
]
PER_PAGE = 100                        # commits per repo (newest first)
MAX_COMMITS = 120                     # total dots kept, newest kept first
_OUTPUT = "snake_game_data.json"


def repos() -> List[str]:
    """Repository list — prefers the one the original fetcher already used."""
    try:
        with open("snake_data.json", encoding="utf-8") as fh:
            data = json.load(fh)
        listed = [r for r in data.get("repos") or [] if isinstance(r, str)]
        if listed:
            return listed
    except Exception:                                       # noqa: BLE001
        pass
    return list(DEFAULT_REPOS)


def _header() -> Dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _request(url: str):
    import urllib.error
    import urllib.request

    req = urllib.request.Request(url, headers=_header())
    try:
        return urllib.request.urlopen(req, timeout=25)
    except urllib.error.HTTPError as exc:
        print(f"[warn] HTTP {exc.code} fetching {url}", file=sys.stderr)
        return None
    except Exception as exc:                                # noqa: BLE001
        print(f"[warn] {url}: {exc}", file=sys.stderr)
        return None


def fetch_commits(repo: str) -> List[Dict]:
    """Return this repo's commit records, oldest first."""
    url = f"{API}/repos/{repo}/commits?per_page={PER_PAGE}"
    resp = _request(url)
    if resp is None:
        return []
    try:
        body = resp.read()
    finally:
        try:
            resp.close()
        except Exception:                                   # noqa: BLE001
            pass

    try:
        raw = json.loads(body.decode("utf-8"))
    except Exception as exc:                                # noqa: BLE001
        print(f"[warn] {repo}: unreadable payload ({exc})", file=sys.stderr)
        return []
    if not isinstance(raw, list):
        return []

    out: List[Dict] = []
    for item in raw:
        try:
            commit = item.get("commit") or {}
            meta = commit.get("author") or commit.get("committer") or {}
            when = (meta.get("date") or "").strip()
            if not when:
                continue
            subject = (commit.get("message") or "").splitlines()[0].strip()
            out.append({
                "repo": repo,
                "sha": (item.get("sha") or "")[:10],
                "date": when,
                "subject": subject[:120],
            })
        except Exception:                                   # noqa: BLE001
            continue
    out.sort(key=lambda c: c["date"])
    return out


def build_payload() -> Dict:
    repo_list = repos()
    anchor = repo_list[0]
    commits: List[Dict] = []

    for repo in repo_list:
        records = fetch_commits(repo)
        print(f"  {repo:<34} {len(records):>4} commits")
        commits.extend(records)
        time.sleep(0.25)                                    # be gentle

    # newest kept first when trimming, but the game replays them oldest-first
    commits.sort(key=lambda c: c["date"])
    if len(commits) > MAX_COMMITS:
        commits = commits[-MAX_COMMITS:]

    return {
        "repo": anchor,
        "repos": repo_list,
        "commits": commits,
        "fetched_at": date.today().isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--print", action="store_true", dest="show",
                        help="print the payload instead of writing it")
    args = parser.parse_args()

    print(f"Fetching commit records from {len(repos())} repos ...")
    payload = build_payload()

    commits = payload["commits"]
    print(f"Total: {len(commits)} commits "
          f"({commits[0]['date'][:10] if commits else '-'} .. "
          f"{commits[-1]['date'][:10] if commits else '-'})")

    if args.show:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    with open(_OUTPUT, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    print(f"[ok] wrote {_OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
