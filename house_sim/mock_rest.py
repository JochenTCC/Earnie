"""Minimal Home Assistant REST mock for HaAdapter (Bearer + state shape)."""
from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import unquote, urlparse

from house_sim.state_store import StateStore

logger = logging.getLogger(__name__)

DEFAULT_BENCH_TOKEN = "house-sim-bench-token"

_server: ThreadingHTTPServer | None = None
_thread: threading.Thread | None = None
_lock = threading.Lock()
_store: StateStore | None = None
_token: str = DEFAULT_BENCH_TOKEN


def _normalize_path(raw_path: str) -> str:
    path = urlparse(raw_path).path
    return path.rstrip("/") or "/"


class _HaMockHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A003
        logger.debug("house_sim.mock_rest: " + format, *args)

    def _unauthorized(self) -> None:
        body = b'{"message":"Unauthorized"}'
        self.send_response(401)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _check_auth(self) -> bool:
        header = self.headers.get("Authorization") or ""
        expected = f"Bearer {_token}"
        if header.strip() != expected:
            self._unauthorized()
            return False
        return True

    def _json_response(self, status: int, payload: Any) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _text_response(self, status: int, message: str) -> None:
        body = message.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if not self._check_auth():
            return
        if _store is None:
            self._text_response(503, "Store not ready")
            return
        path = _normalize_path(self.path)
        if path == "/api/states":
            self._json_response(200, _store.list_states())
            return
        prefix = "/api/states/"
        if path.startswith(prefix):
            entity_id = unquote(path[len(prefix) :])
            payload = _store.get(entity_id)
            if payload is None:
                self._json_response(404, {"message": f"Entity {entity_id} not found."})
                return
            self._json_response(200, payload)
            return
        self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        if not self._check_auth():
            return
        if _store is None:
            self._text_response(503, "Store not ready")
            return
        path = _normalize_path(self.path)
        prefix = "/api/services/"
        if not path.startswith(prefix):
            self.send_error(404)
            return
        parts = path[len(prefix) :].split("/")
        if len(parts) != 2:
            self._text_response(400, "Expected /api/services/{domain}/{service}")
            return
        domain, service = parts
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._text_response(400, "Invalid JSON")
            return
        if not isinstance(data, dict):
            self._text_response(400, "JSON object required")
            return
        status, message = _store.apply_service(domain, service, data)
        if status == 200:
            self._json_response(200, [])
        else:
            self._text_response(status, message)


def start_mock_rest(
    store: StateStore,
    *,
    host: str = "127.0.0.1",
    port: int = 0,
    token: str = DEFAULT_BENCH_TOKEN,
) -> tuple[ThreadingHTTPServer, str]:
    """Start daemon mock HA; port 0 picks an ephemeral port. Returns (server, base_url)."""
    global _server, _thread, _store, _token
    with _lock:
        if _server is not None:
            raise RuntimeError("house_sim mock REST already running")
        _store = store
        _token = str(token)
        server = ThreadingHTTPServer((host, int(port)), _HaMockHandler)
        thread = threading.Thread(
            target=server.serve_forever,
            name="house-sim-mock-rest",
            daemon=True,
        )
        thread.start()
        _server = server
        _thread = thread
        bound_host, bound_port = server.server_address[:2]
        # Local lab mock only — TLS not used on loopback ThreadingHTTPServer.
        base_url = f"http://{bound_host}:{bound_port}"  # NOSONAR python:S5332
        logger.info("house_sim mock REST listening on %s", base_url)
        return server, base_url


def stop_mock_rest() -> None:
    """Stop mock listener (tests / CLI shutdown)."""
    global _server, _thread, _store
    with _lock:
        server = _server
        _server = None
        _thread = None
        _store = None
    if server is not None:
        server.shutdown()
        server.server_close()


def active_store() -> StateStore | None:
    return _store
