"""Loxone/EHAL debug row builders."""
from __future__ import annotations

import config
from ui.loxone_debug import (
    _format_age_text,
    _network_write_mapping,
    mapping_column_label,
    render_ehal_write_error_banner,
)

from datetime import datetime
from typing import Any

import streamlit as st

import config
from integrations.ehal_debug_mapping import (
    build_loxone_setpoint_io_index,
    expected_live_read_fields,
    expected_live_write_fields,
    ha_setpoint_mapping,
    ha_telemetry_mapping,
    is_live_read_field,
    is_live_write_field,
    loxone_write_field_to_io,
    mapping_or_dash,
    openems_setpoint_mapping,
    openems_telemetry_mapping,
    ordered_union,
    parse_check_wert,
    resolve_loxone_write_field,
)
from integrations.loxone_connectivity import LoxoneCheck, loxone_env_configured, run_read_checks
from runtime_store import run_state
from runtime_store.main_daemon import status as daemon_status
from ui.fragment_refresh import STATUS_FRAGMENT_RUN_EVERY
from ui.runtime_config import reload_runtime_config
from ui.setup_dotenv import render_loxone_verify_results
from ui.sankey_produktiv import has_produktiv_run



def status_strip_banner(silent: bool, daemon_running: bool) -> tuple[str, str]:
    """Return (streamlit_level, message) for Silent/Loud × daemon state."""
    if silent and daemon_running:
        return (
            "warning",
            "Silent-Modus - Optimierer läuft, sendet aber keine Daten",
        )
    if silent:
        return ("warning", "Silent-Modus - Optimierer-Dienst läuft nicht")
    if daemon_running:
        return (
            "success",
            "Loud-Modus - Optimierer läuft und sendet Daten",
        )
    return (
        "warning",
        "Loud-Modus konfiguriert - Optimierer-Dienst läuft nicht "
        "(starten Sie main.py unter Daemon Control)",
    )

def read_check_status_label(item: LoxoneCheck) -> str:
    if item.passed:
        return "OK"
    if item.severity == "warning":
        return "Warnung"
    return "Fehler"

def rows_with_mapping_column_label(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Rename internal ``Mapping`` key to the backend-specific display title.

    Keeps column order: EHAL-Feld, mapping label, then remaining columns.
    """
    label = mapping_column_label()
    if label == "Mapping":
        return rows
    renamed: list[dict[str, str]] = []
    for row in rows:
        out: dict[str, str] = {}
        if "EHAL-Feld" in row:
            out["EHAL-Feld"] = row["EHAL-Feld"]
        if "Mapping" in row:
            out[label] = row["Mapping"]
        for key, value in row.items():
            if key in ("EHAL-Feld", "Mapping"):
                continue
            out[key] = value
        renamed.append(out)
    return renamed

def build_read_rows(
    checks: list[LoxoneCheck],
    read_at: str,
    *,
    expected_fields: list[str] | None = None,
) -> list[dict[str, str]]:
    by_label = {
        item.label: item
        for item in checks
        if is_live_read_field(item.label)
    }
    ordered = ordered_union(
        expected_fields
        if expected_fields is not None
        else expected_live_read_fields(network_backend=False),
        list(by_label),
    )
    rows: list[dict[str, str]] = []
    for field in ordered:
        if not is_live_read_field(field):
            continue
        item = by_label.get(field)
        if item is None:
            rows.append(
                {
                    "EHAL-Feld": field,
                    "Mapping": "",
                    "Wert": "",
                    "Status": "Kein Mapping",
                    "Detail": "",
                    "Zuletzt gelesen": read_at,
                }
            )
            continue
        mapping = str(item.io_name or "").strip()
        wert = parse_check_wert(item.detail, passed=item.passed)
        if wert and field.endswith("get_evcs_ready_by_time"):
            from integrations.loxone_client import format_ready_by_display

            wert = format_ready_by_display(wert)
        rows.append(
            {
                "EHAL-Feld": field,
                "Mapping": mapping,
                "Wert": wert,
                "Status": (
                    "Kein Mapping" if not mapping else read_check_status_label(item)
                ),
                "Detail": "" if item.passed else item.detail,
                "Zuletzt gelesen": read_at,
            }
        )
    return rows

def build_telemetry_rows(
    telemetry: dict[str, Any],
    read_at: str,
    *,
    mapping: dict[str, str] | None = None,
    expected_fields: list[str] | None = None,
) -> list[dict[str, str]]:
    source = mapping or {}
    present = {
        str(field): value
        for field, value in telemetry.items()
        if is_live_read_field(str(field))
    }
    ordered = ordered_union(
        expected_fields
        if expected_fields is not None
        else expected_live_read_fields(network_backend=True),
        sorted(present),
    )
    rows: list[dict[str, str]] = []
    for field in ordered:
        if not is_live_read_field(field):
            continue
        mapped = mapping_or_dash(source, field)
        if field in present:
            rows.append(
                {
                    "EHAL-Feld": field,
                    "Mapping": mapped,
                    "Wert": str(present[field]),
                    "Status": "OK" if mapped else "Kein Mapping",
                    "Detail": "",
                    "Zuletzt gelesen": read_at,
                }
            )
        else:
            rows.append(
                {
                    "EHAL-Feld": field,
                    "Mapping": mapped,
                    "Wert": "",
                    "Status": "Kein Mapping" if not mapped else "Fehlt",
                    "Detail": "",
                    "Zuletzt gelesen": read_at,
                }
            )
    return rows

def _write_row(
    *,
    field: str,
    mapping: str,
    value: str,
    success: str,
    written_at: str,
    message: str,
) -> dict[str, str]:
    return {
        "EHAL-Feld": field,
        "Mapping": mapping,
        "Wert": value,
        "Erfolg": success,
        "Gesendet um": written_at,
        "Meldung": message,
    }

def build_write_rows_from_trace(
    writes: list[dict[str, Any]],
    *,
    expected_fields: list[str] | None = None,
) -> list[dict[str, str]]:
    index = build_loxone_setpoint_io_index()
    field_to_io = loxone_write_field_to_io()
    by_field: dict[str, dict[str, Any]] = {}
    for entry in writes:
        io_name = str(entry.get("io_name") or "").strip()
        field = resolve_loxone_write_field(io_name, index)
        if not is_live_write_field(field):
            continue
        by_field[field] = entry
    ordered = ordered_union(
        expected_fields
        if expected_fields is not None
        else expected_live_write_fields(network_backend=False),
        list(by_field),
    )
    rows: list[dict[str, str]] = []
    for field in ordered:
        if not is_live_write_field(field):
            continue
        entry = by_field.get(field)
        configured = str(field_to_io.get(field) or "").strip()
        if entry is None:
            rows.append(
                _write_row(
                    field=field,
                    mapping=configured,
                    value="",
                    success="",
                    written_at="",
                    message="" if not configured else "Nicht im letzten Lauf",
                )
            )
            continue
        io_name = str(entry.get("io_name") or "").strip() or configured
        rows.append(
            _write_row(
                field=field,
                mapping=configured or io_name,
                value=str(entry.get("value", "")),
                success="Ja" if entry.get("success") else "Nein",
                written_at=str(entry.get("written_at") or ""),
                message="",
            )
        )
    return rows

def build_ehal_write_rows(
    writes: list[dict[str, Any]],
    *,
    mapping: dict[str, str] | None = None,
    expected_fields: list[str] | None = None,
) -> list[dict[str, str]]:
    source = mapping if mapping is not None else _network_write_mapping()
    by_field: dict[str, dict[str, Any]] = {}
    for entry in writes:
        field = str(entry.get("field") or "").strip()
        if not is_live_write_field(field):
            continue
        by_field[field] = entry
    ordered = ordered_union(
        expected_fields
        if expected_fields is not None
        else expected_live_write_fields(network_backend=True),
        list(by_field),
    )
    rows: list[dict[str, str]] = []
    for field in ordered:
        if not is_live_write_field(field):
            continue
        mapped = mapping_or_dash(source, field)
        entry = by_field.get(field)
        if entry is None:
            rows.append(
                _write_row(
                    field=field,
                    mapping=mapped,
                    value="",
                    success="",
                    written_at="",
                    message="" if not mapped else "Nicht im letzten Lauf",
                )
            )
            continue
        rows.append(
            _write_row(
                field=field,
                mapping=mapped,
                value=str(entry.get("value", "")),
                success="Ja" if entry.get("success") else "Nein",
                written_at=str(entry.get("written_at") or ""),
                message=str(entry.get("message") or ""),
            )
        )
    return rows

def build_intended_write_rows(
    loxone_sent: dict[str, float],
    completed_at: str,
    *,
    expected_fields: list[str] | None = None,
) -> list[dict[str, str]]:
    index = build_loxone_setpoint_io_index()
    field_to_io = loxone_write_field_to_io()
    by_field: dict[str, tuple[str, float]] = {}
    for io_name, value in loxone_sent.items():
        field = resolve_loxone_write_field(str(io_name), index)
        if not is_live_write_field(field):
            continue
        by_field[field] = (str(io_name), value)
    ordered = ordered_union(
        expected_fields
        if expected_fields is not None
        else expected_live_write_fields(network_backend=False),
        list(by_field),
    )
    rows: list[dict[str, str]] = []
    for field in ordered:
        if not is_live_write_field(field):
            continue
        configured = str(field_to_io.get(field) or "").strip()
        found = by_field.get(field)
        if found is None:
            rows.append(
                _write_row(
                    field=field,
                    mapping=configured,
                    value="",
                    success="",
                    written_at="",
                    message="" if not configured else "Nicht im letzten Lauf",
                )
            )
            continue
        io_name, value = found
        rows.append(
            _write_row(
                field=field,
                mapping=configured or io_name,
                value=str(value),
                success="Nein",
                written_at=completed_at,
                message="Nicht gesendet (Silent-Modus)",
            )
        )
    return rows

def write_summary_from_rows(rows: list[dict[str, str]]) -> str:
    """Summary for Live-Schreiben: count only rows shown with a write attempt."""
    attempted = [row for row in rows if row.get("Erfolg") in ("Ja", "Nein")]
    if not attempted:
        return "Keine Schreibvorgänge erfasst."
    ok = sum(1 for row in attempted if row.get("Erfolg") == "Ja")
    return f"{ok}/{len(attempted)} Schreibvorgänge erfolgreich"

def render_status_strip(main_state: dict | None) -> None:
    silent = config.is_silent_mode()
    daemon_running = daemon_status().state == "running"
    level, message = status_strip_banner(silent, daemon_running)
    if level == "success":
        st.success(message)
    else:
        st.warning(message)

    render_ehal_write_error_banner()

    ehal_net = config.is_ehal_network_backend()

    if ehal_net:
        if not has_produktiv_run(main_state):
            st.info("Noch kein Produktiv-Durchlauf von **main.py** — Schreib-Historie leer.")
            return
        completed = main_state.get("completed_at", "?")
        age_txt = _format_age_text(run_state.age_seconds(main_state))
        st.caption(f"Letzter **main.py**-Lauf: **{completed}** · vor **{age_txt}**")
        return

    if not loxone_env_configured():
        st.warning(
            "Loxone-Zugangsdaten fehlen. Tragen Sie IP, Benutzer und Passwort unter "
            "**Anbindung** auf **Smarthome-Backend** ein."
        )
        return

    if not has_produktiv_run(main_state):
        st.info("Noch kein Produktiv-Durchlauf von **main.py** — Schreib-Historie leer.")
        return

    completed = main_state.get("completed_at", "?")
    age_txt = _format_age_text(run_state.age_seconds(main_state))
    st.caption(f"Letzter **main.py**-Lauf: **{completed}** · vor **{age_txt}**")
