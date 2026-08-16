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
from runtime_store.main_daemon import status as daemon_status
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




def mapping_column_label() -> str:
    """Live-table column title for the backend address (Merker / entity / channel)."""
    if config.is_ehal_ha_backend():
        return "Mapping auf Home Assistant"
    if config.is_ehal_openems_backend():
        return "Mapping auf OpenEMS"
    return "Mapping auf Loxone"








def _network_write_mapping() -> dict[str, str]:
    if config.is_ehal_ha_backend():
        return ha_setpoint_mapping(config.get("EHAL_HA_ENTITIES") or {})
    if config.is_ehal_openems_backend():
        return openems_setpoint_mapping(
            ess_component=str(config.get("EHAL_OPENEMS_ESS_COMPONENT") or "ess0"),
            evcs_component=str(config.get("EHAL_OPENEMS_EVCS_COMPONENT") or "evcs0"),
        )
    return {}












def _omitted_write_caption(raw_count: int, rows: list[dict[str, str]]) -> str | None:
    """Caption when raw traces include Merker not shown in the Live-Schreiben table."""
    shown = sum(1 for row in rows if row.get("Erfolg") in ("Ja", "Nein"))
    omitted = raw_count - shown
    if omitted <= 0:
        return None
    return (
        f"{omitted} weitere Schreibvorgänge (nicht gemappte Legacy-Merker) "
        "sind nicht in der Tabelle."
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
        st.dataframe(
            rows_with_mapping_column_label(rows),
            width="stretch",
            hide_index=True,
        )


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
        rows_with_mapping_column_label(
            build_telemetry_rows(
                dict(telemetry),
                read_at,
                mapping=_telemetry_mapping_for_adapter(adapter),
            )
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
                rows_with_mapping_column_label(build_ehal_write_rows([])),
                width="stretch",
                hide_index=True,
            )
            return
        if silent_run or ehal_writes is None:
            st.info("Silent-Modus beim letzten Lauf — keine EHAL-Schreibvorgänge.")
            st.dataframe(
                rows_with_mapping_column_label(
                    build_intended_write_rows(loxone_sent, completed_at)
                    if loxone_sent
                    else build_ehal_write_rows([])
                ),
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
        st.dataframe(
            rows_with_mapping_column_label(write_rows),
            width="stretch",
            hide_index=True,
        )
        return

    if not has_produktiv_run(main_state):
        st.caption("Noch kein Produktiv-Durchlauf — Sollwerte leer, Mapping aus Config.")
        st.dataframe(
            rows_with_mapping_column_label(build_write_rows_from_trace([])),
            width="stretch",
            hide_index=True,
        )
        return

    loxone_writes = main_state.get("loxone_writes")

    if silent_run or loxone_writes is None:
        st.info("Silent-Modus beim letzten Lauf — keine Schreibvorgänge ausgeführt.")
        st.dataframe(
            rows_with_mapping_column_label(
                build_intended_write_rows(loxone_sent, completed_at)
            ),
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
            rows_with_mapping_column_label(
                build_intended_write_rows(loxone_sent, completed_at)
                if loxone_sent
                else build_write_rows_from_trace([])
            ),
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
    st.dataframe(
        rows_with_mapping_column_label(write_rows),
        width="stretch",
        hide_index=True,
    )


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

from ui.loxone_debug_rows import (  # noqa: E402
    _write_row,
    build_ehal_write_rows,
    build_intended_write_rows,
    build_read_rows,
    build_telemetry_rows,
    build_write_rows_from_trace,
    read_check_status_label,
    render_status_strip,
    rows_with_mapping_column_label,
    status_strip_banner,
    write_summary_from_rows,
)
