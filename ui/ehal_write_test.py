"""EHAL-Com Schreibtest UI: multi-field table + one-shot batch write/roundtrip."""
from __future__ import annotations

from typing import Any

import streamlit as st

import config
from integrations.ehal_write_test import (
    ACTIVE_POWER_MAX_ABS_W,
    DEFAULT_ROUNDTRIP_WAIT_S,
    FORCE_ESS_ACTIVE_POWER,
    RoundtripStatus,
    WriteTestClampError,
    WriteTestSilentError,
    allowed_probe_fields,
    default_ev_nominal_a,
    looks_like_housesim,
    mapped_write_targets,
    probe_value_bounds,
    restore_safe_setpoints,
    roundtrip_batch,
    write_probes,
    writes_allowed,
)

_SESSION_PENDING = "ehal_write_test_pending"
_SESSION_RESULT = "ehal_write_test_result"
_DEFAULT_FORCE_W = 100.0


def render_write_test_section() -> None:
    """Expander under Live-Schreiben: table of probes, one send / roundtrip."""
    with st.expander("Schreibtest", expanded=False):
        st.caption(
            "Mehrere gemappte Sollwerte in einer Tabelle setzen und mit **einem** "
            "Klick schreiben (ein Setpoint-Dokument). Optional Auto-Roundtrip. "
            "Gleicher Adapter-Pfad wie der Produktiv-Lauf."
        )
        if looks_like_housesim():
            st.info(
                "HouseSim / Lab-Adapter erkannt — ideal zum Testen, "
                "bevor echte Anlagenwerte geschrieben werden."
            )

        silent = not writes_allowed()
        if silent:
            st.warning(
                "Silent-Modus aktiv — Schreibtest deaktiviert. "
                "Silent auf **Optimierer-Dienst** bzw. in der Statusleiste ausschalten."
            )

        force = st.checkbox(
            f"``set_ess_active_power`` in Tabelle freigeben (±{ACTIVE_POWER_MAX_ABS_W:g} W)",
            value=False,
            key="ehal_write_test_force",
            disabled=silent,
            help=(
                "Blendet die Zeile ``set_ess_active_power`` ein (Default "
                f"{_DEFAULT_FORCE_W:g} W). Schreibt **nicht** automatisch — "
                "Wert in der Tabelle setzen, dann „Alle schreiben“."
            ),
        )

        try:
            fields = allowed_probe_fields(force_ess_active=bool(force))
            targets = mapped_write_targets()
        except (ValueError, OSError) as exc:
            st.error(f"Adapter/Mapping nicht verfügbar: {exc}")
            return

        if not fields:
            st.caption(
                "Keine gemappten Probe-Felder. ESS-/EVCS-Bindings auf EHAL-Com setzen."
            )
            return

        max_kw = float(config.get_battery_params().get("max_power_kw") or 0.0)
        ev_a = default_ev_nominal_a()
        selected = _render_probe_table(
            fields,
            targets=targets,
            max_power_kw=max_kw,
            ev_nominal_a=ev_a,
            force_ess_active=bool(force),
            disabled=silent,
        )

        wait_s = st.number_input(
            "Roundtrip-Wartezeit (s)",
            min_value=0.0,
            max_value=10.0,
            value=float(DEFAULT_ROUNDTRIP_WAIT_S),
            step=0.5,
            key="ehal_write_test_wait",
            disabled=silent,
        )

        col_manual, col_auto, col_restore = st.columns(3)
        with col_manual:
            if st.button(
                "Alle schreiben",
                key="ehal_write_test_manual_btn",
                disabled=silent or not selected,
                type="primary",
            ):
                _queue_action(
                    "manual",
                    values=selected,
                    force=bool(force),
                    wait_s=float(wait_s),
                )
                st.rerun()
        with col_auto:
            if st.button(
                "Auto-Roundtrip",
                key="ehal_write_test_auto_btn",
                disabled=silent or not selected,
            ):
                _queue_action(
                    "roundtrip",
                    values=selected,
                    force=bool(force),
                    wait_s=float(wait_s),
                )
                st.rerun()
        with col_restore:
            if st.button(
                "Sicher wiederherstellen",
                key="ehal_write_test_restore_btn",
                disabled=silent,
                help="ESS Automatik + EVCS 0 A (wie Startup-Safe-Push).",
            ):
                _queue_action("restore", values={}, force=False, wait_s=0.0)
                st.rerun()

        pending = st.session_state.get(_SESSION_PENDING)
        if isinstance(pending, dict) and pending.get("action"):
            _confirm_write_test_dialog()

        _render_last_result()


def _render_probe_table(
    fields: list[str],
    *,
    targets: dict[str, str],
    max_power_kw: float,
    ev_nominal_a: float | None,
    force_ess_active: bool,
    disabled: bool,
) -> dict[str, Any]:
    """Render include+value rows; return selected field→value map."""
    hdr = st.columns([0.8, 2.4, 2.8, 2.0])
    hdr[0].markdown("**Senden**")
    hdr[1].markdown("**EHAL-Feld**")
    hdr[2].markdown("**Mapping**")
    hdr[3].markdown("**Wert**")

    selected: dict[str, Any] = {}
    for field in fields:
        include_default = True
        cols = st.columns([0.8, 2.4, 2.8, 2.0])
        include = cols[0].checkbox(
            "Senden",
            value=include_default,
            key=f"ehal_write_test_incl_{field}",
            disabled=disabled,
            label_visibility="collapsed",
        )
        cols[1].markdown(f"`{field}`")
        cols[2].caption(targets.get(field) or "—")
        value = _render_row_value(
            field,
            max_power_kw=max_power_kw,
            ev_nominal_a=ev_nominal_a,
            force_ess_active=force_ess_active,
            disabled=disabled or not include,
            container=cols[3],
        )
        if include and value is not None:
            selected[field] = value
    return selected


def _render_row_value(
    field: str,
    *,
    max_power_kw: float,
    ev_nominal_a: float | None,
    force_ess_active: bool,
    disabled: bool,
    container: Any,
) -> Any:
    lo, hi, unit = probe_value_bounds(
        field,
        max_power_kw=max_power_kw,
        ev_nominal_a=ev_nominal_a,
        force_ess_active=force_ess_active,
    )
    if field == "set_ess_mode":
        labels = {0: "0 Automatik", 1: "1 Laden", 2: "2 Entladen"}
        return container.selectbox(
            "Wert",
            options=[0, 1, 2],
            format_func=lambda m: labels[m],
            key=f"ehal_write_test_val_{field}",
            disabled=disabled,
            label_visibility="collapsed",
        )

    if lo is None or hi is None:
        container.caption(unit or "—")
        return None

    default = _default_probe_value(field, hi=float(hi))
    step = 100.0 if unit == "W" and field == FORCE_ESS_ACTIVE_POWER else (
        1.0 if unit == "W" else 0.5
    )
    return container.number_input(
        f"Wert ({unit})",
        min_value=float(lo),
        max_value=float(hi),
        value=float(default),
        step=float(step),
        key=f"ehal_write_test_val_{field}",
        disabled=disabled,
        label_visibility="collapsed",
    )


def _default_probe_value(field: str, *, hi: float) -> float:
    if field == FORCE_ESS_ACTIVE_POWER:
        return min(_DEFAULT_FORCE_W, ACTIVE_POWER_MAX_ABS_W, hi if hi > 0 else _DEFAULT_FORCE_W)
    if "limit" in field and hi > 0:
        return min(hi, 1000.0) if hi >= 1000 else hi
    return 0.0


def _queue_action(
    action: str,
    *,
    values: dict[str, Any],
    force: bool,
    wait_s: float,
) -> None:
    st.session_state[_SESSION_PENDING] = {
        "action": action,
        "values": dict(values),
        "force": force,
        "wait_s": wait_s,
        "force_confirmed": False,
    }


@st.dialog("Schreibtest bestätigen")
def _confirm_write_test_dialog() -> None:
    pending = st.session_state.get(_SESSION_PENDING) or {}
    action = str(pending.get("action") or "")
    values = pending.get("values") if isinstance(pending.get("values"), dict) else {}

    if action == "restore":
        st.markdown(
            "Sichere Sollwerte schreiben (**ESS Automatik**, **EVCS 0 A**) "
            "auf das **live** Backend?"
        )
        col_yes, col_no = st.columns(2)
        with col_yes:
            if st.button("Ja, wiederherstellen", type="primary", key="ewt_restore_yes"):
                _run_restore()
                st.session_state.pop(_SESSION_PENDING, None)
                st.rerun()
        with col_no:
            if st.button("Abbrechen", key="ewt_restore_no"):
                st.session_state.pop(_SESSION_PENDING, None)
                st.rerun()
        return

    has_force = FORCE_ESS_ACTIVE_POWER in values
    if has_force and not pending.get("force_confirmed"):
        st.error(
            f"**Zweite Bestätigung:** ``{FORCE_ESS_ACTIVE_POWER} = "
            f"{values.get(FORCE_ESS_ACTIVE_POWER)!r}`` "
            f"(max ±{ACTIVE_POWER_MAX_ABS_W:g} W) erzwingt Batterieleistung."
        )
        st.caption("Nur wenn Sie bewusst testen — danach wiederherstellen.")
        col_yes, col_no = st.columns(2)
        with col_yes:
            if st.button(
                "Ja, Force bestätigen",
                type="primary",
                key="ewt_force_yes",
            ):
                pending = dict(pending)
                pending["force_confirmed"] = True
                st.session_state[_SESSION_PENDING] = pending
                st.rerun()
        with col_no:
            if st.button("Abbrechen", key="ewt_force_no"):
                st.session_state.pop(_SESSION_PENDING, None)
                st.rerun()
        return

    verb = "Auto-Roundtrip" if action == "roundtrip" else "Alle schreiben"
    lines = ", ".join(f"`{k}={v!r}`" for k, v in values.items()) or "—"
    st.markdown(
        f"**{verb}:** {lines} — schreibt **live** auf das Smarthome-Backend "
        "(ein Setpoint-Dokument)."
    )
    if has_force:
        st.caption("Force ESS-Leistung ist in der Auswahl enthalten.")
    col_yes, col_no = st.columns(2)
    with col_yes:
        if st.button("Ja, ausführen", type="primary", key="ewt_run_yes"):
            _execute_pending()
            st.session_state.pop(_SESSION_PENDING, None)
            st.rerun()
    with col_no:
        if st.button("Abbrechen", key="ewt_run_no"):
            st.session_state.pop(_SESSION_PENDING, None)
            st.rerun()


def _execute_pending() -> None:
    pending = st.session_state.get(_SESSION_PENDING) or {}
    action = str(pending.get("action") or "")
    values = pending.get("values") if isinstance(pending.get("values"), dict) else {}
    force = bool(pending.get("force"))
    wait_s = float(pending.get("wait_s") or DEFAULT_ROUNDTRIP_WAIT_S)
    max_kw = float(config.get_battery_params().get("max_power_kw") or 0.0)
    ev_a = default_ev_nominal_a()

    try:
        if action == "manual":
            error, clamped = write_probes(
                values,
                force_ess_active=force,
                max_power_kw=max_kw,
                ev_nominal_a=ev_a,
            )
            if error is None:
                st.session_state[_SESSION_RESULT] = {
                    "kind": "manual_ok",
                    "values": clamped,
                    "message": (
                        "Schreiben OK: "
                        + ", ".join(f"{k}={v!r}" for k, v in clamped.items())
                    ),
                }
            else:
                st.session_state[_SESSION_RESULT] = {
                    "kind": "manual_err",
                    "values": clamped,
                    "message": str(error.get("message") or error),
                }
            return

        if action == "roundtrip":
            result = roundtrip_batch(
                values,
                force_ess_active=force,
                wait_s=wait_s,
                restore=True,
                max_power_kw=max_kw,
                ev_nominal_a=ev_a,
            )
            st.session_state[_SESSION_RESULT] = {
                "kind": f"roundtrip_{result.status.value}",
                "values": result.written,
                "echoes": result.echoes,
                "message": result.message,
            }
    except WriteTestSilentError as exc:
        st.session_state[_SESSION_RESULT] = {"kind": "silent", "message": str(exc)}
    except WriteTestClampError as exc:
        st.session_state[_SESSION_RESULT] = {"kind": "clamp", "message": str(exc)}
    except (ValueError, OSError, TypeError) as exc:
        st.session_state[_SESSION_RESULT] = {"kind": "error", "message": str(exc)}


def _run_restore() -> None:
    try:
        if not writes_allowed():
            raise WriteTestSilentError(
                "Silent-Modus aktiv — Wiederherstellen blockiert."
            )
        restore_safe_setpoints()
        st.session_state[_SESSION_RESULT] = {
            "kind": "restore_ok",
            "message": "Sichere Sollwerte gesendet (ESS Automatik, EVCS 0 A).",
        }
    except WriteTestSilentError as exc:
        st.session_state[_SESSION_RESULT] = {"kind": "silent", "message": str(exc)}
    except (ValueError, OSError, TypeError) as exc:
        st.session_state[_SESSION_RESULT] = {"kind": "error", "message": str(exc)}


def _render_last_result() -> None:
    result = st.session_state.get(_SESSION_RESULT)
    if not isinstance(result, dict):
        return
    kind = str(result.get("kind") or "")
    message = str(result.get("message") or "")
    if kind in ("manual_ok", "restore_ok", f"roundtrip_{RoundtripStatus.PASS.value}"):
        st.success(message)
    elif kind == f"roundtrip_{RoundtripStatus.PARTIAL.value}":
        st.warning(message)
    else:
        st.error(message)
    echoes = result.get("echoes")
    if isinstance(echoes, dict) and echoes:
        st.caption(
            "Echo: "
            + ", ".join(f"{k}={v!r}" for k, v in echoes.items())
        )
