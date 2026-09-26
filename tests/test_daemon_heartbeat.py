"""Daemon heartbeat + container healthcheck logic (2.6.m / H4)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from runtime_store import daemon_heartbeat as hb
from scripts import container_healthcheck as chc


def test_touch_and_read_heartbeat(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
    path = hb.touch_daemon_heartbeat(now_ts=1_700_000_000)
    assert path.is_file()
    assert hb.read_heartbeat_ts() == 1_700_000_000
    assert hb.heartbeat_is_fresh(now_ts=1_700_000_050) is True
    assert hb.heartbeat_is_fresh(now_ts=1_700_000_000 + hb.STALE_AFTER_SEC + 1) is False


def test_missing_heartbeat_not_fresh(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
    assert hb.read_heartbeat_ts() is None
    assert hb.heartbeat_is_fresh(now_ts=1_700_000_000) is False


def test_healthcheck_fails_when_streamlit_down(monkeypatch) -> None:
    monkeypatch.setattr(chc, "check_streamlit_health", lambda: False)
    monkeypatch.setattr(chc, "check_daemon_heartbeat_if_running", lambda: True)
    assert chc.run_healthcheck() == 1


def test_healthcheck_fails_when_daemon_heartbeat_stale(monkeypatch) -> None:
    monkeypatch.setattr(chc, "check_streamlit_health", lambda: True)
    monkeypatch.setattr(chc, "check_daemon_heartbeat_if_running", lambda: False)
    assert chc.run_healthcheck() == 1


def test_healthcheck_ok(monkeypatch) -> None:
    monkeypatch.setattr(chc, "check_streamlit_health", lambda: True)
    monkeypatch.setattr(chc, "check_daemon_heartbeat_if_running", lambda: True)
    assert chc.run_healthcheck() == 0


def test_daemon_heartbeat_skipped_when_stopped(monkeypatch) -> None:
    stopped = MagicMock()
    stopped.state = "stopped"
    monkeypatch.setattr(chc, "daemon_status", lambda: stopped)
    assert chc.check_daemon_heartbeat_if_running() is True


def test_daemon_heartbeat_required_when_running(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
    running = MagicMock()
    running.state = "running"
    monkeypatch.setattr(chc, "daemon_status", lambda: running)
    assert chc.check_daemon_heartbeat_if_running(now_ts=1_700_000_000) is False
    hb.touch_daemon_heartbeat(now_ts=1_700_000_000)
    assert chc.check_daemon_heartbeat_if_running(now_ts=1_700_000_010) is True


def test_streamlit_health_url_uses_env(monkeypatch) -> None:
    monkeypatch.setenv("EARNIE_UI_STREAMLIT_PORT", "8502")
    assert chc.streamlit_health_url() == "http://127.0.0.1:8502/_stcore/health"


@patch("scripts.container_healthcheck.urllib.request.urlopen")
def test_check_streamlit_health_http_ok(mock_urlopen) -> None:
    resp = MagicMock()
    resp.status = 200
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    mock_urlopen.return_value = resp
    assert chc.check_streamlit_health("http://127.0.0.1:8501/_stcore/health") is True
