"""Tests for registry entitlement soft status (2.4.q)."""
from __future__ import annotations

import json
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from runtime_store.hardware_identity import compute_hardware_fingerprint
from runtime_store.registry_entitlement import (
    build_entitlement,
    build_entitlement_ed25519,
    registry_status,
    verify_entitlement_ed25519,
    verify_entitlement_sig,
)


def _write_keypair(tmp_path: Path) -> tuple[Ed25519PrivateKey, Path]:
    private_key = Ed25519PrivateKey.generate()
    pub_path = tmp_path / "pub.pem"
    pub_path.write_bytes(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    return private_key, pub_path


def test_build_and_verify_entitlement_hmac() -> None:
    fp = compute_hardware_fingerprint(
        {"host": "lab-host", "loxone": "", "ha": "", "openems": ""}
    )
    secret = "dev-secret-for-tests"
    doc = build_entitlement(fingerprint=fp, secret=secret)
    assert verify_entitlement_sig(doc, secret) is True
    assert verify_entitlement_sig(doc, "wrong") is False


def test_build_and_verify_entitlement_ed25519(tmp_path: Path) -> None:
    fp = compute_hardware_fingerprint(
        {"host": "lab-host", "loxone": "", "ha": "", "openems": ""}
    )
    private_key, pub_path = _write_keypair(tmp_path)
    doc = build_entitlement_ed25519(fingerprint=fp, private_key=private_key)
    from runtime_store.registry_entitlement import load_ed25519_public_key

    pub = load_ed25519_public_key(str(pub_path))
    assert verify_entitlement_ed25519(doc, pub) is True
    doc_bad = dict(doc)
    doc_bad["sig"] = "00" * 64
    assert verify_entitlement_ed25519(doc_bad, pub) is False


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


def test_registry_status_valid_hmac(tmp_path: Path) -> None:
    fp = compute_hardware_fingerprint(
        {"host": "h1", "loxone": "SN", "ha": "", "openems": ""}
    )
    secret = "sec"
    doc = build_entitlement(fingerprint=fp, secret=secret)
    path = tmp_path / "earnie_registry.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    report = registry_status(path=str(path), fingerprint=fp, secret=secret)
    assert report.status == "valid"


def test_registry_status_valid_ed25519(tmp_path: Path) -> None:
    fp = compute_hardware_fingerprint(
        {"host": "h1", "loxone": "SN", "ha": "", "openems": ""}
    )
    private_key, pub_path = _write_keypair(tmp_path)
    doc = build_entitlement_ed25519(fingerprint=fp, private_key=private_key)
    path = tmp_path / "earnie_registry.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    report = registry_status(
        path=str(path),
        fingerprint=fp,
        public_key_path=str(pub_path),
    )
    assert report.status == "valid"
    assert report.detail == "bound"


def test_registry_status_mismatch_ed25519(tmp_path: Path) -> None:
    fp_a = compute_hardware_fingerprint(
        {"host": "a", "loxone": "", "ha": "", "openems": ""}
    )
    fp_b = compute_hardware_fingerprint(
        {"host": "b", "loxone": "", "ha": "", "openems": ""}
    )
    private_key, pub_path = _write_keypair(tmp_path)
    doc = build_entitlement_ed25519(fingerprint=fp_a, private_key=private_key)
    path = tmp_path / "earnie_registry.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    report = registry_status(
        path=str(path),
        fingerprint=fp_b,
        public_key_path=str(pub_path),
    )
    assert report.status == "mismatch"


def test_registry_status_invalid_sig_ed25519(tmp_path: Path) -> None:
    fp = compute_hardware_fingerprint(
        {"host": "h1", "loxone": "", "ha": "", "openems": ""}
    )
    private_key, pub_path = _write_keypair(tmp_path)
    doc = build_entitlement_ed25519(fingerprint=fp, private_key=private_key)
    doc["sig"] = "00" * 64
    path = tmp_path / "earnie_registry.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    report = registry_status(
        path=str(path),
        fingerprint=fp,
        public_key_path=str(pub_path),
    )
    assert report.status == "invalid_sig"


def test_registry_status_mismatch_hmac(tmp_path: Path) -> None:
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


def test_registry_status_invalid_sig_hmac(tmp_path: Path) -> None:
    fp = compute_hardware_fingerprint(
        {"host": "h1", "loxone": "", "ha": "", "openems": ""}
    )
    doc = build_entitlement(fingerprint=fp, secret="sec")
    doc["sig"] = "0" * 64
    path = tmp_path / "earnie_registry.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    report = registry_status(path=str(path), fingerprint=fp, secret="sec")
    assert report.status == "invalid_sig"
