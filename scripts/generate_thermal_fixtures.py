#!/usr/bin/env python3
"""Erzeugt minimale Loxone-CSV-Fixtures für thermische Tests."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "tests" / "fixtures" / "thermal"


def _fmt_value(value: float, decimals: int) -> str:
    return f"{value:.{decimals}f}".replace(".", ",")


def _write_series(path: Path, header: str, rows: list[tuple[datetime, float]]) -> None:
    lines = [header]
    for dt, value in rows:
        lines.append(
            f"{dt.strftime('%d.%m.%Y')};{dt.strftime('%H:%M:%S')};{_fmt_value(value, 2)}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="latin-1")


def _write_power(path: Path, rows: list[tuple[datetime, float]]) -> None:
    lines = ["Datum;Zeit;Dummy;Leistung"]
    for dt, value in rows:
        lines.append(
            f"{dt.strftime('%d.%m.%Y')};{dt.strftime('%H:%M:%S')};0,0;{_fmt_value(value, 3)}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="latin-1")


def generate_thermal_fixtures() -> None:
    TARGET.mkdir(parents=True, exist_ok=True)
    start = datetime(2025, 6, 1, 0, 0)
    temp_rows: list[tuple[datetime, float]] = []
    ambient_rows: list[tuple[datetime, float]] = []
    power_rows: list[tuple[datetime, float]] = []
    actual_c = 38.0
    for hour in range(72):
        dt = start + timedelta(hours=hour)
        ambient_c = 10.0
        power_kw = 0.0 if hour < 60 else 5.0
        if power_kw < 2.0:
            actual_c = max(ambient_c + 6.0, actual_c - 0.35)
        else:
            actual_c = min(39.0, actual_c + 0.5)
        temp_rows.append((dt, actual_c))
        ambient_rows.append((dt, ambient_c))
        power_rows.append((dt, power_kw))

    _write_series(
        TARGET / "SwimSpa_currenttemperature_fixture.csv",
        "Datum;Zeit;Ist-Temperatur",
        temp_rows,
    )
    _write_series(
        TARGET / "Aussentemperatur_Einfahrt_fixture.csv",
        "Datum;Zeit;Aussen-Temperatur",
        ambient_rows,
    )
    _write_power(TARGET / "SwimSpa_Verbrauchszaehler_fixture.csv", power_rows)


def main() -> int:
    generate_thermal_fixtures()
    print(f"Thermal-Fixtures geschrieben nach {TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
