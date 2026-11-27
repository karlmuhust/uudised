"""Local Uudised server: serves the site, keeps Karl's clicks, and runs updates on a timer.

    python -m pipeline.serve                 # http://localhost:8765, updates every 12 hours
    python -m pipeline.serve --every 6       # update every 6 hours
    python -m pipeline.serve --no-update     # just serve

Listens on 127.0.0.1 only, so nothing is reachable from other machines.
State (read / not interested) is stored in data/state.json.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import time
from datetime import datetime, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from . import run

STATE_LOCK = threading.Lock()
ID_RE = re.compile(r"^[a-f0-9]{8,40}$")


def load_state() -> dict:
    data = run.load_json(run.STATE_PATH, {})
    return {"read": data.get("read", {}), "dismissed": data.get("dismissed", {})}


def apply_action(state: dict, sid: str, action: str) -> dict:
    at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    state["read"].pop(sid, None)
    state["dismissed"].pop(sid, None)
    if action == "read":
        state["read"][sid] = at
    elif action == "dismiss":
        state["dismissed"][sid] = at
    elif action != "undo":
        raise ValueError("bad action")
    return state


class Handler(SimpleHTTPRequestHandler):
    def _json(self, body, status=200):
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def end_headers(self):
        if self.path.startswith("/data/"):
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        if self.path.split("?")[0] == "/api/state":
            with STATE_LOCK:
                return self._json(load_state())
        return super().do_GET()

    def do_POST(self):
        if self.path.split("?")[0] != "/api/state":
            return self._json({"error": "not found"}, 404)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(min(length, 10_000)) or b"{}")
            sid, action = body.get("id"), body.get("action")
            if not isinstance(sid, str) or not ID_RE.match(sid):
                return self._json({"error": "bad id"}, 400)
            with STATE_LOCK:
                state = apply_action(load_state(), sid, action)
                run.save_json(run.STATE_PATH, state)
            return self._json(state)
        except (ValueError, json.JSONDecodeError):
            return self._json({"error": "bad request"}, 400)

    def log_message(self, fmt, *args):  # keep the console quiet except for errors
        if args and str(args[1]).startswith(("4", "5")):
            super().log_message(fmt, *args)


def updater(every_hours: float) -> None:
    while True:
        try:
            print(f"[{time.strftime('%H:%M')}] Running update…", file=sys.stderr)
            run.main([])
        except Exception as exc:
            print(f"Update failed: {exc}", file=sys.stderr)
        time.sleep(every_hours * 3600)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--every", type=float, default=12.0, help="hours between updates")
    ap.add_argument("--no-update", action="store_true")
    args = ap.parse_args(argv)

    if not args.no_update:
        threading.Thread(target=updater, args=(args.every,), daemon=True).start()
    handler = partial(Handler, directory=str(run.ROOT / "site"))
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    print(f"Uudised is running at http://localhost:{args.port}  (Ctrl+C to stop)", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
