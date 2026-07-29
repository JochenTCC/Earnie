"""Tests for registry entitlement soft status (2.4.i)."""
from __future__ import annotations

import json
from pathlib import Path

from runtime_store.hardware_identity import compute_hardware_fingerprint
from runtime_store.registry_entitlement import (
    build_entitlement,
    registry_status,
    verify_entitlement_sig,
)


def test_build_and_verify_entitlement() -> None:
    fp = compute_hardware_fingerprint({"host": "lab-host", "loxone": "", "ha": "", "openems": ""})
    secret = "dev-secret-for-tests"
    doc = build_entitlement(fingerprint=fp, secret=secret)
    assert verify_entitlement_sig(doc, secret) is True
    assert verify_entitlement_sig(doc, "wrong") is False


def test_registry_status_unbound(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    fp = compute_hardware_fingerprint(
        {"host": "h1", "loxone": "", "ha": "", "openems": ""}
    )
    report = registry_status(
        path=str(missing),
        fingerprint=fp,
        secret="sec",
    )
    assert report.status == "unbound"


def test_registry_status_valid(tmp_path: Path) -> None:
    fp = compute_hardware_fingerprint(
        {"host": "h1", "loxone": "SN", "ha": "", "openems": ""}
    )
    secret = "sec"
    doc = build_entitlement(fingerprint=fp, secret=secret)
    path = tmp_path / "earnie_registry.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    report = registry_status(path=str(path), fingerprint=fp, secret=secret)
    assert report.status == "valid"


def test_registry_status_mismatch(tmp_path: Path) -> None:
    fp_a = compute_hardware_fingerprint(
        {"host": "a", "loxone": "", "ha": "", "openems": ""}
    )
    fp_b = compute_hardware_fingerprint(
        {"host": "b", "loxone": "", "ha": "", "openems": ""}
    )
    secret = "sec"
    doc = build_entitlement(fingerprint=fp_a, secret=secret)
    path = tmp_path / "earnie_registry.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    report = registry_status(path=str(path), fingerprint=fp_b, secret=secret)
    assert report.status == "mismatch"


def test_registry_status_invalid_sig(tmp_path: Path) -> None:
    fp = compute_hardware_fingerprint(
        {"host": "h1", "loxone": "", "ha": "", "openems": ""}
    )
    doc = build_entitlement(fingerprint=fp, secret="sec")
    doc["sig"] = "0" * 64
    path = tmp_path / "earnie_registry.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    report = registry_status(path=str(path), fingerprint=fp, secret="sec")
    assert report.status == "invalid_sig"
