"""Prüft Loxone-Steuerwerte gegen den letzten main.py-Durchlauf und korrigiert Abweichungen."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import config
from integrations import loxone_client
from runtime_store import run_state

logger = logging.getLogger(__name__)

SOC_TOLERANCE_PERCENT = 0.1
POWER_TOLERANCE_KW = 0.05


@dataclass(frozen=True)
class LoxoneMismatch:
    io_name: str
    expected: float
    actual: float | None
    corrected: bool
    read_failed: bool


def expected_loxone_snapshot_from_run_state(state: dict[str, Any]) -> dict[str, float] | None:
    """Soll-Zustand aus run_state (bevorzugt gespeichertes loxone_sent)."""
    if not state or not state.get("success"):
        return None

    sent = state.get("loxone_sent")
    if isinstance(sent, dict) and sent:
        return {str(k): float(v) for k, v in sent.items()}

    required = ("mode", "target_power_kw", "target_soc_percent")
    if not all(key in state for key in required):
        logger.warning("run_state ohne loxone_sent und unvollständige Optimierungsdaten")
        return None

    return loxone_client.build_sent_loxone_snapshot(
        int(state["mode"]),
        float(state["target_power_kw"]),
        float(state["target_soc_percent"]),
        state.get("consumer_powers_kw") or {},
        None,
        state.get("consumer_pv_follow") or {},
    )


def _tolerance_for_io(
    io_name: str,
    flex_enable_names: set[str],
    flex_setpoint_names: set[str],
    flex_pv_follow_names: set[str],
) -> float:
    if io_name == config.get("LOXONE_CONTROL_CMD_NAME"):
        return 0.0
    if io_name in flex_enable_names:
        return 0.0
    if io_name in flex_pv_follow_names:
        return 0.0
    if io_name in flex_setpoint_names:
        return POWER_TOLERANCE_KW
    if io_name == config.get("LOXONE_TARGET_SOC_NAME"):
        return SOC_TOLERANCE_PERCENT
    return POWER_TOLERANCE_KW


def _values_match(expected: float, actual: float, tolerance: float) -> bool:
    return abs(expected - actual) <= tolerance


def verify_and_restore_loxone_states(
    expected: dict[str, float],
) -> list[LoxoneMismatch]:
    """Liest Steuer-Merker, vergleicht mit Soll und setzt bei Abweichung zurück."""
    mismatches: list[LoxoneMismatch] = []
    flex_enable_names = {
        str((c.get("loxone_outputs") or {}).get("enable_name", ""))
        for c in config.get_flexible_consumers(optimizer_only=True)
    }
    flex_enable_names.discard("")
    flex_setpoint_names = {
        str((c.get("loxone_outputs") or {}).get("power_setpoint_name", ""))
        for c in config.get_flexible_consumers(optimizer_only=True)
    }
    flex_setpoint_names.discard("")
    flex_pv_follow_names = {
        str((c.get("loxone_outputs") or {}).get("pv_follow_name", ""))
        for c in config.get_flexible_consumers(optimizer_only=True)
    }
    flex_pv_follow_names.discard("")

    for io_name, expected_value in expected.items():
        if not io_name:
            continue

        actual_raw = loxone_client.fetch_loxone_generic_value(io_name)
        if actual_raw is None:
            mismatches.append(
                LoxoneMismatch(io_name, expected_value, None, False, True)
            )
            continue

        actual_value = float(actual_raw)
        tolerance = _tolerance_for_io(
            io_name, flex_enable_names, flex_setpoint_names, flex_pv_follow_names
        )
        if _values_match(expected_value, actual_value, tolerance):
            continue

        corrected = loxone_client.send_loxone_value(io_name, expected_value)
        mismatches.append(
            LoxoneMismatch(io_name, expected_value, actual_value, corrected, False)
        )

    return mismatches


def run_watchdog_cycle() -> list[LoxoneMismatch]:
    """Ein Prüfdurchlauf: run_state laden, vergleichen, ggf. korrigieren."""
    config.reload_config()
    state = run_state.load_run_state()
    expected = expected_loxone_snapshot_from_run_state(state or {})
    if not expected:
        logger.info("Kein gültiger main.py-Sollzustand – Prüfung übersprungen")
        return []

    completed = (state or {}).get("completed_at", "?")
    logger.debug("Prüfe %s Loxone-Merker (main.py %s)", len(expected), completed)
    return verify_and_restore_loxone_states(expected)
