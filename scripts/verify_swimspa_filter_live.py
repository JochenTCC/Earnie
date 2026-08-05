#!/usr/bin/env python3
r"""Live-Abnahme Pool/SwimSpa-Filter: Loxone-Formate und natives Fenster prüfen.

Aufruf (Miniserver erreichbar, .env gesetzt):
    .venv\Scripts\python.exe -m scripts.verify_swimspa_filter_live

Prüft pool_filter aus config.json / Hausprofil:
  - get_filter_remaining_hours (Float, Schulden in h)
  - get_filter_native_start_hour / get_filter_native_duration_hours
  - sens_filter_active (binär, Filter läuft)
  - flex.pool_filter.set_enable (Schreib-Merker lesbar)
"""
from __future__ import annotations

import sys
from datetime import datetime

from runtime_store.config_load import load_config_or_exit

config = load_config_or_exit()
from integrations import loxone_client
from integrations.loxone_connectivity import loxone_env_configured, ensure_live_config
from optimizer.filter_context import slot_in_native_window


def _find_pool_filter() -> dict | None:
    for consumer in config.get_flexible_consumers():
        if consumer.get("id") == "pool_filter":
            return consumer
    return None


def _status(ok: bool) -> str:
    return "OK" if ok else "FEHLER"


def _check_sollstunden(consumer: dict) -> tuple[bool, str]:
    from settings.ehal_marker_resolve import marker_get_filter_remaining_hours

    name = marker_get_filter_remaining_hours(consumer)
    if not name:
        return False, "get_filter_remaining_hours fehlt"
    raw = loxone_client.fetch_loxone_raw_value(name)
    value = loxone_client.fetch_loxone_generic_value(name)
    if value is None:
        return False, f"nicht lesbar (raw={raw!r})"
    if value < 0:
        return False, f"negativ: {value} (raw={raw!r})"
    return True, f"{value:.4f} h (raw={raw!r})"


def _check_start_hour(consumer: dict) -> tuple[bool, str]:
    from settings.ehal_marker_resolve import marker_get_filter_native_start_hour

    name = marker_get_filter_native_start_hour(consumer)
    if not name:
        return False, "get_filter_native_start_hour fehlt"
    hour, fmt, raw = loxone_client.fetch_filter_native_start_hour(name)
    if hour is None:
        return False, f"nicht parsebar (raw={raw!r}, format={fmt})"
    return True, f"Start={hour:.0f} h, Format={fmt}, raw={raw!r}"


def _check_duration(consumer: dict) -> tuple[bool, str]:
    from settings.ehal_marker_resolve import marker_get_filter_native_duration_hours

    name = marker_get_filter_native_duration_hours(consumer)
    if not name:
        return False, "get_filter_native_duration_hours fehlt"
    raw = loxone_client.fetch_loxone_raw_value(name)
    value = loxone_client.fetch_loxone_generic_value(name)
    if value is None:
        return False, f"nicht lesbar (raw={raw!r})"
    if value <= 0:
        return False, f"Dauer <= 0: {value} (raw={raw!r})"
    return True, f"{value:.4f} h (raw={raw!r})"


def _check_binary(label: str, io_name: str) -> tuple[bool, str]:
    if not io_name:
        return False, "Merkername fehlt"
    raw = loxone_client.fetch_loxone_raw_value(io_name)
    value = loxone_client.fetch_loxone_generic_value(io_name)
    if value is None:
        return False, f"nicht lesbar (raw={raw!r})"
    if value not in (0.0, 1.0):
        return False, f"erwartet 0/1, erhalten {value} (raw={raw!r})"
    return True, f"{int(value)} (raw={raw!r})"


def _native_window_summary(
    start_hour: float | None,
    duration_hours: float | None,
) -> str:
    if start_hour is None or duration_hours is None:
        return "natives Fenster nicht bestimmbar"
    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    inside = slot_in_native_window(now, start_hour, duration_hours)
    return (
        f"Fenster [{start_hour:.0f}, {start_hour + duration_hours:.2f}) h — "
        f"jetzt {'INNERHALB (Earnie-Zusatz gesperrt)' if inside else 'AUSSERHALB (Zusatz möglich)'}"
    )


def main() -> int:
    if not loxone_env_configured():
        print(
            "FEHLER: LOXONE_IP, LOXONE_USER und LOXONE_PASS müssen in .env gesetzt sein.",
            file=sys.stderr,
        )
        return 2

    try:
        ensure_live_config()
    except (FileNotFoundError, ValueError, KeyError) as exc:
        print(f"FEHLER: Konfiguration ungültig: {exc}", file=sys.stderr)
        return 2

    from settings.ehal_marker_resolve import (
        marker_flex_enable,
        marker_get_filter_native_duration_hours,
        marker_get_filter_native_start_hour,
        marker_sens_filter_active,
    )

    consumer = _find_pool_filter()
    if consumer is None:
        print(
            "FEHLER: pool_filter fehlt in flexible_consumers "
            "(Hausprofil / Planungspfad prüfen).",
            file=sys.stderr,
        )
        return 2

    checks: list[tuple[str, bool, str]] = []

    ok, detail = _check_sollstunden(consumer)
    checks.append(("Sollstunden (Schulden)", ok, detail))

    ok, detail = _check_start_hour(consumer)
    checks.append(("Natives Fenster Start", ok, detail))
    start_hour = None
    if ok:
        start_hour, _, _ = loxone_client.fetch_filter_native_start_hour(
            marker_get_filter_native_start_hour(consumer)
        )

    ok, detail = _check_duration(consumer)
    checks.append(("Natives Fenster Dauer", ok, detail))
    duration = None
    if ok:
        duration = loxone_client.fetch_loxone_generic_value(
            marker_get_filter_native_duration_hours(consumer)
        )

    ok, detail = _check_binary("Filter läuft", marker_sens_filter_active(consumer))
    checks.append(("Filter läuft (Ist)", ok, detail))

    ok, detail = _check_binary("Earnie-Freigabe", marker_flex_enable(consumer))
    checks.append(("Earnie Filter-Freigabe", ok, detail))

    print("Pool-Filter Live-Abnahme\n")
    for label, passed, detail in checks:
        print(f"[{_status(passed)}] {label}: {detail}")

    print(f"\n{_native_window_summary(start_hour, duration)}")

    all_ok = all(passed for _, passed, _ in checks)
    if all_ok:
        print("\nAlle Pool-Filter-Prüfungen erfolgreich.")
        return 0

    failed = sum(1 for _, passed, _ in checks if not passed)
    print(f"\n{failed} von {len(checks)} Prüfungen fehlgeschlagen.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
