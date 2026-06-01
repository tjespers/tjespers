#!/usr/bin/env python3
"""
gen-stack.py — generate a custom "tech stack" SVG card from techstack.yaml.

Why this exists: GitHub strips <style>/class/style= from README markdown, so you
can't use CSS/Tailwind there. But CSS embedded *inside an SVG file* renders fine.
This script builds that SVG for you, so you only ever edit techstack.yaml.

Usage:
    python3 scripts/gen-stack.py

Outputs:
    assets/stack-dark.svg   (for GitHub dark theme)
    assets/stack-light.svg  (for GitHub light theme)

Reference them in the README with a <picture> so each theme gets the right one:

    <picture>
      <source media="(prefers-color-scheme: dark)"  srcset="assets/stack-dark.svg">
      <source media="(prefers-color-scheme: light)" srcset="assets/stack-light.svg">
      <img alt="Tech stack" src="assets/stack-dark.svg" width="860">
    </picture>

Brand icons + their colors are fetched once from Simple Icons
(https://cdn.simpleicons.org) and cached under assets/.icons/ so later runs work
offline. Pills wrap automatically to fit the card width, with an optional
theme.max_per_row cap.
"""
from __future__ import annotations
import re
import sys
import urllib.request
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("PyYAML is required:  pip install pyyaml")

ROOT = Path(__file__).resolve().parent.parent
CFG = ROOT / "techstack.yaml"
ASSETS = ROOT / "assets"
ICON_CACHE = ASSETS / ".icons"

# ── layout constants ──────────────────────────────────────────────────────────
PAD_X = 28          # left/right padding
PAD_TOP = 14        # top padding
HEADER_H = 40       # space for a domain title
PILL_H = 32         # pill height
PILL_ROW_H = PILL_H + 10   # vertical step between wrapped pill rows
DOMAIN_GAP = 26     # gap below a domain block
GAP = 12            # gap between pills on a row
ICON = 16           # icon size in px
ICON_GAP = 7        # gap between icon and label
PILL_PAD = 14       # horizontal padding inside a pill

# Two palettes. Per-domain accent colors come from techstack.yaml.
THEMES = {
    "dark":  {"bg": "#0d1117", "pill_alpha": "1f", "text": "#c9d1d9"},
    "light": {"bg": "#ffffff", "pill_alpha": "14", "text": "#1f2328"},
}


def fetch(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "gen-stack/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8")


def get_icon(slug: str) -> tuple[str | None, str | None]:
    """Return (path_d, brand_hex) for a Simple Icons slug. Cached on disk.

    cdn.simpleicons.org returns e.g.:
        <svg fill="#326CE5" ...><title>Kubernetes</title><path d="..."/></svg>
    so we read both the icon geometry and its official brand color in one go.
    """
    cache = ICON_CACHE / f"{slug}.svg"
    if cache.exists():
        svg = cache.read_text()
    else:
        svg = ""
        for url in (
            f"https://cdn.simpleicons.org/{slug}",
            f"https://unpkg.com/simple-icons@latest/icons/{slug}.svg",
        ):
            try:
                svg = fetch(url)
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(svg)
                break
            except Exception:
                continue
        if not svg:
            print(f"  ! icon '{slug}' not found — pill will render without an icon")
            return None, None
    pm = re.search(r'<path[^>]*\bd="([^"]+)"', svg)
    cm = re.search(r'\bfill="(#[0-9A-Fa-f]{3,6})"', svg)
    return (pm.group(1) if pm else None), (cm.group(1) if cm else None)


def est_text_width(label: str, size: int = 13) -> float:
    w = 0.0
    for ch in label:
        if ch.isupper():
            w += size * 0.66
        elif ch in " .":
            w += size * 0.30
        else:
            w += size * 0.55
    return w


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{max(0,min(255,r)):02x}{max(0,min(255,g)):02x}{max(0,min(255,b)):02x}"


def clamp_visible(hex_color: str, theme_name: str) -> str:
    """Nudge a color so it stays readable against the theme background.

    On dark themes, lift very-dark brand colors (e.g. GitHub #181717) toward
    white; on light themes, deepen very-pale colors. Hue is preserved — we only
    mix toward white/black until a luminance threshold is met.
    """
    try:
        r, g, b = _hex_to_rgb(hex_color)
    except Exception:
        return hex_color
    lum = 0.299 * r + 0.587 * g + 0.114 * b  # 0 dark … 255 light
    if theme_name == "dark":
        floor = 110
        if lum < floor:
            t = min(0.85, (floor - lum) / 255 * 1.8)
            r, g, b = (round(c + (255 - c) * t) for c in (r, g, b))
    else:  # light
        ceil = 175
        if lum > ceil:
            t = min(0.85, (lum - ceil) / 255 * 1.8)
            r, g, b = (round(c * (1 - t)) for c in (r, g, b))
    return _rgb_to_hex(r, g, b)


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_svg(cfg: dict, theme_name: str) -> str:
    theme = THEMES[theme_name]
    tcfg = cfg.get("theme", {}) or {}
    W = int(tcfg.get("width", 860))
    icon_mode = tcfg.get("icon_color", "brand")   # brand | white | accent
    pill_mode = tcfg.get("pill_color", "brand")   # brand | accent
    max_per_row = int(tcfg.get("max_per_row", 0)) or None  # 0/absent = width-only wrap
    domains = cfg["domains"]
    avail = W - 2 * PAD_X      # usable width for pills

    # ── Pass 1: resolve each pill (icon path/color + measured width) and wrap
    # pills into lines so nothing overflows the card width or the row cap. ─────
    def resolve(dom):
        accent = dom["accent"]
        pills = []
        for it in dom["items"]:
            slug = it.get("icon")
            path, brand_hex = (get_icon(slug) if slug else (None, None))
            brand = clamp_visible(it.get("color") or brand_hex or accent, theme_name)
            if icon_mode == "white":
                icol = it.get("color") or theme["text"]
            elif icon_mode == "accent":
                icol = it.get("color") or accent
            else:
                icol = brand
            pill_color = brand if pill_mode == "brand" else accent
            icon_w = (ICON + ICON_GAP) if path else 0
            w = int(PILL_PAD * 2 + icon_w + est_text_width(it["label"]))
            pills.append({
                "label": it["label"], "path": path, "icon_color": icol,
                "pill_color": pill_color, "w": w,
            })
        lines, line, lw = [], [], 0
        for p in pills:
            too_wide = line and lw + p["w"] > avail
            too_many = max_per_row and len(line) >= max_per_row
            if too_wide or too_many:
                lines.append(line)
                line, lw = [], 0
            line.append(p)
            lw += p["w"] + GAP
        if line:
            lines.append(line)
        return accent, lines

    resolved = [resolve(d) for d in domains]
    H = PAD_TOP + sum(HEADER_H + len(lines) * PILL_ROW_H + DOMAIN_GAP
                      for _, lines in resolved) + 6

    out: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}" role="img" aria-label="Tech stack">'
    ]
    css = [
        "text{font-family:'Segoe UI',Ubuntu,Helvetica,Arial,sans-serif;}",
        ".band{font-weight:700;font-size:15px;}",
        f".pt{{font-weight:600;font-size:13px;fill:{theme['text']};}}",
        ".row{animation:rise .55s ease both;}",
    ]
    for i in range(len(domains)):
        css.append(f".r{i}{{animation-delay:{0.02 + i*0.1:.2f}s}}")
    css.append("@keyframes rise{from{opacity:.2;transform:translateY(6px)}"
               "to{opacity:1;transform:none}}")
    out.append("<defs><style>" + "".join(css) + "</style></defs>")
    out.append(f'<rect x="0" y="0" width="{W}" height="{H}" rx="16" fill="{theme["bg"]}"/>')

    # ── Pass 2: emit each domain at its computed y offset ─────────────────────
    y = PAD_TOP
    for i, (dom, (accent, lines)) in enumerate(zip(domains, resolved)):
        out.append(f'<g class="row r{i}">')
        out.append(
            f'  <text class="band" fill="{accent}" x="{PAD_X}" y="{y+26}">'
            f'{esc(dom.get("emoji",""))}  {esc(dom["name"])}</text>'
        )
        py = y + HEADER_H
        for line in lines:
            x = PAD_X
            for p in line:
                out.append(
                    f'  <rect x="{x}" y="{py}" width="{p["w"]}" height="{PILL_H}" rx="8" '
                    f'fill="{p["pill_color"] + theme["pill_alpha"]}" '
                    f'stroke="{p["pill_color"]}" stroke-width="1.3"/>'
                )
                tx = x + PILL_PAD
                if p["path"]:
                    scale = ICON / 24.0
                    iy = py + (PILL_H - ICON) / 2
                    out.append(
                        f'  <g transform="translate({tx},{iy:.1f}) scale({scale:.4f})">'
                        f'<path d="{p["path"]}" fill="{p["icon_color"]}"/></g>'
                    )
                    tx += ICON + ICON_GAP
                out.append(f'  <text class="pt" x="{tx}" y="{py+21}">{esc(p["label"])}</text>')
                x += p["w"] + GAP
            py += PILL_ROW_H
        out.append("</g>")
        y = py + DOMAIN_GAP

    out.append("</svg>")
    return "\n".join(out)


def main() -> None:
    if not CFG.exists():
        sys.exit(f"Config not found: {CFG}")
    cfg = yaml.safe_load(CFG.read_text())
    ASSETS.mkdir(exist_ok=True)
    for theme_name in ("dark", "light"):
        svg = build_svg(cfg, theme_name)
        out = ASSETS / f"stack-{theme_name}.svg"
        out.write_text(svg)
        print(f"✓ wrote {out.relative_to(ROOT)}  ({len(svg)} bytes)")
    print("Done. Reference them in the README with a <picture> element (see script header).")


if __name__ == "__main__":
    main()
