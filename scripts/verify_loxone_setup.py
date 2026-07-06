#!/usr/bin/env python3
"""Loxone-Umgebung prüfen (Installations- / Smoke-Test, nur lesend).

Aufruf:
    python -m scripts.verify_loxone_setup

Voraussetzungen: .env mit LOXONE_IP, LOXONE_USER, LOXONE_PASS und config.json
"""
from __future__ import annotations

import sys

from integrations.loxone_connectivity import (
    loxone_env_configured,
    verify_loxone_setup,
)


def _print_results(results: list) -> None:
    for item in results:
        if item.passed:
            status = "OK"
        elif item.severity == "warning":
            status = "WARNUNG"
        else:
            status = "FEHLER"
        target = f" ({item.io_name})" if item.io_name else ""
        print(f"[{status}] {item.label}{target}: {item.detail}")


def main() -> int:
    if not loxone_env_configured():
        print(
            "FEHLER: LOXONE_IP, LOXONE_USER und LOXONE_PASS müssen in .env gesetzt sein.",
            file=sys.stderr,
        )
        return 2

    try:
        ok, results = verify_loxone_setup()
    except (FileNotFoundError, ValueError, KeyError) as exc:
        print(f"FEHLER: Konfiguration ungültig: {exc}", file=sys.stderr)
        return 2

    _print_results(results)
    if ok:
        print("\nAlle Loxone-Prüfungen erfolgreich.")
        return 0

    failed = sum(
        1 for item in results if not item.passed and item.severity != "warning"
    )
    print(f"\n{failed} von {len(results)} Prüfungen fehlgeschlagen.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
