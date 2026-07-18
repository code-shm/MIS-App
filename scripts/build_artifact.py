"""Produce a body-only artifact page (style + markup + inlined data).

The Artifact host wraps the file in its own <!doctype/html/head/body>, so this
strips index.html's document wrapper and keeps the <style>, the <body> content,
and the scripts — with data.json inlined so the page is fully self-contained.
"""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
HTML = ROOT / "dashboards" / "html" / "index.html"
DATA = ROOT / "dashboards" / "html" / "data.json"
OUT = ROOT / "dashboards" / "html" / "_artifact_body.html"


def main() -> int:
    if not DATA.exists():
        print("data.json missing — run the pipeline first.")
        return 1
    html = HTML.read_text(encoding="utf-8")
    data = DATA.read_text(encoding="utf-8")

    style = re.search(r"<style>.*?</style>", html, re.S).group(0)
    body = re.search(r"<body>(.*?)</body>", html, re.S).group(1)
    body = body.replace('<script src="data.js"></script>',
                        f"<script>window.DASHBOARD_DATA = {data};</script>")

    OUT.write_text(style + "\n" + body, encoding="utf-8")
    print(f"Wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size/1024:,.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
