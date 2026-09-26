# tests/test_version_track.py
from __future__ import annotations

from pathlib import Path

import pytest

from runtime_store import version_track as vt


@pytest.fixture(autouse=True)
def _clear_pending():
    vt._PENDING_WARNING = None
    yield
    vt._PENDING_WARNING = None


def test_is_downgrade_official_vs_older():
    assert vt.is_downgrade("2.5.0", "2.6.0") is True
    assert vt.is_downgrade("2.6.0", "2.5.0") is False
    assert vt.is_downgrade("2.6.0", "2.6.0") is False


def test_is_downgrade_prerelease_below_same_core_official():
    assert vt.is_downgrade("2.6.0-alpha.1", "2.6.0") is True
    assert vt.is_downgrade("2.6.0", "2.6.0-alpha.1") is False


def test_is_downgrade_alpha_sequence():
    assert vt.is_downgrade("2.6.0-alpha.1", "2.6.0-alpha.2") is True
    assert vt.is_downgrade("2.6.0-alpha.2", "2.6.0-alpha.1") is False


def test_check_and_record_first_run_no_warning(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(vt, "runtime_path", lambda name: str(tmp_path / name))
    assert vt.check_and_record_version("2.6.0") is None
    assert (tmp_path / "last_run_version").read_text(encoding="utf-8").strip() == "2.6.0"
    assert vt.consume_downgrade_warning() is None


def test_check_and_record_downgrade_warns(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(vt, "runtime_path", lambda name: str(tmp_path / name))
    (tmp_path / "last_run_version").write_text("2.6.0\n", encoding="utf-8")
    msg = vt.check_and_record_version("2.5.3")
    assert msg is not None
    assert "2.6.0" in msg and "2.5.3" in msg
    assert "Downgrade" in msg
    assert vt.consume_downgrade_warning() == msg
    assert vt.consume_downgrade_warning() is None
    assert (tmp_path / "last_run_version").read_text(encoding="utf-8").strip() == "2.5.3"


def test_check_and_record_upgrade_silent(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(vt, "runtime_path", lambda name: str(tmp_path / name))
    (tmp_path / "last_run_version").write_text("2.5.0\n", encoding="utf-8")
    assert vt.check_and_record_version("2.6.0") is None
