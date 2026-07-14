#!/usr/bin/env python3
"""Erzeugt minimale Loxone-CSV-Fixtures für thermische Tests."""
from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "tests" / "fixtures" / "thermal"


def _load_thermal_model():
    path = ROOT / "optimizer" / "thermal_model.py"
    module_name = "thermal_model_gen"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"thermal_model nicht ladbar: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


_tm = _load_thermal_model()
ThermalBand = _tm.ThermalBand
capacity_kwh_per_k_from_volume = _tm.capacity_kwh_per_k_from_volume
simulate_next_temp_c = _tm.simulate_next_temp_c

FREEZER_U_KW_PER_K = 0.003
FREEZER_VOLUME_L = 350.0
FREEZER_SETPOINT_C = -18.0
FREEZER_TOLERANCE_C = 2.0
FREEZER_EFFICIENCY = 0.85
FREEZER_COMPRESSOR_KW = 0.15


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


def _generate_swimspa_fixtures() -> None:
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


def _generate_freezer_fixtures() -> None:
    """Zweites thermal_rc-Referenzmodell (Gefrierschrank, RC-Simulation mit bekannter U)."""
    start = datetime(2025, 1, 15, 0, 0)
    ambient_c = 22.0
    capacity = capacity_kwh_per_k_from_volume(FREEZER_VOLUME_L)
    band = ThermalBand(setpoint_c=FREEZER_SETPOINT_C, tolerance_c=FREEZER_TOLERANCE_C)
    temp_c = FREEZER_SETPOINT_C
    compressor_on = False

    temp_rows: list[tuple[datetime, float]] = []
    ambient_rows: list[tuple[datetime, float]] = []
    power_rows: list[tuple[datetime, float]] = []

    for hour in range(720):
        dt = start + timedelta(hours=hour)
        next_no_heat = simulate_next_temp_c(
            temp_c,
            ambient_c,
            0.0,
            capacity_kwh_per_k=capacity,
            heat_loss_kw_per_k=FREEZER_U_KW_PER_K,
            heating_efficiency=FREEZER_EFFICIENCY,
        )
        if next_no_heat > band.max_c:
            compressor_on = True
        elif next_no_heat < band.min_c:
            compressor_on = False
        power_kw = FREEZER_COMPRESSOR_KW if compressor_on else 0.0
        temp_c = simulate_next_temp_c(
            temp_c,
            ambient_c,
            power_kw,
            capacity_kwh_per_k=capacity,
            heat_loss_kw_per_k=FREEZER_U_KW_PER_K,
            heating_efficiency=FREEZER_EFFICIENCY,
        )
        temp_rows.append((dt, round(temp_c, 2)))
        ambient_rows.append((dt, ambient_c))
        power_rows.append((dt, power_kw))

    _write_series(
        TARGET / "Freezer_currenttemperature_fixture.csv",
        "Datum;Zeit;Ist-Temperatur",
        temp_rows,
    )
    _write_series(
        TARGET / "Freezer_ambient_fixture.csv",
        "Datum;Zeit;Raum-Temperatur",
        ambient_rows,
    )
    _write_power(TARGET / "Freezer_Verbrauchszaehler_fixture.csv", power_rows)


def generate_thermal_fixtures() -> None:
    TARGET.mkdir(parents=True, exist_ok=True)
    _generate_swimspa_fixtures()
    _generate_freezer_fixtures()


def main() -> int:
    generate_thermal_fixtures()
    print(f"Thermal-Fixtures geschrieben nach {TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
