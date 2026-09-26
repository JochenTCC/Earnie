#!/usr/bin/env python3
"""Container HEALTHCHECK: Streamlit /_stcore/health + optional daemon heartbeat."""
from __future__ import annotations

import os
import sys
import urllib.error
import urllib.request

from runtime_store.daemon_heartbeat import STALE_AFTER_SEC, heartbeat_is_fresh
from runtime_store.main_daemon import status as daemon_status


def streamlit_health_url() -> str:
    port = os.environ.get("EARNIE_UI_STREAMLIT_PORT", "8501").strip() or "8501"
    return f"http://127.0.0.1:{port}/_stcore/health"


def check_streamlit_health(url: str | None = None, *, timeout_sec: float = 4.0) -> bool:
    target = url if url is not None else streamlit_health_url()
    try:
        with urllib.request.urlopen(target, timeout=timeout_sec) as resp:
            return 200 <= int(resp.status) < 300
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False


def check_daemon_heartbeat_if_running(*, now_ts: float | None = None) -> bool:
    """If optimizer daemon PID is alive, require a fresh heartbeat file."""
    if daemon_status().state != "running":
        return True
    return heartbeat_is_fresh(now_ts=now_ts, stale_after_sec=STALE_AFTER_SEC)


def run_healthcheck() -> int:
    if not check_streamlit_health():
        print(f"earnie: healthcheck FAIL — Streamlit not healthy at {streamlit_health_url()}", file=sys.stderr)
        return 1
    if not check_daemon_heartbeat_if_running():
        print(
            "earnie: healthcheck FAIL — optimizer daemon running but heartbeat stale/missing",
            file=sys.stderr,
        )
        return 1
    return 0


def main() -> int:
    return run_healthcheck()


if __name__ == "__main__":
    raise SystemExit(main())
