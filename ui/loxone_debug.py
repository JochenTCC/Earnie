"""EHAL-Com: Live-Lese- und Schreib-Debug für die Streamlit-UI."""
from __future__ import annotations

from datetime import datetime
from typing import Any

import streamlit as st

import config
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


def build_read_rows(checks: list[LoxoneCheck], read_at: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item in checks:
        rows.append(
            {
                "Label": item.label,
                "IO-Name": item.io_name or "—",
                "Status": read_check_status_label(item),
                "Detail": item.detail,
                "Zuletzt gelesen": read_at,
            }
        )
    return rows


def build_telemetry_rows(telemetry: dict[str, Any], read_at: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for field, value in sorted(telemetry.items()):
        rows.append(
            {
                "EHAL-Feld": str(field),
                "Wert": str(value),
                "Status": "OK",
                "Zuletzt gelesen": read_at,
            }
        )
    return rows


def build_write_rows_from_trace(writes: list[dict[str, Any]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for entry in writes:
        rows.append(
            {
                "IO-Name": str(entry.get("io_name") or "—"),
                "Wert": str(entry.get("value", "")),
                "Erfolg": "Ja" if entry.get("success") else "Nein",
                "Gesendet um": str(entry.get("written_at") or "—"),
            }
        )
    return rows


def build_ehal_write_rows(writes: list[dict[str, Any]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for entry in writes:
        rows.append(
            {
                "EHAL-Feld": str(entry.get("field") or "—"),
                "Wert": str(entry.get("value", "")),
                "Erfolg": "Ja" if entry.get("success") else "Nein",
                "Gesendet um": str(entry.get("written_at") or "—"),
                "Meldung": str(entry.get("message") or ""),
            }
        )
    return rows


def build_intended_write_rows(
    loxone_sent: dict[str, float], completed_at: str
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for io_name, value in sorted(loxone_sent.items()):
        rows.append(
            {
                "IO-Name": io_name,
                "Sollwert": str(value),
                "Status": "Nicht gesendet (Silent-Modus)",
                "Letzter Lauf": completed_at,
            }
        )
    return rows


def write_summary_text(writes: list[dict[str, Any]]) -> str:
    if not writes:
        return "Keine Schreibvorgänge erfasst."
    ok = sum(1 for entry in writes if entry.get("success"))
    return f"{ok}/{len(writes)} Schreibvorgänge erfolgreich"


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
        st.dataframe(rows, use_container_width=True, hide_index=True)


@st.fragment(run_every=STATUS_FRAGMENT_RUN_EVERY)
def _render_ehal_telemetry_fragment() -> None:
    reload_runtime_config()
    read_at = datetime.now().isoformat(timespec="seconds")
    from integrations.ehal_live import get_network_adapter, read_live_power_kw
    from integrations.ha_adapter import HaHttpError
    from integrations.openems_adapter import OpenemsHttpError

    try:
        telemetry = get_network_adapter().read_telemetry()
    except (OpenemsHttpError, HaHttpError, ValueError, OSError) as exc:
        st.error(f"EHAL-Telemetrie fehlgeschlagen: {exc}")
        return

    st.caption(f"EHAL-Telemetrie · Stand **{read_at}**")
    st.dataframe(
        build_telemetry_rows(dict(telemetry), read_at),
        use_container_width=True,
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
        st.caption(f"Backend **{hub}/EHAL** — Telemetrie über REST.")
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
    st.caption("Tabelle unten aktualisiert sich automatisch (ca. alle 10 Sekunden).")
    if st.button("Jetzt aktualisieren", key="loxone_debug_refresh_reads"):
        st.rerun()
    _render_live_reads_fragment()


def render_last_writes_section(main_state: dict | None) -> None:
    st.subheader("Live-Schreiben")

    silent_now = config.is_loxone_silent_mode()
    silent_run = bool((main_state or {}).get("loxone_silent_mode"))

    if not has_produktiv_run(main_state):
        st.caption("Noch kein Produktiv-Durchlauf — keine Schreib-Historie.")
        return

    completed_at = str(main_state.get("completed_at") or "—")
    loxone_sent = main_state.get("loxone_sent") or {}
    ehal_writes = main_state.get("ehal_writes")

    if config.is_ehal_network_backend():
        if silent_run or ehal_writes is None:
            st.info("Silent-Modus beim letzten Lauf — keine EHAL-Schreibvorgänge.")
            if loxone_sent:
                st.caption("Geplante Sollwerte (nicht gesendet):")
                st.dataframe(
                    build_intended_write_rows(loxone_sent, completed_at),
                    use_container_width=True,
                    hide_index=True,
                )
            return
        if not ehal_writes:
            st.caption("Letzter Lauf ohne EHAL-Schreibdatensätze.")
            return
        summary = write_summary_text(ehal_writes)
        failed = [entry for entry in ehal_writes if not entry.get("success")]
        if failed:
            st.error(summary)
        else:
            st.success(summary)
        st.dataframe(
            build_ehal_write_rows(ehal_writes),
            use_container_width=True,
            hide_index=True,
        )
        return

    loxone_writes = main_state.get("loxone_writes")

    if silent_run or loxone_writes is None:
        st.info("Silent-Modus beim letzten Lauf — keine Schreibvorgänge ausgeführt.")
        if loxone_sent:
            st.caption("Geplante Sollwerte (nicht gesendet):")
            st.dataframe(
                build_intended_write_rows(loxone_sent, completed_at),
                use_container_width=True,
                hide_index=True,
            )
        elif silent_now:
            st.caption("Keine `loxone_sent`-Werte im letzten Lauf gespeichert.")
        return

    if not loxone_writes:
        st.warning(
            "Letzter Lauf ohne Silent-Modus, aber keine `loxone_writes` gespeichert "
            "(Lauf vor dem Debug-Update?)."
        )
        if loxone_sent:
            st.caption("Geplante Sollwerte aus `loxone_sent`:")
            rows = [
                {"IO-Name": name, "Sollwert": str(value), "Gesendet um": completed_at}
                for name, value in sorted(loxone_sent.items())
            ]
            st.dataframe(rows, use_container_width=True, hide_index=True)
        return

    failed = [entry for entry in loxone_writes if not entry.get("success")]
    summary = write_summary_text(loxone_writes)
    if failed:
        st.error(summary)
    else:
        st.success(summary)
    st.dataframe(
        build_write_rows_from_trace(loxone_writes),
        use_container_width=True,
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
