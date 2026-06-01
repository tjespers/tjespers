#!/usr/bin/env python3
"""
gen-stats.py — generate a custom GitHub "stats" SVG card, fully self-owned.

Why this exists: the popular third-party stats services (github-readme-stats,
etc.) go down or rate-limit constantly — at time of writing the public instance
returns 503 DEPLOYMENT_PAUSED. Like the tech-stack card, we render our own SVG
from data we pull straight from the GitHub GraphQL API, so nothing on the
profile depends on someone else's uptime.

Usage:
    python3 scripts/gen-stats.py

Auth: uses $GITHUB_TOKEN if set (e.g. in CI), otherwise `gh auth token`.

Outputs:
    assets/stats-dark.svg
    assets/stats-light.svg

Reference in the README with a <picture> for theme-swapping (see stack card).
"""
from __future__ import annotations
import datetime as _dt
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
USER = "tjespers"
START_YEAR = 2015  # account created Aug 2015

# tokyonight-ish palette; tiles each get their own accent
THEMES = {
    "dark":  {"bg": "#0d1117", "tile": "#161b22", "stroke": "#21262d",
              "num": "#e6edf3", "label": "#8b949e"},
    "light": {"bg": "#ffffff", "tile": "#f6f8fa", "stroke": "#d0d7de",
              "num": "#1f2328", "label": "#59636e"},
}
ACCENTS = ["#7aa2f7", "#bb9af7", "#9ece6a", "#e0af68"]


def token() -> str:
    t = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if t:
        return t
    try:
        return subprocess.check_output(["gh", "auth", "token"], text=True).strip()
    except Exception:
        sys.exit("No token: set $GITHUB_TOKEN or run `gh auth login`.")


def gql(query: str, tok: str) -> dict:
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query}).encode(),
        headers={"Authorization": f"bearer {tok}",
                 "User-Agent": "gen-stats/1.0",
                 "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        out = json.load(r)
    if "errors" in out:
        sys.exit(f"GraphQL error: {out['errors']}")
    return out["data"]


def fetch_stats(tok: str) -> dict:
    this_year = _dt.date.today().year
    lifetime = 0
    days: dict[str, int] = {}
    for y in range(START_YEAR, this_year + 1):
        d = gql(
            f'{{ user(login:"{USER}"){{ contributionsCollection('
            f'from:"{y}-01-01T00:00:00Z", to:"{y}-12-31T23:59:59Z"){{ '
            f'contributionCalendar{{ totalContributions weeks{{ contributionDays'
            f'{{ date contributionCount }} }} }} }} }} }}', tok)
        cc = d["user"]["contributionsCollection"]["contributionCalendar"]
        lifetime += cc["totalContributions"]
        for w in cc["weeks"]:
            for cd in w["contributionDays"]:
                days[cd["date"]] = cd["contributionCount"]
        if y == this_year:
            year_total = cc["totalContributions"]

    # longest streak
    longest = cur = 0
    prev = None
    for ds in sorted(days):
        dt = _dt.date.fromisoformat(ds)
        if days[ds] > 0:
            cur = cur + 1 if (prev and (dt - prev).days == 1) else 1
            longest = max(longest, cur)
            prev = dt
        else:
            prev = None

    meta = gql(f'{{ user(login:"{USER}"){{ repositories(ownerAffiliations:OWNER,'
               f' isFork:false){{ totalCount }} createdAt }} }}', tok)
    repos = meta["user"]["repositories"]["totalCount"]
    created = _dt.date.fromisoformat(meta["user"]["createdAt"][:10])
    years = _dt.date.today().year - created.year

    return {"years": years, "lifetime": lifetime, "year_total": year_total,
            "longest": longest, "repos": repos}


def human(n: int) -> str:
    if n >= 1000:
        return f"{n/1000:.1f}k".replace(".0k", "k")
    return str(n)


def build_svg(stats: dict, theme_name: str) -> str:
    t = THEMES[theme_name]
    W, H = 860, 150
    pad, gap = 28, 16
    tiles = [
        ("🗓️", f"{stats['years']}+", "years on GitHub"),
        ("⚡", human(stats["lifetime"]), "contributions"),
        ("📈", human(stats["year_total"]), "this year"),
        ("🔥", str(stats["longest"]), "longest streak"),
    ]
    n = len(tiles)
    tw = (W - 2 * pad - (n - 1) * gap) / n
    th = H - 2 * pad

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
           f'viewBox="0 0 {W} {H}" role="img" aria-label="GitHub stats">']
    css = [
        "text{font-family:'Segoe UI',Ubuntu,Helvetica,Arial,sans-serif;}",
        f".num{{font-weight:800;font-size:32px;fill:{t['num']};text-anchor:middle;}}",
        f".lab{{font-weight:600;font-size:13px;fill:{t['label']};text-anchor:middle;}}",
        ".emoji{{font-size:18px;text-anchor:middle;}}".replace("{{", "{").replace("}}", "}"),
        ".tile{animation:rise .5s ease both;}",
    ]
    for i in range(n):
        css.append(f".t{i}{{animation-delay:{0.05 + i*0.08:.2f}s}}")
    css.append("@keyframes rise{from{opacity:0;transform:translateY(8px)}"
               "to{opacity:1;transform:none}}")
    out.append("<defs><style>" + "".join(css) + "</style></defs>")
    out.append(f'<rect width="{W}" height="{H}" rx="16" fill="{t["bg"]}"/>')

    for i, (emoji, num, lab) in enumerate(tiles):
        x = pad + i * (tw + gap)
        cx = x + tw / 2
        accent = ACCENTS[i % len(ACCENTS)]
        out.append(f'<g class="tile t{i}">')
        out.append(f'  <rect x="{x:.1f}" y="{pad}" width="{tw:.1f}" height="{th}" '
                   f'rx="12" fill="{t["tile"]}" stroke="{t["stroke"]}" stroke-width="1"/>')
        out.append(f'  <rect x="{x:.1f}" y="{pad}" width="4" height="{th}" rx="2" fill="{accent}"/>')
        out.append(f'  <text class="emoji" x="{cx:.1f}" y="{pad+34}">{emoji}</text>')
        out.append(f'  <text class="num" x="{cx:.1f}" y="{pad+72}">{num}</text>')
        out.append(f'  <text class="lab" x="{cx:.1f}" y="{pad+96}">{lab}</text>')
        out.append('</g>')
    out.append("</svg>")
    return "\n".join(out)


def main() -> None:
    tok = token()
    print("· fetching stats from GitHub…")
    stats = fetch_stats(tok)
    print(f"  {stats}")
    ASSETS.mkdir(exist_ok=True)
    for theme_name in ("dark", "light"):
        svg = build_svg(stats, theme_name)
        (ASSETS / f"stats-{theme_name}.svg").write_text(svg)
        print(f"✓ wrote assets/stats-{theme_name}.svg")


if __name__ == "__main__":
    main()
