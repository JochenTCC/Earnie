#!/usr/bin/env python3
"""Issue earnie_registry.json for a hardware fingerprint (2.4.q).

Default: Ed25519 via ``EARNIE_REGISTRY_PRIVATE_KEY_PATH``.
Fallback: HMAC via ``EARNIE_REGISTRY_DEV_SECRET`` when ``--hmac`` is set.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime_store.env_vars import read_env
from runtime_store.registry_entitlement import (
    OFFICIAL_ISSUER,
    build_entitlement,
    build_entitlement_ed25519,
    load_ed25519_private_key,
)


def _valid_fingerprint(fp: str) -> bool:
    return len(fp) == 64 and all(c in "0123456789abcdef" for c in fp)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Issue earnie_registry.json. "
            "Default Ed25519 (EARNIE_REGISTRY_PRIVATE_KEY_PATH); "
            "optional --hmac with EARNIE_REGISTRY_DEV_SECRET."
        ),
    )
    parser.add_argument(
        "--fingerprint",
        required=True,
        help="Full 64-char SHA-256 hex hardware fingerprint",
    )
    parser.add_argument(
        "--out",
        required=True,
        help="Output path for entitlement JSON",
    )
    parser.add_argument(
        "--issuer",
        default=None,
        help="Issuer label (default: earnie for Ed25519, earnie-dev for HMAC)",
    )
    parser.add_argument(
        "--expires-at",
        default=None,
        help="Optional ISO-8601 expiry; omit for forever (null)",
    )
    parser.add_argument(
        "--hmac",
        action="store_true",
        help="Use HMAC-SHA256 with EARNIE_REGISTRY_DEV_SECRET (dev/test only)",
    )
    parser.add_argument(
        "--private-key",
        default=None,
        help="Override path to Ed25519 PKCS8 PEM private key",
    )
    args = parser.parse_args(argv)
    fp = args.fingerprint.strip().lower()
    if not _valid_fingerprint(fp):
        print("--fingerprint must be 64 hex characters.", file=sys.stderr)
        return 2

    if args.hmac:
        secret = read_env("REGISTRY_DEV_SECRET")
        if not secret:
            print(
                "EARNIE_REGISTRY_DEV_SECRET is required with --hmac.",
                file=sys.stderr,
            )
            return 2
        issuer = args.issuer or "earnie-dev"
        doc = build_entitlement(
            fingerprint=fp,
            secret=secret,
            issuer=issuer,
            expires_at=args.expires_at,
        )
    else:
        key_path = (args.private_key or "").strip() or read_env(
            "REGISTRY_PRIVATE_KEY_PATH"
        )
        if not key_path:
            print(
                "EARNIE_REGISTRY_PRIVATE_KEY_PATH (or --private-key) is required.",
                file=sys.stderr,
            )
            return 2
        try:
            private_key = load_ed25519_private_key(key_path)
        except (OSError, ValueError) as exc:
            print(f"Failed to load private key: {exc}", file=sys.stderr)
            return 2
        issuer = args.issuer or OFFICIAL_ISSUER
        doc = build_entitlement_ed25519(
            fingerprint=fp,
            private_key=private_key,
            issuer=issuer,
            expires_at=args.expires_at,
        )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
