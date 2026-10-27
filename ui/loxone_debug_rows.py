"""Loxone/EHAL debug row builders."""
from __future__ import annotations

from typing import Any

import streamlit as st

import config
from integrations import ehal_live
from ui.loxone_debug import (
    _format_age_text,
    mapping_column_label,
    render_ehal_write_error_banner,
)
from integrations.ehal_debug_mapping import (  # noqa: F401  (build_loxone_setpoint_io_index / loxone_write_field_to_io: patched via this module, used by loxone_debug_write_rows)
    build_loxone_setpoint_io_index,
    loxone_write_field_to_io,
    canonicalize_live_display_field,
    expected_live_read_fields,
    is_live_read_field,
    mapping_or_dash,
    ordered_union,
    parse_check_wert,
)
from integrations.loxone_connectivity import LoxoneCheck, loxone_env_configured
from runtime_store import run_state
from runtime_store.main_daemon import status as daemon_status
from ui.ehal_unit_display import live_read_pair
from ui.sankey_produktiv import has_produktiv_run
from ui.loxone_debug_write_rows import (  # noqa: F401  (re-exported)
    _DASH,
    _enrich_write_row,
    _live_backend,
    _network_display_backend,
    _success_label,
    _write_row,
    build_ehal_write_rows,
    build_intended_write_rows,
    build_write_rows_from_trace,
    write_summary_from_rows,
)







def _enrich_read_row(
    row: dict[str, str],
    *,
    backend: str,
    value_space: str,
    hub_unit_hint: str | None = None,
) -> dict[str, str]:
    """Add Wert (EHAL); keep Wert as hub/raw side (or — when only EHAL known)."""
    hub, ehal = live_read_pair(
        row.get("EHAL-Feld", ""),
        backend,  # type: ignore[arg-type]
        row.get("Wert", ""),
        value_space=value_space,  # type: ignore[arg-type]
        hub_unit_hint=hub_unit_hint,
    )
    return {
        "EHAL-Feld": row.get("EHAL-Feld", ""),
        "Wert": hub if str(row.get("Wert", "")).strip() else row.get("Wert", ""),
        "Wert (EHAL)": ehal if str(row.get("Wert", "")).strip() else "",
        "Status": row.get("Status", ""),
        "Detail": row.get("Detail", ""),
        "Zuletzt gelesen": row.get("Zuletzt gelesen", ""),
    }




def status_strip_banner(silent: bool, daemon_running: bool) -> tuple[str, str]:
    """Return (streamlit_level, message) for Silent/Loud × daemon state."""
    from runtime_store.shadow.mode import is_shadow_mode

    if is_shadow_mode():
        if daemon_running:
            return (
                "info",
                "Shadow-Modus - Optimierer läuft (Feed), keine Backend-Schreibzugriffe",
            )
        return (
            "warning",
            "Shadow-Modus - Optimierer-Dienst läuft nicht",
        )
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
    if item.state:
        return item.state
    if item.passed:
        return "OK"
    if item.severity == "warning":
        return "Warnung"
    return "Fehler"


def _live_field_to_push_ehal_id(field: str) -> str:
    """Map a Live-Lesen row label to a push inbox EHAL ID (bare / entity-scoped / qualified)."""
    from ehal.qualified_ids import GRID_KINDS, field_kind, qualified_plant_id

    name = str(field or "").strip()
    if not name:
        return ""
    if ":" in name:
        # Legacy ``{consumer}:{stored_key}`` — prefer the stored key when already qualified.
        tail = name.split(":", 1)[1].strip()
        return tail
    kind = field_kind(name)
    if kind in GRID_KINDS:
        return qualified_plant_id(kind)
    return name


def _inbox_last_read_local(ehal_id: str) -> str:
    """Local ``HH:MM:SS`` from the push inbox ``last_ts``, or empty."""
    eid = str(ehal_id or "").strip()
    if not eid:
        return ""
    try:
        from datetime import datetime, timezone

        from runtime_store.loxone_push_inbox import memory_snapshot

        row = memory_snapshot().get(eid)
        if not row:
            return ""
        parsed = datetime.fromisoformat(str(row.get("last_ts") or ""))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone().strftime("%H:%M:%S")
    except Exception:  # noqa: BLE001
        return ""


def _try_push_live_row(
    field: str,
    *,
    read_at: str,
    backend: str = "loxone",
) -> dict[str, str] | None:
    """Build a Live-Lesen row from the push inbox when a numeric value resolves."""
    from ehal.loxone_push_source import is_pushable_kind
    from ehal.push_signals import REQUEST_OPTIMIZE_ID
    from ehal.qualified_ids import field_kind
    from runtime_store.loxone_push_inbox import read_control_receipt, read_push_value

    ehal_id = _live_field_to_push_ehal_id(field)
    if not ehal_id:
        return None
    if ehal_id == REQUEST_OPTIMIZE_ID:
        try:
            value, state, last_ts = read_control_receipt(ehal_id)
        except Exception:  # noqa: BLE001
            return None
        if value is None:
            return None
        last = _inbox_last_read_local(ehal_id) or last_ts or read_at
        return _enrich_read_row(
            {
                "EHAL-Feld": field,
                "Wert": str(value),
                "Status": state,
                "Detail": "",
                "Zuletzt gelesen": last,
            },
            backend=backend,
            value_space="hub",
        )
    if not is_pushable_kind(field_kind(ehal_id)):
        return None
    try:
        value, state = read_push_value(ehal_id)
    except Exception:  # noqa: BLE001
        return None
    if value is None:
        return None
    last = _inbox_last_read_local(ehal_id) or read_at
    value_space = "ehal" if backend == "ha" else "hub"
    return _enrich_read_row(
        {
            "EHAL-Feld": field,
            "Wert": str(value),
            "Status": state,
            "Detail": "",
            "Zuletzt gelesen": last,
        },
        backend=backend,
        value_space=value_space,
    )

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

def _empty_mapped_read_row(field: str, read_at: str) -> dict[str, str]:
    return _enrich_read_row(
        {
            "EHAL-Feld": field,
            "Wert": "",
            "Status": "Kein Mapping",
            "Detail": "",
            "Zuletzt gelesen": read_at,
        },
        backend="loxone",
        value_space="hub",
    )


def _read_row_from_check(
    field: str, item: LoxoneCheck, *, mapping: str, read_at: str
) -> dict[str, str]:
    wert = parse_check_wert(item.detail, passed=item.passed)
    if wert and field.endswith("get_evcs_ready_by_time"):
        from integrations.ehal_live import format_ready_by_display

        wert = format_ready_by_display(wert)
    ehal_id = _live_field_to_push_ehal_id(field)
    last = read_at
    if item.state:
        last = _inbox_last_read_local(ehal_id) or read_at
    status = "Kein Mapping" if not mapping else read_check_status_label(item)
    return _enrich_read_row(
        {
            "EHAL-Feld": field,
            "Wert": wert,
            "Status": status,
            "Detail": "" if item.passed else item.detail,
            "Zuletzt gelesen": last,
        },
        backend="loxone",
        value_space="hub",
    )


def build_read_rows(
    checks: list[LoxoneCheck],
    read_at: str,
    *,
    expected_fields: list[str] | None = None,
) -> list[dict[str, str]]:
    by_label: dict[str, LoxoneCheck] = {}
    for item in checks:
        if not is_live_read_field(item.label):
            continue
        key = canonicalize_live_display_field(item.label, has_batteries=False)
        if key:
            by_label[key] = item
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
        mapping = str(item.io_name or "").strip() if item is not None else ""
        if ehal_live.is_ha_push_transport():
            push_row = _try_push_live_row(field, read_at=read_at, backend="ha")
            if push_row is not None:
                rows.append(push_row)
            else:
                rows.append(_empty_mapped_read_row(field, read_at))
            continue
        if item is None or not mapping:
            push_row = _try_push_live_row(field, read_at=read_at)
            if push_row is not None:
                rows.append(push_row)
                continue
            if item is None:
                rows.append(_empty_mapped_read_row(field, read_at))
                continue
        rows.append(
            _read_row_from_check(field, item, mapping=mapping, read_at=read_at)
        )
    return rows


def build_telemetry_rows(
    telemetry: dict[str, Any],
    read_at: str,
    *,
    mapping: dict[str, str] | None = None,
    expected_fields: list[str] | None = None,
    backend: str | None = None,
    push_info: dict[str, tuple[str, str, float | None]] | None = None,
    push_details: dict[str, str] | None = None,
) -> list[dict[str, str]]:
    """Live-Lesen rows.

    ``push_info`` (HA): qualified id → (push state, last receipt, last pushed value
    with ``ehal.ha.sign`` applied). ``push_details``: qualified id → Detail note.

    HA bindings carry no entity ids (activation keys only), so "mapped" cannot come
    from ``mapping``; an activated push signal shows its inbox state and receipt time.
    """
    push = push_info or {}
    details = push_details or {}
    source: dict[str, str] = {}
    for k, v in (mapping or {}).items():
        key = canonicalize_live_display_field(str(k), has_batteries=False)
        val = str(v or "").strip()
        if key and val:
            source[key] = val
    present: dict[str, Any] = {}
    for field, value in telemetry.items():
        if not is_live_read_field(str(field)):
            continue
        key = canonicalize_live_display_field(str(field), has_batteries=False)
        if key:
            present[key] = value
    ordered = ordered_union(
        expected_fields
        if expected_fields is not None
        else expected_live_read_fields(network_backend=True),
        sorted(present),
    )
    hub = _network_display_backend(backend)
    rows: list[dict[str, str]] = []
    for field in ordered:
        if not is_live_read_field(field):
            continue
        mapped = mapping_or_dash(source, field)
        seen_at = read_at
        if field in push:
            state, last_seen, pushed = push[field]
            if field in present:
                wert = str(present[field])
            else:
                wert = "" if pushed is None else str(pushed)
            status = state
            seen_at = last_seen or read_at
        elif field in present:
            wert = str(present[field])
            status = "OK" if mapped else "Kein Mapping"
        else:
            wert = ""
            status = "Kein Mapping" if not mapped else "Fehlt"
        rows.append(
            _enrich_read_row(
                {
                    "EHAL-Feld": field,
                    "Wert": wert,
                    "Status": status,
                    "Detail": details.get(field, ""),
                    "Zuletzt gelesen": seen_at,
                },
                backend=hub,
                value_space="ehal",
            )
        )
    return rows









def render_status_strip(main_state: dict | None) -> None:
    silent = config.is_silent_mode()
    daemon_running = daemon_status().state == "running"
    level, message = status_strip_banner(silent, daemon_running)
    if level == "success":
        st.success(message)
    elif level == "info":
        st.info(message)
    else:
        st.warning(message)

    render_ehal_write_error_banner()

    ehal_net = ehal_live.is_ehal_network_backend()

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
