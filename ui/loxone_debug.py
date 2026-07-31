"""EHAL-Com: Live-Lese- und Schreib-Debug für die Streamlit-UI."""
from __future__ import annotations

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
from ui.fragment_refresh import STATUS_FRAGMENT_RUN_EVERY
from ui.runtime_config import reload_runtime_config
from ui.setup_dotenv import render_loxone_verify_results
from ui.sankey_produktiv import has_produktiv_run


def _format_age_text(age_sec: float | None) -> str:
    if age_sec is None:
        return "?"
    if age_sec < 120:
        return f"{int(age_sec)} s"
    return f"{int(age_sec // 60)} min"


def read_check_status_label(item: LoxoneCheck) -> str:
    if item.passed:
        return "OK"
    if item.severity == "warning":
        return "Warnung"
    return "Fehler"


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
        rows.append(
            {
                "EHAL-Feld": field,
                "Mapping": mapping,
                "Wert": parse_check_wert(item.detail, passed=item.passed),
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


def _network_write_mapping() -> dict[str, str]:
    if config.is_ehal_ha_backend():
        return ha_setpoint_mapping(config.get("EHAL_HA_ENTITIES") or {})
    if config.is_ehal_openems_backend():
        return openems_setpoint_mapping(
            ess_component=str(config.get("EHAL_OPENEMS_ESS_COMPONENT") or "ess0"),
            evcs_component=str(config.get("EHAL_OPENEMS_EVCS_COMPONENT") or "evcs0"),
        )
    return {}


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
                mapping=io_name,
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
                mapping=io_name or configured,
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


def _omitted_write_caption(raw_count: int, rows: list[dict[str, str]]) -> str | None:
    """Caption when raw traces include non-set_* Merker not shown in the table."""
    shown = sum(1 for row in rows if row.get("Erfolg") in ("Ja", "Nein"))
    omitted = raw_count - shown
    if omitted <= 0:
        return None
    return (
        f"{omitted} weitere Schreibvorgänge (Freigabe/Legacy-Merker) "
        "sind nicht als set_* in der Tabelle."
    )


def _telemetry_mapping_for_adapter(adapter: Any) -> dict[str, str]:
    if config.is_ehal_ha_backend():
        entities = getattr(getattr(adapter, "cfg", None), "entities", None)
        mapping = ha_telemetry_mapping(entities)
        if "sens_power_consumers" not in mapping:
            mapping = dict(mapping)
            mapping["sens_power_consumers"] = "—(abgeleitet)"
        return mapping
    cfg = getattr(adapter, "cfg", None)
    return openems_telemetry_mapping(
        ess_component=str(getattr(cfg, "ess_component", None) or "ess0"),
        evcs_component=str(getattr(cfg, "evcs_component", None) or "evcs0"),
    )


def render_status_strip(main_state: dict | None) -> None:
    silent = config.is_loxone_silent_mode()
    ehal_net = config.is_ehal_network_backend()
    if ehal_net:
        hub = "HA" if config.is_ehal_ha_backend() else "OpenEMS"
        if silent:
            st.warning(
                f"**Silent-Modus aktiv** — EHAL/{hub}-Setpoints werden nicht gesendet."
            )
        else:
            st.success(
                f"**{hub}-EHAL** — `main.py` sendet M1-Setpoints an {hub} REST."
            )
    elif silent:
        st.warning("**Silent-Modus aktiv** — Steuerwerte werden nicht an Loxone gesendet.")
    else:
        st.success("**Live-Modus** — `main.py` sendet Steuerwerte an Loxone.")

    render_ehal_write_error_banner()

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
            "**Anbindung** auf dieser Seite ein."
        )
        return

    if not has_produktiv_run(main_state):
        st.info("Noch kein Produktiv-Durchlauf von **main.py** — Schreib-Historie leer.")
        return

    completed = main_state.get("completed_at", "?")
    age_txt = _format_age_text(run_state.age_seconds(main_state))
    st.caption(f"Letzter **main.py**-Lauf: **{completed}** · vor **{age_txt}**")


def render_ehal_write_error_banner() -> None:
    """Show last EHAL Write-Error-Telemetry from runtime/ehal_write_error.json."""
    from integrations.ehal_live import load_write_error

    error = load_write_error()
    if not error:
        return
    fields = ", ".join(error.get("failed_fields") or [])
    hub = error.get("hub_status")
    hub_txt = f" (Hub-Status: {hub})" if hub else ""
    st.error(
        f"**EHAL Schreibfehler** — {error.get('message', 'unbekannt')} "
        f"| Felder: {fields or '—'}{hub_txt}"
    )


@st.fragment(run_every=STATUS_FRAGMENT_RUN_EVERY)
def _render_live_reads_fragment() -> None:
    reload_runtime_config()
    read_at = datetime.now().isoformat(timespec="seconds")

    if not loxone_env_configured():
        st.caption("Live-Lesen nicht möglich — Zugangsdaten fehlen.")
        return

    try:
        checks = run_read_checks()
    except Exception as exc:
        st.error(f"Loxone-Lese-Prüfung fehlgeschlagen: {exc}")
        return

    ok = sum(1 for item in checks if item.passed)
    st.caption(f"{ok}/{len(checks)} Merker erfolgreich gelesen · Stand **{read_at}**")
    rows = build_read_rows(checks, read_at)
    if rows:
        st.dataframe(rows, width="stretch", hide_index=True)


@st.fragment(run_every=STATUS_FRAGMENT_RUN_EVERY)
def _render_ehal_telemetry_fragment() -> None:
    reload_runtime_config()
    read_at = datetime.now().isoformat(timespec="seconds")
    from integrations.ehal_live import get_network_adapter, read_live_power_kw
    from integrations.ha_adapter import HaHttpError
    from integrations.openems_adapter import OpenemsHttpError

    try:
        adapter = get_network_adapter()
        telemetry = adapter.read_telemetry()
    except (OpenemsHttpError, HaHttpError, ValueError, OSError) as exc:
        st.error(f"EHAL-Telemetrie fehlgeschlagen: {exc}")
        return

    st.caption(f"EHAL-Telemetrie · Stand **{read_at}**")
    st.dataframe(
        build_telemetry_rows(
            dict(telemetry),
            read_at,
            mapping=_telemetry_mapping_for_adapter(adapter),
        ),
        width="stretch",
        hide_index=True,
    )
    power = read_live_power_kw()
    if power:
        st.caption(
            f"Live-Leistung (kW): PV {power['pv']} · Haus {power['house']} · "
            f"Batterie {power['battery']} · Netz {power['grid']}"
        )


def render_live_reads_section() -> None:
    st.subheader("Live-Lesen")
    if config.is_ehal_network_backend():
        hub = "HA" if config.is_ehal_ha_backend() else "OpenEMS"
        st.caption(
            f"Backend **{hub}/EHAL** — nur `sens_*` / `get_*` Telemetrie über REST."
        )
        if st.button("Verbindung testen", key="ehal_debug_test_connection"):
            from integrations.ehal_live import get_network_adapter
            from integrations.ha_adapter import HaHttpError
            from integrations.openems_adapter import OpenemsHttpError

            try:
                telemetry = get_network_adapter().read_telemetry()
                st.success(f"Verbindung OK — {len(dict(telemetry))} Felder gelesen.")
                st.json(dict(telemetry))
            except (OpenemsHttpError, HaHttpError, ValueError, OSError) as exc:
                st.error(f"Verbindungstest fehlgeschlagen: {exc}")
        st.caption("Tabelle unten aktualisiert sich automatisch (ca. alle 10 Sekunden).")
        if st.button("Jetzt aktualisieren", key="ehal_debug_refresh_reads"):
            st.rerun()
        _render_ehal_telemetry_fragment()
        return

    render_loxone_verify_results(button_key="loxone_debug_verify_button")
    st.caption(
        "Nur `sens_*` / `get_*` / `{id}:flex.{slug}.sens_power_act` · Tabelle aktualisiert sich "
        "automatisch (ca. alle 10 Sekunden)."
    )
    if st.button("Jetzt aktualisieren", key="loxone_debug_refresh_reads"):
        st.rerun()
    _render_live_reads_fragment()


def render_last_writes_section(main_state: dict | None) -> None:
    st.subheader("Live-Schreiben")

    silent_now = config.is_loxone_silent_mode()
    silent_run = bool((main_state or {}).get("loxone_silent_mode"))
    completed_at = str((main_state or {}).get("completed_at") or "")
    loxone_sent = (main_state or {}).get("loxone_sent") or {}
    ehal_writes = (main_state or {}).get("ehal_writes")

    if config.is_ehal_network_backend():
        if not has_produktiv_run(main_state):
            st.caption("Noch kein Produktiv-Durchlauf — Sollwerte leer, Mapping aus Config.")
            st.dataframe(
                build_ehal_write_rows([]),
                width="stretch",
                hide_index=True,
            )
            return
        if silent_run or ehal_writes is None:
            st.info("Silent-Modus beim letzten Lauf — keine EHAL-Schreibvorgänge.")
            st.dataframe(
                build_intended_write_rows(loxone_sent, completed_at)
                if loxone_sent
                else build_ehal_write_rows([]),
                width="stretch",
                hide_index=True,
            )
            return
        write_rows = build_ehal_write_rows(ehal_writes or [])
        summary = write_summary_from_rows(write_rows)
        failed = [
            row for row in write_rows if row.get("Erfolg") == "Nein"
        ]
        if ehal_writes:
            if failed:
                st.error(summary)
            else:
                st.success(summary)
            omitted = _omitted_write_caption(len(ehal_writes), write_rows)
            if omitted:
                st.caption(omitted)
        else:
            st.caption("Letzter Lauf ohne EHAL-Schreibdatensätze.")
        st.dataframe(write_rows, width="stretch", hide_index=True)
        return

    if not has_produktiv_run(main_state):
        st.caption("Noch kein Produktiv-Durchlauf — Sollwerte leer, Mapping aus Config.")
        st.dataframe(
            build_write_rows_from_trace([]),
            width="stretch",
            hide_index=True,
        )
        return

    loxone_writes = main_state.get("loxone_writes")

    if silent_run or loxone_writes is None:
        st.info("Silent-Modus beim letzten Lauf — keine Schreibvorgänge ausgeführt.")
        st.dataframe(
            build_intended_write_rows(loxone_sent, completed_at),
            width="stretch",
            hide_index=True,
        )
        if not loxone_sent and silent_now:
            st.caption("Keine `loxone_sent`-Werte im letzten Lauf gespeichert.")
        return

    if not loxone_writes:
        st.warning(
            "Letzter Lauf ohne Silent-Modus, aber keine `loxone_writes` gespeichert "
            "(Lauf vor dem Debug-Update?)."
        )
        st.dataframe(
            build_intended_write_rows(loxone_sent, completed_at)
            if loxone_sent
            else build_write_rows_from_trace([]),
            width="stretch",
            hide_index=True,
        )
        return

    write_rows = build_write_rows_from_trace(loxone_writes)
    failed = [row for row in write_rows if row.get("Erfolg") == "Nein"]
    summary = write_summary_from_rows(write_rows)
    omitted = _omitted_write_caption(len(loxone_writes), write_rows)
    if failed:
        st.error(summary)
    else:
        st.success(summary)
    if omitted:
        st.caption(omitted)
    st.dataframe(write_rows, width="stretch", hide_index=True)

def render_last_run_snapshot_expander(main_state: dict | None) -> None:
    if not has_produktiv_run(main_state):
        return
    with st.expander("Letzter Lauf — Lese-Snapshot aus run_state"):
        st.json(
            {
                "completed_at": main_state.get("completed_at"),
                "soc_percent": main_state.get("soc_percent"),
                "flex_live_kw": main_state.get("flex_live_kw"),
                "flex_measured_ids": main_state.get("flex_measured_ids"),
                "event_trigger_snapshot": main_state.get("event_trigger_snapshot"),
                "consumption_snapshot": main_state.get("consumption_snapshot"),
                "ehal_writes": main_state.get("ehal_writes"),
            }
        )


def render_loxone_debug_block() -> None:
    reload_runtime_config()
    main_state = run_state.load_run_state()
    render_status_strip(main_state)
    render_live_reads_section()
    render_last_writes_section(main_state)
    render_last_run_snapshot_expander(main_state)
