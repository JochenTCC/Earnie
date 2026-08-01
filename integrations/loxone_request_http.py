"""Minimal Loxone → Earnie HTTP wake (Earnie_Request_Optimize)."""
from __future__ import annotations

import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

REQUEST_OPTIMIZE_PATH = "/ehal/loxone/request_optimize"
ALIVE_PATH = "/ehal/loxone/alive"

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

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path == ALIVE_PATH.rstrip("/") or path == ALIVE_PATH:
            self.send_response(204)
            self.end_headers()
            return
        self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path == REQUEST_OPTIMIZE_PATH.rstrip("/") or path == REQUEST_OPTIMIZE_PATH:
            length = int(self.headers.get("Content-Length") or 0)
            if length > 0:
                self.rfile.read(length)
            signal_optimize_request()
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
            "Loxone request HTTP listening on %s:%s (%s, %s)",
            host,
            port,
            REQUEST_OPTIMIZE_PATH,
            ALIVE_PATH,
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
        if ev.is_set():
            if event is None:
                clear_optimize_request()
            else:
                ev.clear()
            return True
        chunk = min(poll, remaining)
        sleep(chunk)
        remaining -= chunk
    if ev.is_set():
        if event is None:
            clear_optimize_request()
        else:
            ev.clear()
        return True
    return False
