# pv_tuner.py — PV-Zähler-Delta für cons_data (Adaptation P2 ersetzt später den gesamten Pfad)
import json
import logging
import os
from datetime import datetime
from typing import Optional

import config
from integrations import loxone_client
from runtime_store.file_metadata import (
    PV_COUNTER_STATE_SCHEMA,
    read_schema_version,
    stamp_payload,
    strip_metadata,
)
from runtime_store.persist_paths import pv_counter_state_file

logger = logging.getLogger(__name__)

STATE_FILE = pv_counter_state_file()


def _save_state_atomic(file_path: str, data: dict):
    """
    Schreibt Daten direkt in die JSON-Datei (Docker Bind-Mount kompatibel).
    Nutzt das direkte Überschreiben ('w'), damit die Inode für Docker intakt bleibt.
    """
    payload = stamp_payload(strip_metadata(data), schema_version=PV_COUNTER_STATE_SCHEMA)
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=4)
    except Exception as e:
        logger.error(f"🚨 Fehler beim Schreiben der State-Datei {file_path}: {e}")
        raise e


def _pv_delta_from_counter(current_total_pv: float, state: dict) -> float:
    last_total_pv = state.get("last_total_pv", current_total_pv)
    pv_delta = current_total_pv - last_total_pv
    if pv_delta < 0:
        logger.warning(
            "⚠️ Negatives PV-Delta festgestellt (%.3f kWh). Setze Zustand zurück.",
            pv_delta,
        )
        pv_delta = 0.0
    return pv_delta


def _load_pv_counter_state() -> dict | None:
    if not os.path.exists(STATE_FILE) or os.path.getsize(STATE_FILE) == 0:
        return None
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
        schema_version = read_schema_version(state, default=1)
        if schema_version > PV_COUNTER_STATE_SCHEMA:
            logger.warning(
                "pv_counter_state: neuere Schema-Version %s (aktuell %s) – lese best effort",
                schema_version,
                PV_COUNTER_STATE_SCHEMA,
            )
        return strip_metadata(state)
    except Exception as e:
        logger.exception("🚨 Fehler beim Lesen von pv_counter_state.json: %s", e)
        return None


def get_pv_delta_peek() -> Optional[float]:
    """
    Liest das PV-Delta ohne pv_counter_state zu aktualisieren (Event-Läufe in main.py).
    """
    current_total_pv = loxone_client.fetch_loxone_generic_value(
        config.get("LOXONE_PV_COUNTER_NAME")
    )
    if current_total_pv is None:
        logger.error("Fehler beim Abrufen des PV-Zählerstands von Loxone.")
        return None

    state = _load_pv_counter_state()
    if state is None:
        logger.warning(
            "PV-Delta (peek): Kein pv_counter_state – Event-Lauf ohne Stunden-Delta."
        )
        return None

    pv_delta = _pv_delta_from_counter(current_total_pv, state)
    logger.info("PV-Delta (peek, ohne State-Update): %.3f kWh", pv_delta)
    return pv_delta


def get_pv_delta_and_update() -> Optional[float]:
    """
    Holt den aktuellen PV-Zählerstand, berechnet das Delta zur vorherigen Stunde
    und aktualisiert den Zustand atomar.
    """
    current_total_pv = loxone_client.fetch_loxone_generic_value(
        config.get("LOXONE_PV_COUNTER_NAME")
    )
    if current_total_pv is None:
        logger.error("Fehler beim Abrufen des PV-Zählerstands von Loxone.")
        return None

    state = _load_pv_counter_state()
    if state is None:
        initial_state = {
            "last_total_pv": current_total_pv,
            "last_updated": datetime.now().isoformat(),
        }
        try:
            _save_state_atomic(STATE_FILE, initial_state)
            logger.info(
                "Erststart: PV-Zählerstand gesichert — kein Delta für dieses Intervall."
            )
        except Exception as e:
            logger.exception("🚨 Fehler beim Erstellen der State-Datei: %s", e)
        return None

    pv_delta = _pv_delta_from_counter(current_total_pv, state)
    state["last_total_pv"] = current_total_pv
    state["last_updated"] = datetime.now().isoformat()

    try:
        _save_state_atomic(STATE_FILE, state)
        logger.info("PV-Zählerstand aktualisiert. Delta: %.3f kWh", pv_delta)
    except Exception as e:
        logger.exception("🚨 Fehler beim Aktualisieren der State-Datei: %s", e)

    return pv_delta
