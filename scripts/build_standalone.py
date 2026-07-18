"""Inline data.json into index.html -> a single self-contained dashboard file.

The result (dashboards/html/amex_dashboard_standalone.html) needs no web server
and no data.js sidecar: double-click it and it renders. Handy for sharing the
dashboard as one artifact.
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
HTML = ROOT / "dashboards" / "html" / "index.html"
DATA = ROOT / "dashboards" / "html" / "data.json"
OUT = ROOT / "dashboards" / "html" / "amex_dashboard_standalone.html"


def main() -> int:
    if not DATA.exists():
        print("data.json not found — run `python -m src.pipeline` first.")
        return 1
    html = HTML.read_text(encoding="utf-8")
    data = DATA.read_text(encoding="utf-8")
    inline = f"<script>window.DASHBOARD_DATA = {data};</script>"
    # Inline the scorer assets + code so the Live Scorer works with no server
    # (lazy loadScript() over file:// is blocked; pre-defining the globals skips it).
    for name in ("states_geo.js", "scorer_assets.js", "scorer.js"):
        p = ROOT / "dashboards" / "html" / name
        if p.exists():
            inline += f"\n<script>{p.read_text(encoding='utf-8')}</script>"
    html = html.replace('<script src="data.js"></script>', inline)
    OUT.write_text(html, encoding="utf-8")
    print(f"Wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size/1024:,.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
