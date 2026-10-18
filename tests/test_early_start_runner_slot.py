"""Cross-process runner slot of the EarlyStart equivalence test (``_runner_slot``)."""
from __future__ import annotations

import os
import sys
import tempfile

import pytest

from tests import early_start_equivalence as ese


def _fail_on_slot_zero(monkeypatch, exc: OSError) -> None:
    real_open = os.open

    def fake_open(path, flags, *args):
        if str(path).endswith("earnie_early_start_runner_0.lock"):
            raise exc
        return real_open(path, flags, *args)

    monkeypatch.setattr(os, "open", fake_open)


def test_delete_pending_lock_on_windows_counts_as_busy_slot(monkeypatch, tmp_path):
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(sys, "platform", "win32")
    _fail_on_slot_zero(monkeypatch, PermissionError(13, "Permission denied"))

    with ese._runner_slot():
        assert (tmp_path / "earnie_early_start_runner_1.lock").exists()
        assert not (tmp_path / "earnie_early_start_runner_0.lock").exists()
    assert not (tmp_path / "earnie_early_start_runner_1.lock").exists()


def test_permission_error_outside_windows_is_raised(monkeypatch, tmp_path):
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(sys, "platform", "linux")
    _fail_on_slot_zero(monkeypatch, PermissionError(13, "Permission denied"))

    with pytest.raises(PermissionError):
        with ese._runner_slot():
            pass
