#!/usr/bin/env python3
"""Issue a dev HMAC entitlement for a hardware fingerprint (2.4.i spike)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime_store.env_vars import read_env
from runtime_store.registry_entitlement import build_entitlement


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Issue earnie_registry.json (dev HMAC). "
            "Requires EARNIE_REGISTRY_DEV_SECRET."
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
        default="earnie-dev",
        help="Issuer label (default: earnie-dev)",
    )
    parser.add_argument(
        "--expires-at",
        default=None,
        help="Optional ISO-8601 expiry; omit for forever (null)",
    )
    args = parser.parse_args(argv)
    secret = read_env("REGISTRY_DEV_SECRET")
    if not secret:
        print(
            "EARNIE_REGISTRY_DEV_SECRET (or ENERGY_OPTIMIZER_REGISTRY_DEV_SECRET) "
            "is required.",
            file=sys.stderr,
        )
        return 2
    fp = args.fingerprint.strip().lower()
    if len(fp) != 64 or any(c not in "0123456789abcdef" for c in fp):
        print("--fingerprint must be 64 hex characters.", file=sys.stderr)
        return 2
    doc = build_entitlement(
        fingerprint=fp,
        secret=secret,
        issuer=args.issuer,
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
