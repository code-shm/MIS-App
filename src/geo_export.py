"""Bake US state geometry into a self-contained JS asset for the map.

Fetches the us-atlas **pre-projected** (Albers USA) states TopoJSON once, decodes
it to per-state SVG path strings keyed by 2-letter code, and writes
``dashboards/html/states_geo.js`` (``window.US_STATES_GEO``). Because the atlas
is already in screen pixels, no runtime projection or external library is needed
— the choropleth stays CSP-safe and works offline / on Vercel.

    python -m src.geo_export
"""
from __future__ import annotations

import json

import requests

from . import config

SRC = "https://cdn.jsdelivr.net/npm/us-atlas@3/states-albers-10m.json"
OUT = config.ROOT / "dashboards" / "html" / "states_geo.js"

FIPS_ABBR = {
    "01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA", "08": "CO",
    "09": "CT", "10": "DE", "11": "DC", "12": "FL", "13": "GA", "15": "HI",
    "16": "ID", "17": "IL", "18": "IN", "19": "IA", "20": "KS", "21": "KY",
    "22": "LA", "23": "ME", "24": "MD", "25": "MA", "26": "MI", "27": "MN",
    "28": "MS", "29": "MO", "30": "MT", "31": "NE", "32": "NV", "33": "NH",
    "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND", "39": "OH",
    "40": "OK", "41": "OR", "42": "PA", "44": "RI", "45": "SC", "46": "SD",
    "47": "TN", "48": "TX", "49": "UT", "50": "VT", "51": "VA", "53": "WA",
    "54": "WV", "55": "WI", "56": "WY", "72": "PR",
}


def _decode_arcs(topo):
    sx, sy = topo["transform"]["scale"]
    tx, ty = topo["transform"]["translate"]
    decoded = []
    for arc in topo["arcs"]:
        x = y = 0
        pts = []
        for dx, dy in arc:
            x += dx; y += dy
            pts.append((round(x * sx + tx, 1), round(y * sy + ty, 1)))
        decoded.append(pts)
    return decoded


def _ring_points(arc_indices, arcs):
    pts = []
    for idx in arc_indices:
        a = arcs[~idx][::-1] if idx < 0 else arcs[idx]
        pts.extend(a if not pts else a[1:])  # drop shared endpoint
    return pts


def _path_d(geom, arcs) -> str:
    polys = geom["arcs"] if geom["type"] == "MultiPolygon" else [geom["arcs"]]
    d = []
    for poly in polys:
        for ring in poly:
            pts = _ring_points(ring, arcs)
            if len(pts) < 2:
                continue
            d.append("M" + "L".join(f"{x},{y}" for x, y in pts) + "Z")
    return "".join(d)


def build() -> dict:
    print(f"[geo] Fetching {SRC} ...")
    topo = requests.get(SRC, timeout=120).json()
    arcs = _decode_arcs(topo)

    xs, ys = [], []
    for a in arcs:
        for x, y in a:
            xs.append(x); ys.append(y)
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    pad = 8
    view = f"{minx - pad:.0f} {miny - pad:.0f} {maxx - minx + 2 * pad:.0f} {maxy - miny + 2 * pad:.0f}"

    paths = {}
    for g in topo["objects"]["states"]["geometries"]:
        abbr = FIPS_ABBR.get(g.get("id"))
        if not abbr:
            continue
        paths[abbr] = _path_d(g, arcs)

    payload = {"viewBox": view, "paths": paths}
    OUT.write_text("window.US_STATES_GEO = " + json.dumps(payload, separators=(",", ":")) + ";\n",
                   encoding="utf-8")
    print(f"[geo] Wrote {OUT.relative_to(config.ROOT)} ({OUT.stat().st_size/1024:,.0f} KB) "
          f"| {len(paths)} states | viewBox {view}")
    return payload


if __name__ == "__main__":
    build()
