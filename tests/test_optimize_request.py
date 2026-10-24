"""UI → daemon ad-hoc optimize request and plan-input change detection."""
from __future__ import annotations

import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from runtime_store import optimize_request
from runtime_store.optimize_request import (
    OptimizeRequestError,
    plan_inputs_changed_since_last_run,
    request_optimize,
)

_LAST_RUN = "2026-10-24T10:00:00"


def _state() -> dict:
    return {"completed_at": _LAST_RUN}


def _epoch() -> float:
    from runtime_store import run_state

    return run_state.completed_at_epoch(_state())


def _file_with_mtime(tmp_path: Path, name: str, mtime: float) -> str:
    path = tmp_path / name
    path.write_text("{}", encoding="utf-8")
    os.utime(path, (mtime, mtime))
    return str(path)


def test_no_run_state_means_no_change(tmp_path: Path) -> None:
    path = _file_with_mtime(tmp_path, "tariffs.json", 1.0)
    assert not plan_inputs_changed_since_last_run({}, resolvers=(lambda: path,))


def test_file_newer_than_last_run_is_a_change(tmp_path: Path) -> None:
    old = _file_with_mtime(tmp_path, "a.json", _epoch() - 60)
    new = _file_with_mtime(tmp_path, "b.json", _epoch() + 60)
    assert plan_inputs_changed_since_last_run(_state(), resolvers=(lambda: old, lambda: new))


def test_only_older_files_are_no_change(tmp_path: Path) -> None:
    old = _file_with_mtime(tmp_path, "a.json", _epoch() - 60)
    assert not plan_inputs_changed_since_last_run(_state(), resolvers=(lambda: old,))


def test_missing_file_is_ignored(tmp_path: Path) -> None:
    missing = str(tmp_path / "gone.json")
    assert not plan_inputs_changed_since_last_run(_state(), resolvers=(lambda: missing,))


def _serve(status: int) -> tuple[HTTPServer, list[str]]:
    seen: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            seen.append(self.path)
            self.send_response(status)
            self.end_headers()

        def log_message(self, *args) -> None:  # noqa: A002
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, seen


def test_request_optimize_posts_to_request_route() -> None:
    server, seen = _serve(204)
    try:
        request_optimize(port=server.server_port)
    finally:
        server.shutdown()
        server.server_close()
    assert seen == ["/ehal/loxone/request_optimize"]


def test_request_optimize_unreachable_daemon_raises() -> None:
    server, _ = _serve(204)
    port = server.server_port
    server.shutdown()
    server.server_close()
    with pytest.raises(OptimizeRequestError, match=str(port)):
        request_optimize(port=port)


def test_request_optimize_http_error_raises() -> None:
    server, _ = _serve(404)
    try:
        with pytest.raises(OptimizeRequestError):
            request_optimize(port=server.server_port)
    finally:
        server.shutdown()
        server.server_close()


def test_module_uses_daemon_port_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    server, seen = _serve(204)
    monkeypatch.setattr(optimize_request.config, "get_ehal_http_port", lambda: server.server_port)
    try:
        request_optimize()
    finally:
        server.shutdown()
        server.server_close()
    assert seen
