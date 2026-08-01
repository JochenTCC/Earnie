"""Hardware registry entitlement load/verify (2.4.q first approach).

Official path: Ed25519 with bundled public key. HMAC + ``EARNIE_REGISTRY_DEV_SECRET``
remains a local/test fallback only. Never refuses app start.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from runtime_store.env_vars import read_env
from runtime_store.hardware_identity import (
    collect_and_fingerprint,
    display_fingerprint,
)
from runtime_store.persist_paths import runtime_path

RegistryStatus = Literal["unbound", "valid", "mismatch", "invalid_sig"]

DEFAULT_REGISTRY_FILENAME = "earnie_registry.json"
SIG_ALG_ED25519 = "ed25519"
SIG_ALG_HMAC = "hmac-sha256"
SIG_ALG = SIG_ALG_HMAC  # legacy alias for tests / HMAC helpers
DEV_ISSUER = "earnie-dev"
OFFICIAL_ISSUER = "earnie"
BUNDLED_PUBKEY_REL = os.path.join("share", "registry", "earnie_registry_pubkey.pem")


@dataclass(frozen=True)
class RegistryReport:
    """Soft registry check result (never raises to stop the app)."""

    status: RegistryStatus
    fingerprint: str
    fingerprint_display: str
    path: str | None = None
    detail: str = ""


def default_registry_path() -> str:
    override = read_env("REGISTRY_PATH")
    if override:
        return override
    return runtime_path(DEFAULT_REGISTRY_FILENAME)


def bundled_registry_pubkey_path() -> str:
    """Default Ed25519 public key shipped with the image/repo."""
    override = read_env("REGISTRY_PUBLIC_KEY_PATH")
    if override:
        return override
    return BUNDLED_PUBKEY_REL


def _expires_canonical(expires_at: Any) -> str:
    if expires_at is None:
        return "null"
    return str(expires_at).strip()


def signing_payload(
    *,
    fingerprint: str,
    issued_at: str,
    expires_at: Any,
    issuer: str,
    sig_alg: str,
) -> str:
    """Canonical UTF-8 payload signed by HMAC or Ed25519 (no trailing newline)."""
    return (
        f"fingerprint={fingerprint.strip()}\n"
        f"issued_at={issued_at.strip()}\n"
        f"expires_at={_expires_canonical(expires_at)}\n"
        f"issuer={issuer.strip()}\n"
        f"sig_alg={sig_alg.strip()}"
    )


def load_ed25519_private_key(path: str) -> Ed25519PrivateKey:
    """Load PKCS8 PEM private key from ``path``."""
    with open(path, "rb") as handle:
        raw = handle.read()
    key = serialization.load_pem_private_key(raw, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("private key is not Ed25519")
    return key


def load_ed25519_public_key(path: str) -> Ed25519PublicKey:
    """Load SubjectPublicKeyInfo PEM public key from ``path``."""
    with open(path, "rb") as handle:
        raw = handle.read()
    key = serialization.load_pem_public_key(raw)
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("public key is not Ed25519")
    return key


def sign_entitlement_ed25519(
    *,
    fingerprint: str,
    issued_at: str,
    expires_at: Any,
    issuer: str,
    private_key: Ed25519PrivateKey,
) -> str:
    """Return hex Ed25519 signature of the signing payload."""
    payload = signing_payload(
        fingerprint=fingerprint,
        issued_at=issued_at,
        expires_at=expires_at,
        issuer=issuer,
        sig_alg=SIG_ALG_ED25519,
    )
    return private_key.sign(payload.encode("utf-8")).hex()


def sign_entitlement(
    *,
    fingerprint: str,
    issued_at: str,
    expires_at: Any,
    issuer: str,
    secret: str,
    sig_alg: str = SIG_ALG_HMAC,
) -> str:
    """Return hex HMAC-SHA256 of the signing payload (dev/test fallback)."""
    payload = signing_payload(
        fingerprint=fingerprint,
        issued_at=issued_at,
        expires_at=expires_at,
        issuer=issuer,
        sig_alg=sig_alg,
    )
    digest = hmac.new(
        secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return digest


def build_entitlement(
    *,
    fingerprint: str,
    secret: str,
    issuer: str = DEV_ISSUER,
    expires_at: str | None = None,
    issued_at: str | None = None,
) -> dict[str, Any]:
    """Build a signed entitlement dict (HMAC fallback for tests)."""
    issued = issued_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    sig = sign_entitlement(
        fingerprint=fingerprint,
        issued_at=issued,
        expires_at=expires_at,
        issuer=issuer,
        secret=secret,
        sig_alg=SIG_ALG_HMAC,
    )
    return {
        "fingerprint": fingerprint.strip(),
        "issued_at": issued,
        "expires_at": expires_at,
        "issuer": issuer,
        "sig_alg": SIG_ALG_HMAC,
        "sig": sig,
    }


def build_entitlement_ed25519(
    *,
    fingerprint: str,
    private_key: Ed25519PrivateKey,
    issuer: str = OFFICIAL_ISSUER,
    expires_at: str | None = None,
    issued_at: str | None = None,
) -> dict[str, Any]:
    """Build a signed entitlement dict (Ed25519 first approach)."""
    issued = issued_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    sig = sign_entitlement_ed25519(
        fingerprint=fingerprint,
        issued_at=issued,
        expires_at=expires_at,
        issuer=issuer,
        private_key=private_key,
    )
    return {
        "fingerprint": fingerprint.strip(),
        "issued_at": issued,
        "expires_at": expires_at,
        "issuer": issuer,
        "sig_alg": SIG_ALG_ED25519,
        "sig": sig,
    }


def load_entitlement(path: str) -> dict[str, Any] | None:
    """Load entitlement JSON; return None if missing or unreadable."""
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _shape_ok(data: dict[str, Any]) -> bool:
    required = ("fingerprint", "issued_at", "issuer", "sig_alg", "sig")
    for key in required:
        if key not in data:
            return False
        if key != "expires_at" and not str(data.get(key) or "").strip():
            return False
    if "expires_at" not in data:
        return False
    return True


def verify_entitlement_sig(data: dict[str, Any], secret: str) -> bool:
    """True when HMAC matches; False on any failure (HMAC fallback only)."""
    if not secret or not _shape_ok(data):
        return False
    if str(data.get("sig_alg") or "").strip() != SIG_ALG_HMAC:
        return False
    expected = sign_entitlement(
        fingerprint=str(data["fingerprint"]),
        issued_at=str(data["issued_at"]),
        expires_at=data.get("expires_at"),
        issuer=str(data["issuer"]),
        secret=secret,
        sig_alg=SIG_ALG_HMAC,
    )
    actual = str(data.get("sig") or "").strip().lower()
    return hmac.compare_digest(expected.lower(), actual)


def verify_entitlement_ed25519(
    data: dict[str, Any],
    public_key: Ed25519PublicKey,
) -> bool:
    """True when Ed25519 signature matches; False on any failure."""
    if not _shape_ok(data):
        return False
    if str(data.get("sig_alg") or "").strip() != SIG_ALG_ED25519:
        return False
    payload = signing_payload(
        fingerprint=str(data["fingerprint"]),
        issued_at=str(data["issued_at"]),
        expires_at=data.get("expires_at"),
        issuer=str(data["issuer"]),
        sig_alg=SIG_ALG_ED25519,
    )
    try:
        sig_bytes = bytes.fromhex(str(data.get("sig") or "").strip())
    except ValueError:
        return False
    try:
        public_key.verify(sig_bytes, payload.encode("utf-8"))
    except (InvalidSignature, ValueError):
        return False
    return True


def _is_expired(expires_at: Any) -> bool:
    if expires_at is None:
        return False
    text = str(expires_at).strip()
    if not text or text.lower() == "null":
        return False
    try:
        normalized = text.replace("Z", "+00:00")
        when = datetime.fromisoformat(normalized)
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
    except ValueError:
        return True
    return when < datetime.now(timezone.utc)


def _report(
    status: RegistryStatus,
    fingerprint: str,
    *,
    path: str | None,
    detail: str,
) -> RegistryReport:
    return RegistryReport(
        status=status,
        fingerprint=fingerprint,
        fingerprint_display=display_fingerprint(fingerprint),
        path=path,
        detail=detail,
    )


def _verify_sig_for_status(
    data: dict[str, Any],
    *,
    secret: str | None,
    public_key_path: str | None,
) -> tuple[bool, str]:
    """Return (ok, detail_on_failure)."""
    alg = str(data.get("sig_alg") or "").strip()
    if alg == SIG_ALG_ED25519:
        key_path = public_key_path or bundled_registry_pubkey_path()
        if not key_path or not os.path.isfile(key_path):
            return False, "Ed25519 public key not found"
        try:
            pub = load_ed25519_public_key(key_path)
        except (OSError, ValueError) as exc:
            return False, f"Ed25519 public key load error: {exc}"
        if not verify_entitlement_ed25519(data, pub):
            return False, "Ed25519 signature mismatch"
        return True, ""
    if alg == SIG_ALG_HMAC:
        sec = secret if secret is not None else read_env("REGISTRY_DEV_SECRET")
        if not sec:
            return False, "EARNIE_REGISTRY_DEV_SECRET not set"
        if not verify_entitlement_sig(data, sec):
            return False, "HMAC mismatch"
        return True, ""
    return False, f"unsupported sig_alg: {alg}"


def _evaluate_loaded_entitlement(
    data: dict[str, Any],
    *,
    fingerprint: str,
    path: str,
    secret: str | None,
    public_key_path: str | None,
) -> RegistryReport:
    if not _shape_ok(data):
        return _report(
            "invalid_sig", fingerprint, path=path, detail="entitlement shape invalid"
        )
    ok, detail = _verify_sig_for_status(
        data, secret=secret, public_key_path=public_key_path
    )
    if not ok:
        return _report("invalid_sig", fingerprint, path=path, detail=detail)
    bound = str(data.get("fingerprint") or "").strip().lower()
    if bound != fingerprint.lower():
        return _report(
            "mismatch",
            fingerprint,
            path=path,
            detail="fingerprint does not match entitlement",
        )
    if _is_expired(data.get("expires_at")):
        return _report(
            "invalid_sig", fingerprint, path=path, detail="entitlement expired"
        )
    return _report("valid", fingerprint, path=path, detail="bound")


def registry_status(
    *,
    path: str | None = None,
    fingerprint: str | None = None,
    secret: str | None = None,
    public_key_path: str | None = None,
) -> RegistryReport:
    """
    Soft status: unbound | valid | mismatch | invalid_sig.

    Never raises to stop the app.
    """
    try:
        if fingerprint is None:
            _, fingerprint = collect_and_fingerprint()
        fingerprint = fingerprint.strip()
        resolved = path if path is not None else default_registry_path()
        data = load_entitlement(resolved)
        if data is None:
            unbound_path = resolved if os.path.isfile(resolved) else None
            return _report(
                "unbound",
                fingerprint,
                path=unbound_path,
                detail="no entitlement file",
            )
        return _evaluate_loaded_entitlement(
            data,
            fingerprint=fingerprint,
            path=resolved,
            secret=secret,
            public_key_path=public_key_path,
        )
    except Exception as exc:  # noqa: BLE001 — soft path never blocks
        try:
            _, fp = collect_and_fingerprint()
        except Exception:  # noqa: BLE001
            fp = ""
        return _report(
            "invalid_sig",
            fp,
            path=path,
            detail=f"registry check error: {exc}",
        )
