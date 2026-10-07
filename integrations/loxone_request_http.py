"""Minimal Loxone → Earnie HTTP (Request Optimize, alive, Pattern B status.json)."""
from __future__ import annotations

import hmac
import json
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable
from urllib.parse import parse_qs, unquote, urlparse

logger = logging.getLogger(__name__)

REQUEST_OPTIMIZE_PATH = "/ehal/loxone/request_optimize"
ALIVE_PATH = "/ehal/loxone/alive"
STATUS_PATH = "/ehal/loxone/status.json"
# Pilot (spike/vo-push-pilot): Virtual Output push, observation only.
TELEMETRY_PREFIX = "/ehal/loxone/telemetry/"
PUSH_TOKEN_ENV = "EARNIE_PILOT_PUSH_TOKEN"
PUSH_TOKEN_HEADER = "X-Earnie-Token"


def _normalize_path(raw_path: str) -> str:
    path = urlparse(raw_path).path.rstrip("/") or "/"
    return path

_optimize_event = threading.Event()
_server: ThreadingHTTPServer | None = None
_thread: threading.Thread | None = None
_lock = threading.Lock()


def optimize_request_event() -> threading.Event:
    return _optimize_event


def signal_optimize_request() -> None:
    _optimize_event.set()


def clear_optimize_request() -> None:
    _optimize_event.clear()


def consume_optimize_request() -> bool:
    """Return True once if a request was pending; clear the event."""
    if not _optimize_event.is_set():
        return False
    _optimize_event.clear()
    return True


class _LoxoneRequestHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A003
        logger.debug("loxone_request_http: " + format, *args)

    def _record_peer(self) -> None:
        try:
            from runtime_store.loxone_callback_status import record_loxone_callback

            peer = self.client_address[0] if self.client_address else ""
            record_loxone_callback(peer)
        except Exception:  # noqa: BLE001 — never fail the Miniserver callback path
            logger.exception("loxone_request_http: failed to record last callback")

    def do_GET(self) -> None:  # noqa: N802
        path = _normalize_path(self.path)
        if path == ALIVE_PATH.rstrip("/") or path == ALIVE_PATH:
            self._record_peer()
            self.send_response(204)
            self.end_headers()
            return
        if path == STATUS_PATH.rstrip("/") or path == STATUS_PATH:
            self._record_peer()
            from integrations.loxone_status_json import build_loxone_status_payload

            body = json.dumps(build_loxone_status_payload()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith(TELEMETRY_PREFIX):
            self._handle_telemetry_push()
            return
        self.send_error(404)

    def _handle_telemetry_push(self) -> None:
        """``GET /ehal/loxone/telemetry/<EHAL-ID>/<value>`` — pilot inbox (no control effect).

        Disabled (404) unless ``EARNIE_PILOT_PUSH_TOKEN`` is set. The token comes in
        the ``X-Earnie-Token`` header or as ``?t=`` query parameter.
        """
        expected = str(os.getenv(PUSH_TOKEN_ENV) or "").strip()
        if not expected:
            self.send_error(404)
            return
        parsed = urlparse(self.path)
        supplied = self.headers.get(PUSH_TOKEN_HEADER) or (
            parse_qs(parsed.query).get("t") or [""]
        )[0]
        if not hmac.compare_digest(str(supplied).encode(), expected.encode()):
            self.send_error(401)
            return
        ehal_id, _, raw = unquote(parsed.path[len(TELEMETRY_PREFIX):]).partition("/")
        from runtime_store.loxone_push_inbox import record_push

        peer = self.client_address[0] if self.client_address else ""
        result = record_push(ehal_id, raw, peer)
        if result in ("ok", "new"):
            self.send_response(204)
            self.end_headers()
            return
        # bad_id / bad_raw → 400, full → 507; never echo the input back.
        self.send_error(507 if result == "full" else 400)

    def do_POST(self) -> None:  # noqa: N802
        path = _normalize_path(self.path)
        if path == REQUEST_OPTIMIZE_PATH.rstrip("/") or path == REQUEST_OPTIMIZE_PATH:
            length = int(self.headers.get("Content-Length") or 0)
            if length > 0:
                self.rfile.read(length)
            self._record_peer()
            signal_optimize_request()
            try:
                from runtime_store.shadow.hooks import record_event

                record_event("trigger:request_optimize")
            except Exception:  # noqa: BLE001
                pass
            logger.info("Earnie_Request_Optimize received — early optimize queued.")
            self.send_response(204)
            self.end_headers()
            return
        self.send_error(404)


def start_loxone_request_http(
    port: int,
    *,
    host: str = "0.0.0.0",
) -> ThreadingHTTPServer:
    """Start daemon HTTP listener; idempotent if already running on same port."""
    from runtime_store.shadow.mode import is_shadow_mode

    if is_shadow_mode():
        logger.info(
            "Shadow Mode: Loxone request HTTP listener not started (port %s)",
            port,
        )
        return None  # type: ignore[return-value]
    global _server, _thread
    with _lock:
        if _server is not None:
            return _server
        server = ThreadingHTTPServer((host, int(port)), _LoxoneRequestHandler)
        thread = threading.Thread(
            target=server.serve_forever,
            name="loxone-request-http",
            daemon=True,
        )
        thread.start()
        _server = server
        _thread = thread
        logger.info(
            "Loxone request HTTP listening on %s:%s (%s, %s, %s)",
            host,
            port,
            REQUEST_OPTIMIZE_PATH,
            ALIVE_PATH,
            STATUS_PATH,
        )
        return server


def stop_loxone_request_http() -> None:
    """Stop listener (tests)."""
    global _server, _thread
    with _lock:
        server = _server
        _server = None
        _thread = None
    if server is not None:
        server.shutdown()
        server.server_close()


def wait_for_optimize_or_timeout(
    total_wait_sec: float,
    *,
    poll_interval_sec: float = 1.0,
    sleep_fn: Callable[[float], None] | None = None,
    event: threading.Event | None = None,
    on_poll: Callable[[], None] | None = None,
) -> bool:
    """Sleep until timeout or optimize Event; return True if Event fired."""
    import time

    sleep = sleep_fn or time.sleep
    ev = event if event is not None else _optimize_event
    remaining = float(total_wait_sec)
    if remaining <= 0:
        return consume_optimize_request() if event is None else ev.is_set()

    poll = max(0.2, float(poll_interval_sec))
    while remaining > 0:
        if on_poll is not None:
            try:
                on_poll()
            except Exception:  # noqa: BLE001 — wait loop must not die on poll hooks
                logger.exception("wait_for_optimize_or_timeout: on_poll failed")
        if ev.is_set():
            if event is None:
                clear_optimize_request()
            else:
                ev.clear()
            return True
        chunk = min(poll, remaining)
        sleep(chunk)
        remaining -= chunk
    if on_poll is not None:
        try:
            on_poll()
        except Exception:  # noqa: BLE001
            logger.exception("wait_for_optimize_or_timeout: on_poll failed")
    if ev.is_set():
        if event is None:
            clear_optimize_request()
        else:
            ev.clear()
        return True
    return False
