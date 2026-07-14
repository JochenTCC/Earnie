"""Referenz-thermal_rc-Modelle für Tests (kein NAS-Prod-Row)."""
from __future__ import annotations

from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parent / "thermal"

# Bekannte Modellparameter — müssen zu generate_thermal_fixtures passen.
FREEZER_U_KW_PER_K = 0.003
FREEZER_VOLUME_L = 350.0
FREEZER_SETPOINT_C = -18.0
FREEZER_TOLERANCE_C = 2.0
FREEZER_EFFICIENCY = 0.85
FREEZER_COMPRESSOR_KW = 0.15
FREEZER_HEATING_THRESHOLD_KW = 0.08

FREEZER_THERMAL_RC_CONSUMER: dict = {
    "id": "freezer_ref",
    "label": "Gefrierschrank (Referenz)",
    "type": "thermal_rc",
    "nominal_power_kw": FREEZER_COMPRESSOR_KW,
    "heating_power_threshold_kw": FREEZER_HEATING_THRESHOLD_KW,
    "thermal_rc": {
        "water_volume_liters": FREEZER_VOLUME_L,
        "setpoint_c": FREEZER_SETPOINT_C,
        "tolerance_c": FREEZER_TOLERANCE_C,
        "heat_loss_kw_per_k": FREEZER_U_KW_PER_K,
        "heating_efficiency": FREEZER_EFFICIENCY,
    },
}


def swimspa_history_logs() -> dict[str, str]:
    """Pfade zu synthetischen SwimSpa-Loxone-CSV-Fixtures."""
    actual = FIXTURE_DIR / "SwimSpa_currenttemperature_fixture.csv"
    ambient = FIXTURE_DIR / "Aussentemperatur_Einfahrt_fixture.csv"
    power = FIXTURE_DIR / "SwimSpa_Verbrauchszaehler_fixture.csv"
    if not actual.is_file() or not ambient.is_file() or not power.is_file():
        raise FileNotFoundError(
            "SwimSpa-Fixtures fehlen — bitte `python -m scripts.generate_thermal_fixtures` ausführen."
        )
    return {
        "actual_temp_csv": str(actual),
        "ambient_temp_csv": str(ambient),
        "power_csv": str(power),
    }


def freezer_history_logs() -> dict[str, str]:
    """Pfade zu synthetischen Freezer-Loxone-CSV-Fixtures."""
    actual = FIXTURE_DIR / "Freezer_currenttemperature_fixture.csv"
    ambient = FIXTURE_DIR / "Freezer_ambient_fixture.csv"
    power = FIXTURE_DIR / "Freezer_Verbrauchszaehler_fixture.csv"
    if not actual.is_file() or not ambient.is_file() or not power.is_file():
        raise FileNotFoundError(
            "Freezer-Fixtures fehlen — bitte `python -m scripts.generate_thermal_fixtures` ausführen."
        )
    return {
        "actual_temp_csv": str(actual),
        "ambient_temp_csv": str(ambient),
        "power_csv": str(power),
    }
