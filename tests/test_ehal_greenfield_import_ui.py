"""Unit tests for Smarthome-Backend Loxone-Import access gating."""
from __future__ import annotations

import os

os.environ.setdefault("EARNIE_OFFLINE", "1")

from ui.ehal_greenfield_import import (
    _CREDENTIALS_HINT,
    _FAILED_ACCESS_TTL_S,
    _IMPORT_HINT,
    _IMPORT_SAVED_FLASH,
    _access_fingerprint,
    _cached_access,
    resolve_loxone_import_access,
)


def test_import_hint_links_library_doc():
    assert "Anleitung" in _IMPORT_HINT
    assert "loxone-signals.md" in _IMPORT_HINT
    assert "library-setup" in _IMPORT_HINT


def test_import_saved_flash_points_to_hk_consumers_and_ehal_com():
    assert "Hauskonfigurator" in _IMPORT_SAVED_FLASH
    assert "Verbraucher" in _IMPORT_SAVED_FLASH
    assert "EHAL-Com" in _IMPORT_SAVED_FLASH
    # The old "Signal-Mapping" section is gone; EHAL-Com has the Signalliste.
    assert "Signalliste" in _IMPORT_SAVED_FLASH
    assert "Signal-Mapping" not in _IMPORT_SAVED_FLASH


def test_cached_success_kept_for_same_credentials():
    fp = _access_fingerprint("10.0.0.1", "u", "p")
    assert _cached_access((fp, True, 0.0), fp, now=1e6) == (True, None)


def test_cached_failure_expires_so_import_unlocks_again():
    fp = _access_fingerprint("10.0.0.1", "u", "p")
    cached = (fp, False, 100.0)
    assert _cached_access(cached, fp, now=100.0 + _FAILED_ACCESS_TTL_S / 2) == (
        False,
        _CREDENTIALS_HINT,
    )
    assert _cached_access(cached, fp, now=100.0 + _FAILED_ACCESS_TTL_S) is None


def test_fingerprint_changes_for_new_password_of_same_length():
    assert _access_fingerprint("h", "u", "abcd") != _access_fingerprint("h", "u", "wxyz")
    fp_old = _access_fingerprint("h", "u", "abcd")
    fp_new = _access_fingerprint("h", "u", "wxyz")
    assert _cached_access((fp_old, False, 0.0), fp_new, now=0.0) is None


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
