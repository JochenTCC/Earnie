"""Pilot step 0 (spike/vo-push-pilot): show exactly what a Loxone Virtual Output sends.

Dumb capture listener — answers 204 to everything and prints one line per
request (time, delta to the previous request on the same path, method, path,
selected headers, body). Use it to check, with the real Miniserver, what
"Befehl bei EIN" + repeat produce: method, value format of ``\\v`` (decimal
separator, unit), repeat interval, and behaviour on changes.

Usage (PC in the LAN, port free):

    python -m scripts.pilot_vo_capture --port 8599 [--out capture.jsonl]

VO address in Loxone Config: ``http://<this-PC-IP>:8599``; command e.g.
``/ehal/loxone/telemetry/sens_ess_soc/\\v`` (repeat 30 s).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

_last_seen: dict[str, float] = {}
_out_path: str | None = None
_SHOW_HEADERS = ("Content-Type", "X-Earnie-Token", "Authorization", "User-Agent", "Host")


class _CaptureHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return

    def _capture(self) -> None:
        now = time.time()
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode("utf-8", "replace") if length > 0 else ""
        # Signal key = path without the last segment (the value), so the interval is
        # comparable even when every push carries a different value.
        key = self.path.rsplit("/", 1)[0] if "/" in self.path.lstrip("/") else self.path
        delta = now - _last_seen[key] if key in _last_seen else None
        _last_seen[key] = now
        record = {
            "ts": datetime.now().isoformat(timespec="milliseconds"),
            "delta_s": None if delta is None else round(delta, 2),
            "value": unquote(self.path.rsplit("/", 1)[-1]).split("?", 1)[0],
            "method": self.command,
            "path": self.path,
            "peer": self.client_address[0],
            "headers": {k: self.headers.get(k) for k in _SHOW_HEADERS if self.headers.get(k)},
            "body": body,
        }
        print(json.dumps(record, ensure_ascii=False), flush=True)
        if _out_path:
            with open(_out_path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        self.send_response(204)
        self.end_headers()

    do_GET = do_POST = do_PUT = _capture  # noqa: N815


def main() -> int:
    global _out_path
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--port", type=int, default=8599)
    parser.add_argument("--out", default="", help="optional JSONL file to append to")
    args = parser.parse_args()
    _out_path = args.out or None
    server = ThreadingHTTPServer(("0.0.0.0", args.port), _CaptureHandler)
    print(f"capture listening on 0.0.0.0:{args.port} (Ctrl+C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
