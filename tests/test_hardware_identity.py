"""Tests for hardware identity fingerprint (2.4.i)."""
from __future__ import annotations

import hashlib

from runtime_store.hardware_identity import (
    DISPLAY_FINGERPRINT_CHARS,
    compute_hardware_fingerprint,
    display_fingerprint,
    fingerprint_payload,
)


def test_fingerprint_stable_for_fixed_parts() -> None:
    parts = {
        "host": "abc-host",
        "loxone": "MS123",
        "ha": "",
        "openems": "",
    }
    payload = fingerprint_payload(parts)
    assert payload == "host=abc-host\nloxone=MS123"
    expected = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    assert compute_hardware_fingerprint(parts) == expected


def test_fingerprint_key_order_independent_of_dict_order() -> None:
    a = compute_hardware_fingerprint(
        {"loxone": "X", "host": "H", "ha": "", "openems": ""}
    )
    b = compute_hardware_fingerprint(
        {"openems": "", "ha": "", "host": "H", "loxone": "X"}
    )
    assert a == b


def test_empty_parts_hash_empty_string() -> None:
    empty = compute_hardware_fingerprint(
        {"host": "", "loxone": "  ", "ha": "", "openems": ""}
    )
    assert empty == hashlib.sha256(b"").hexdigest()


def test_display_fingerprint_truncates() -> None:
    full = "a" * 64
    assert display_fingerprint(full) == "a" * DISPLAY_FINGERPRINT_CHARS
    assert display_fingerprint("") == ""
