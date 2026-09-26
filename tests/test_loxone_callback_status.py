"""Tests for Miniserver callback status persistence (H10)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from runtime_store import loxone_callback_status as cbs


@pytest.fixture
def callback_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
    return tmp_path


def test_record_and_load_roundtrip(callback_dir: Path) -> None:
    cbs.record_loxone_callback("192.168.178.20")
    status = cbs.load_loxone_callback_status()
    assert status is not None
    assert status["client_ip"] == "192.168.178.20"
    assert status["ts"]
    path = callback_dir / cbs.CALLBACK_FILENAME
    assert path.is_file()
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["client_ip"] == "192.168.178.20"


def test_format_caption_age(callback_dir: Path) -> None:
    now = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
    ts = (now - timedelta(minutes=5)).isoformat()
    caption = cbs.format_loxone_callback_caption(
        {"ts": ts, "client_ip": "10.0.0.5"},
        now=now,
    )
    assert caption == "Letzter Aufruf vom Miniserver: vor 5 min von IP 10.0.0.5"


def test_format_caption_empty(callback_dir: Path) -> None:
    assert "noch keiner" in cbs.format_loxone_callback_caption(None)
