from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from runtime_store.single_instance import SingleInstanceLock


def test_acquire_and_release(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENERGY_OPTIMIZER_RUNTIME_DIR", str(tmp_path))
    lock = SingleInstanceLock("test-service")
    lock.acquire()
    assert lock.lock_path == str(tmp_path / "test-service.lock")
    lock.release()


def test_second_process_is_blocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENERGY_OPTIMIZER_RUNTIME_DIR", str(tmp_path))
    env = os.environ.copy()
    env["ENERGY_OPTIMIZER_RUNTIME_DIR"] = str(tmp_path)
    holder_code = """
import os, sys, time
from runtime_store.single_instance import ensure_single_instance
ensure_single_instance(sys.argv[1])
time.sleep(8)
"""
    holder = subprocess.Popen(
        [sys.executable, "-c", holder_code, "parallel-test"],
        env=env,
        cwd=str(Path(__file__).resolve().parents[1]),
    )
    try:
        time.sleep(0.5)
        blocked = subprocess.run(
            [sys.executable, "-c", holder_code, "parallel-test"],
            env=env,
            cwd=str(Path(__file__).resolve().parents[1]),
            capture_output=True,
            text=True,
        )
        assert blocked.returncode == 1
        assert "parallel-test" in blocked.stderr or "parallel-test" in blocked.stdout
    finally:
        holder.terminate()
        holder.wait(timeout=5)


def test_empty_name_raises() -> None:
    with pytest.raises(ValueError, match="name darf nicht leer sein"):
        SingleInstanceLock("   ")
