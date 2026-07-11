"""Tests for EARNIE_* env var resolution with ENERGY_OPTIMIZER_* fallback."""
from __future__ import annotations

import pytest

from runtime_store import env_vars


def test_read_env_prefers_earnie_over_legacy(monkeypatch):
    monkeypatch.setenv("EARNIE_RUNTIME_DIR", "/earnie/runtime")
    monkeypatch.setenv("ENERGY_OPTIMIZER_RUNTIME_DIR", "/legacy/runtime")
    assert env_vars.read_env("RUNTIME_DIR") == "/earnie/runtime"


def test_read_env_falls_back_to_legacy(monkeypatch):
    monkeypatch.delenv("EARNIE_RUNTIME_DIR", raising=False)
    monkeypatch.setenv("ENERGY_OPTIMIZER_RUNTIME_DIR", "/legacy/runtime")
    assert env_vars.read_env("RUNTIME_DIR") == "/legacy/runtime"


def test_read_env_or_default(monkeypatch):
    monkeypatch.delenv("EARNIE_RUNTIME_DIR", raising=False)
    monkeypatch.delenv("ENERGY_OPTIMIZER_RUNTIME_DIR", raising=False)
    assert env_vars.read_env_or("RUNTIME_DIR", "runtime") == "runtime"


def test_is_truthy(monkeypatch):
    monkeypatch.setenv("EARNIE_OFFLINE", "1")
    assert env_vars.is_truthy("OFFLINE") is True
    monkeypatch.setenv("EARNIE_OFFLINE", "0")
    assert env_vars.is_truthy("OFFLINE") is False
