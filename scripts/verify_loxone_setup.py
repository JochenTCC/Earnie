#!/usr/bin/env python3
"""Loxone-Umgebung prüfen (Installations- / Smoke-Test).

Aufruf:
    python -m scripts.verify_loxone_setup
    python -m scripts.verify_loxone_setup --ftp
    python -m scripts.verify_loxone_setup --roundtrip

Voraussetzungen: .env mit LOXONE_IP, LOXONE_USER, LOXONE_PASS und config.json
"""
from __future__ import annotations

import argparse
import sys

from integrations.loxone_connectivity import (
    loxone_env_configured,
    verify_loxone_setup,
)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prüft Loxone-Verbindung und konfigurierte IO-Namen."
    )
    parser.add_argument(
        "--ftp",
        action="store_true",
        help="Zusätzlich FTP-Zugang und Logdatei prüfen",
    )
    parser.add_argument(
        "--roundtrip",
        action="store_true",
        help="SoC-Sollwert lesen, unverändert zurückschreiben und erneut lesen",
    )
    return parser.parse_args(argv)


def _print_results(results: list) -> None:
    for item in results:
        status = "OK" if item.passed else "FEHLER"
        target = f" ({item.io_name})" if item.io_name else ""
        print(f"[{status}] {item.label}{target}: {item.detail}")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if not loxone_env_configured():
        print(
            "FEHLER: LOXONE_IP, LOXONE_USER und LOXONE_PASS müssen in .env gesetzt sein.",
            file=sys.stderr,
        )
        return 2

    try:
        ok, results = verify_loxone_setup(
            include_ftp=args.ftp,
            include_roundtrip=args.roundtrip,
        )
    except (FileNotFoundError, ValueError, KeyError) as exc:
        print(f"FEHLER: Konfiguration ungültig: {exc}", file=sys.stderr)
        return 2

    _print_results(results)
    if ok:
        print("\nAlle Loxone-Prüfungen erfolgreich.")
        return 0

    failed = sum(1 for item in results if not item.passed)
    print(f"\n{failed} von {len(results)} Prüfungen fehlgeschlagen.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
