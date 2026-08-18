"""Unit tests for Smarthome-Backend Loxone-Import access gating."""
from __future__ import annotations

import os

os.environ.setdefault("EARNIE_OFFLINE", "1")

from ui.ehal_greenfield_import import (
    _CREDENTIALS_HINT,
    _IMPORT_HINT,
    resolve_loxone_import_access,
)


def test_import_hint_links_library_doc():
    assert "Anleitung" in _IMPORT_HINT
    assert "loxone-signals.md" in _IMPORT_HINT
    assert "library-setup" in _IMPORT_HINT


def test_access_disabled_without_credentials():
    enabled, hint = resolve_loxone_import_access(
        host="",
        user="",
        password="",
        credentials_ok=False,
        probe_fn=lambda **_kw: (True, "unused"),
    )
    assert enabled is False
    assert hint == _CREDENTIALS_HINT


def test_access_enabled_when_probe_ok():
    enabled, hint = resolve_loxone_import_access(
        host="10.0.0.1",
        user="u",
        password="p",
        credentials_ok=True,
        probe_fn=lambda **_kw: (True, "LoxAPP3 HTTP 200"),
    )
    assert enabled is True
    assert hint is None


def test_access_disabled_when_probe_fails():
    enabled, hint = resolve_loxone_import_access(
        host="10.0.0.1",
        user="u",
        password="p",
        credentials_ok=True,
        probe_fn=lambda **_kw: (False, "unreachable"),
    )
    assert enabled is False
    assert hint == _CREDENTIALS_HINT
