"""Agentic dashboard server.

Serves the live dashboard and keeps it fresh:

  * static files from ``dashboards/html/`` (the dashboard itself),
  * ``GET  /api/status``  — current version stamp + whether a refresh is running,
  * ``POST /api/refresh`` — trigger a refresh now (``?retrain=1`` to retrain),
  * a background thread that auto-refreshes every ``--interval`` minutes.

The dashboard polls ``/api/status`` and reloads its data when the version stamp
changes — so new complaints appear without touching the page, and the "Refresh
now" button lets you pull on demand.

    python -m src.serve                      # serve + auto-refresh every 60 min
    python -m src.serve --interval 15        # every 15 minutes
    python -m src.serve --no-auto            # serve only; refresh via the button
    python -m src.serve --port 8000
"""
from __future__ import annotations

import argparse
import json
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from . import config, refresh as refresh_mod

HTML_DIR = config.ROOT / "dashboards" / "html"

# Shared refresh state guarded by a lock so a manual trigger and the auto loop
# never run the pipeline concurrently.
_state = {"running": False, "last": None, "last_error": None}
_lock = threading.Lock()


def _do_refresh(retrain: bool = False) -> None:
    with _lock:
        if _state["running"]:
            print("[serve] Refresh already in progress — skipping.")
            return
        _state["running"] = True
    try:
        _state["last"] = refresh_mod.refresh(retrain=retrain)
        _state["last_error"] = None
    except Exception as exc:  # noqa: BLE001 — surface, don't crash the server
        _state["last_error"] = f"{type(exc).__name__}: {exc}"
        print(f"[serve] Refresh failed: {_state['last_error']}")
    finally:
        _state["running"] = False


class Handler(SimpleHTTPRequestHandler):
    def _json(self, code: int, obj: dict) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        route = self.path.split("?")[0]
        if route == "/api/status":
            vf = HTML_DIR / "version.json"
            version = json.loads(vf.read_text()) if vf.exists() else {}
            return self._json(200, {"running": _state["running"],
                                    "error": _state["last_error"], "version": version})
        if route == "/api/report.pdf":
            return self._serve_report()
        return super().do_GET()

    def _serve_report(self):
        try:
            from . import report
            pdf = report.build()          # regenerate from the current data.json
            data = pdf.read_bytes()
        except Exception as exc:  # noqa: BLE001
            return self._json(500, {"error": f"{type(exc).__name__}: {exc}"})
        self.send_response(200)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Content-Disposition",
                         'attachment; filename="amex_executive_report.pdf"')
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):  # noqa: N802
        if self.path.split("?")[0] == "/api/refresh":
            retrain = "retrain=1" in self.path
            if _state["running"]:
                return self._json(202, {"status": "already_running"})
            threading.Thread(target=_do_refresh, kwargs={"retrain": retrain}, daemon=True).start()
            return self._json(202, {"status": "started", "retrain": retrain})
        self.send_error(404)

    def log_message(self, fmt, *args):  # quieter logs; keep refresh prints
        if "/api/" in (self.path if hasattr(self, "path") else ""):
            super().log_message(fmt, *args)


def _auto_loop(interval_min: int) -> None:
    while True:
        time.sleep(interval_min * 60)
        print(f"[serve] Auto-refresh tick (every {interval_min} min).")
        _do_refresh(retrain=False)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Serve the live agentic dashboard")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--interval", type=int, default=60, help="Auto-refresh interval (minutes)")
    ap.add_argument("--no-auto", action="store_true", help="Disable the auto-refresh loop")
    ap.add_argument("--refresh-on-start", action="store_true", help="Refresh immediately at startup")
    args = ap.parse_args(argv)

    if args.refresh_on_start or not (HTML_DIR / "version.json").exists():
        print("[serve] Initial refresh ...")
        _do_refresh(retrain=False)

    if not args.no_auto:
        threading.Thread(target=_auto_loop, args=(args.interval,), daemon=True).start()

    handler = partial(Handler, directory=str(HTML_DIR))
    httpd = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    url = f"http://localhost:{args.port}/index.html"
    print("\n" + "=" * 60)
    print(f"  Amex Complaints dashboard is LIVE  ->  {url}")
    print(f"  Auto-refresh: {'off' if args.no_auto else f'every {args.interval} min'}"
          "  |  Manual: the 'Refresh now' button, or POST /api/refresh")
    print("  Ctrl+C to stop.")
    print("=" * 60 + "\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[serve] Stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
