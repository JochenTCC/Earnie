"""Monitor: dynamic EV ↔ wallbox assignment per wallbox and the user pick (multi-EV M3).

Reads ``runtime/ev_assignments.json`` (written by the daemon, display only) and writes a pick
request that the daemon applies on its next tick (D4 (d)).
"""
from __future__ import annotations

from typing import Any

import streamlit as st

import config
from house_config.wallboxes import VIEW_DYNAMIC_KEY, is_dynamic_ev
from optimizer.ev_assignment import (
    EVIDENCE_PLUG_MATCH,
    EVIDENCE_TEST_CHARGE,
    EVIDENCE_USER_PICK,
    STATUS_ASSIGNED,
    STATUS_FREE,
    STATUS_PLUGGED_UNKNOWN,
    STATUS_TESTING,
)
from runtime_store import ev_assignments as store

_STATUS_TEXT = {
    STATUS_FREE: "frei",
    STATUS_PLUGGED_UNKNOWN: "Auto angesteckt, noch nicht erkannt",
    STATUS_TESTING: "Probeladung läuft",
    STATUS_ASSIGNED: "zugeordnet",
}
_EVIDENCE_TEXT = {
    EVIDENCE_PLUG_MATCH: "Steckabgleich",
    EVIDENCE_TEST_CHARGE: "Probeladung",
    EVIDENCE_USER_PICK: "Auswahl im Monitor",
}
_POLICY_TEXT = {
    "off": "lädt nicht",
    "pv_only": "lädt nur mit PV-Überschuss",
    "immediate": "lädt sofort mit Höchststrom",
}


def _dynamic_setup() -> tuple[list[dict], dict[str, dict[str, Any]]]:
    evs = [
        c
        for c in config.get_flexible_consumers(raw_dynamic=True)
        if str(c.get("type") or "") == "ev" and is_dynamic_ev(c)
    ]
    wallboxes: dict[str, dict[str, Any]] = {}
    for ev in evs:
        for wallbox in ev.get(VIEW_DYNAMIC_KEY) or []:
            wallboxes.setdefault(wallbox["id"], wallbox)
    return evs, wallboxes


def _ev_label(evs: list[dict], ev_id: str | None) -> str:
    for ev in evs:
        if ev["id"] == ev_id:
            return str(ev.get("name") or ev.get("label") or ev_id)
    return str(ev_id or "")


def _request_pick(wallbox_id: str, ev_id: str, session: str) -> None:
    from runtime_store.optimize_request import OptimizeRequestError, request_optimize

    store.request_pick(wallbox_id, ev_id, session)
    try:
        request_optimize()
    except OptimizeRequestError as exc:
        st.warning(f"Auswahl gespeichert; der Optimierer-Dienst übernimmt sie beim nächsten Takt ({exc}).")
        return
    st.success("Auswahl gesendet — der Optimierer-Dienst übernimmt sie gleich.")


def _render_row(row: dict[str, Any], evs: list[dict], wallboxes: dict[str, dict]) -> None:
    wid = str(row["wallbox_id"])
    wallbox = wallboxes.get(wid) or {}
    status = str(row.get("status") or "")
    text = _STATUS_TEXT.get(status, status)
    if status == STATUS_ASSIGNED:
        evidence = _EVIDENCE_TEXT.get(str(row.get("evidence") or ""), str(row.get("evidence")))
        text = f"{_ev_label(evs, row.get('ev_id'))} ({evidence})"
    elif status in (STATUS_PLUGGED_UNKNOWN, STATUS_TESTING) and wallbox.get("unknown_vehicle"):
        text += f" — {_POLICY_TEXT.get(wallbox['unknown_vehicle'], wallbox['unknown_vehicle'])}"
    st.markdown(f"**{wallbox.get('label') or wid}:** {text}")
    if row.get("note"):
        st.caption(str(row["note"]))
    candidates = [str(c) for c in row.get("candidates") or []]
    if status == STATUS_FREE or not candidates or not row.get("session"):
        return
    cols = st.columns([3, 1])
    choice = cols[0].selectbox(
        "Welches Auto steht hier?",
        options=candidates,
        format_func=lambda ev_id: _ev_label(evs, ev_id),
        key=f"ev_assign_pick_{wid}",
        label_visibility="collapsed",
    )
    if cols[1].button("Zuordnen", key=f"ev_assign_pick_btn_{wid}"):
        _request_pick(wid, str(choice), str(row["session"]))


def render_ev_assignment_panel() -> None:
    """Section „Wallboxen“ on the Monitor page; nothing when no EV is dynamic."""
    evs, wallboxes = _dynamic_setup()
    if not evs:
        return
    st.subheader("Wallboxen")
    snapshot = store.read_assignments_snapshot()
    if snapshot is None:
        st.caption("Der Optimierer-Dienst hat noch keine Wallbox-Zuordnung geschrieben.")
        return
    for row in snapshot.get("wallboxes") or []:
        _render_row(row, evs, wallboxes)
    from settings.ehal_marker_resolve import resolve_lox_marker

    blind = [
        _ev_label(evs, ev["id"])
        for ev in evs
        if not resolve_lox_marker(ev, "sens_ev_charge_power")
    ]
    if blind:
        st.caption(
            "Ohne Signal „Auto-Ladeleistung“ ist keine Probeladung möglich, diese Autos "
            "ordnest du hier zu: " + ", ".join(blind) + "."
        )
    st.caption(f"Stand: {snapshot.get('updated_at')}")
