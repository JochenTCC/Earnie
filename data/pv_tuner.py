# pv_tuner.py — PV interval energy via ∫ sens_pv_production_active × Δt
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Optional

from integrations import ehal_live
from runtime_store.file_metadata import (
    read_schema_version,
    stamp_payload,
    strip_metadata,
)
from runtime_store.persist_paths import pv_counter_state_file

logger = logging.getLogger(__name__)

STATE_FILE = pv_counter_state_file()
# Schema 2: last_ts + last_power_w (W). Schema 1 was cumulative last_total_pv (kWh).
_PV_INTEGRAL_SCHEMA = 2


def _save_state_atomic(file_path: str, data: dict) -> None:
    """Write JSON in place (Docker bind-mount compatible)."""
    payload = stamp_payload(strip_metadata(data), schema_version=_PV_INTEGRAL_SCHEMA)
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=4)
    except Exception as e:
        logger.error("Fehler beim Schreiben der State-Datei %s: %s", file_path, e)
        raise e


def _load_pv_integral_state() -> dict | None:
    if not os.path.exists(STATE_FILE) or os.path.getsize(STATE_FILE) == 0:
        return None
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
        schema_version = read_schema_version(state, default=1)
        if schema_version > _PV_INTEGRAL_SCHEMA:
            logger.warning(
                "pv_counter_state: neuere Schema-Version %s (aktuell %s) – lese best effort",
                schema_version,
                _PV_INTEGRAL_SCHEMA,
            )
        return strip_metadata(state)
    except Exception as e:
        logger.exception("Fehler beim Lesen von pv_counter_state.json: %s", e)
        return None


def _read_pv_power_w() -> float | None:
    live = ehal_live.read_live_power_kw()
    if live is None:
        logger.error("PV-Integral: keine Live-Leistung (EHAL) verfügbar.")
        return None
    return max(0.0, float(live["pv"]) * 1000.0)


def _delta_kwh_from_state(
    power_w: float, now: datetime, state: dict
) -> float | None:
    """Trapezoid ∫ over [last_ts, now]; None if state lacks integral fields."""
    last_ts = state.get("last_ts")
    last_power = state.get("last_power_w")
    if last_ts is None or last_power is None:
        return None
    try:
        prev = datetime.fromisoformat(str(last_ts))
    except ValueError:
        logger.warning("PV-Integral: ungültiges last_ts=%r — State wird neu aufgebaut.", last_ts)
        return None
    dt_h = (now - prev).total_seconds() / 3600.0
    if dt_h < 0:
        logger.warning("PV-Integral: negatives Δt (%.3f h) — Delta = 0.", dt_h)
        return 0.0
    if dt_h == 0:
        return 0.0
    avg_w = (float(last_power) + float(power_w)) / 2.0
    return max(0.0, avg_w / 1000.0 * dt_h)


def _new_integral_state(power_w: float, now: datetime) -> dict:
    return {
        "last_power_w": float(power_w),
        "last_ts": now.isoformat(timespec="seconds"),
    }


def get_pv_delta_peek() -> Optional[float]:
    """PV interval energy (kWh) without updating state (event runs)."""
    power_w = _read_pv_power_w()
    if power_w is None:
        return None
    state = _load_pv_integral_state()
    if state is None:
        logger.warning(
            "PV-Delta (peek): Kein pv_counter_state — Event-Lauf ohne Stunden-Delta."
        )
        return None
    now = datetime.now()
    pv_delta = _delta_kwh_from_state(power_w, now, state)
    if pv_delta is None:
        logger.warning(
            "PV-Delta (peek): State ohne Integral-Felder (z. B. alter Zähler-State)."
        )
        return None
    logger.info("PV-Delta (peek, ohne State-Update): %.3f kWh", pv_delta)
    return pv_delta


def get_pv_delta_and_update() -> Optional[float]:
    """
    Integrate live PV power over Δt since last sample; persist timestamp/power.
    First sample (or legacy counter-only state) returns None and seeds state.
    """
    power_w = _read_pv_power_w()
    if power_w is None:
        return None

    now = datetime.now()
    state = _load_pv_integral_state()
    if state is None:
        try:
            _save_state_atomic(STATE_FILE, _new_integral_state(power_w, now))
            logger.info(
                "Erststart: PV-Leistung gesichert (%.0f W) — kein Delta für dieses Intervall.",
                power_w,
            )
        except Exception as e:
            logger.exception("Fehler beim Erstellen der State-Datei: %s", e)
        return None

    pv_delta = _delta_kwh_from_state(power_w, now, state)
    if pv_delta is None:
        try:
            _save_state_atomic(STATE_FILE, _new_integral_state(power_w, now))
            logger.info(
                "PV-State migriert auf Integral (%.0f W) — kein Delta für dieses Intervall.",
                power_w,
            )
        except Exception as e:
            logger.exception("Fehler beim Migrieren der State-Datei: %s", e)
        return None

    try:
        _save_state_atomic(STATE_FILE, _new_integral_state(power_w, now))
        logger.info("PV-Integral aktualisiert. Delta: %.3f kWh", pv_delta)
    except Exception as e:
        logger.exception("Fehler beim Aktualisieren der State-Datei: %s", e)

    return pv_delta
