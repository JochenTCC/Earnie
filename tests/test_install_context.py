# tests/test_install_context.py
from __future__ import annotations

from runtime_store import install_context


def test_defaults_to_manual_when_unset(monkeypatch):
    monkeypatch.delenv("EARNIE_INSTALL_CONTEXT", raising=False)
    assert install_context.detect_install_context() == "manual"
    assert install_context.install_context_target_kinds("manual") is None


def test_loxberry_context(monkeypatch):
    monkeypatch.setenv("EARNIE_INSTALL_CONTEXT", "loxberry")
    assert install_context.detect_install_context() == "loxberry"
    assert install_context.install_context_target_kinds() == ["loxone"]


def test_homeassistant_addon_context(monkeypatch):
    monkeypatch.setenv("EARNIE_INSTALL_CONTEXT", "homeassistant_addon")
    assert install_context.detect_install_context() == "homeassistant_addon"
    assert install_context.install_context_target_kinds() == ["home_assistant"]


def test_unknown_value_falls_back_to_manual(monkeypatch):
    monkeypatch.setenv("EARNIE_INSTALL_CONTEXT", "some-typo")
    assert install_context.detect_install_context() == "manual"


def test_case_insensitive(monkeypatch):
    monkeypatch.setenv("EARNIE_INSTALL_CONTEXT", "LoxBerry")
    assert install_context.detect_install_context() == "loxberry"
