"""EHAL-Com: Push-Inbox (Pilot spike/vo-push-pilot) — Virtual-Output-Pushes im Vergleich zum Poll.

Nur Beobachtung: nichts hier speist den Optimierer. Daten kommen aus
``runtime/loxone_push_inbox.json`` (vom Daemon-Listener geschrieben).
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import streamlit as st

from ehal.qualified_ids import LEGACY_NAMESPACES, NAMESPACES, NS_ESS
from runtime_store import loxone_push_inbox as inbox
from ui.fragment_refresh import STATUS_FRAGMENT_RUN_EVERY

_CONSUMER_NAMESPACES = tuple(ns for ns in NAMESPACES if ns != NS_ESS) + LEGACY_NAMESPACES
_DEFAULT_PORT = 8541
_TOLERANCE_ABS = 0.01
_TOLERANCE_REL = 0.01


def _poll_row_for(ehal_id: str, by_field: dict[str, dict[str, str]]) -> dict[str, str] | None:
    """Live-Lesen row for a pushed ID (plant, Pattern B, or ``{consumer}:{field}``)."""
    if ehal_id in by_field:
        return by_field[ehal_id]
    namespace, _, rest = ehal_id.partition(".")
    slug, _, kind = rest.partition(".")
    legacy_flex = f"flex.{slug}.{kind}"
    # Consumer rows are keyed ``{consumer}:{field}`` with the stored spelling
    # (legacy ``flex.{slug}.*`` for power/enable, bare field for the rest).
    for field, row in by_field.items():
        if ":" not in field:
            continue
        tail = field.split(":", 1)[1]
        if tail == ehal_id or (namespace in _CONSUMER_NAMESPACES and tail == legacy_flex):
            return row
    if namespace in _CONSUMER_NAMESPACES and slug and kind:
        return by_field.get(f"{slug}:{kind}")
    return None


def _compare(push_value: float | None, poll_raw: str) -> tuple[str, str]:
    """(Poll-Wert text, Abweichung text)."""
    poll_value = inbox.parse_push_value(poll_raw)
    if poll_value is None:
        return (poll_raw or "", "—")
    if push_value is None:
        return (f"{poll_value:g}", "—")
    diff = push_value - poll_value
    limit = max(_TOLERANCE_ABS, _TOLERANCE_REL * abs(poll_value))
    label = "gleich" if abs(diff) <= limit else f"Δ {diff:+.3f}"
    return (f"{poll_value:g}", label)


def _local(ts_iso: object) -> str:
    try:
        parsed = datetime.fromisoformat(str(ts_iso))
    except (TypeError, ValueError):
        return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone().strftime("%H:%M:%S")


def build_inbox_rows(
    signals: dict[str, dict[str, Any]],
    poll_rows: list[dict[str, str]] | None = None,
    *,
    now: datetime | None = None,
    repeat_s: float | None = None,
    expected_ids: list[str] | None = None,
) -> list[dict[str, str]]:
    """Table rows for the inbox, sorted by ID.

    ``poll_rows`` are Live-Lesen rows (optional). ``expected_ids`` are signals the saved
    bindings expect: those without a push get a derived state (``0 angenommen`` while the
    link is alive, otherwise ``Unbekannt``).
    """
    by_field = {
        str(row.get("EHAL-Feld") or ""): row for row in (poll_rows or []) if row.get("EHAL-Feld")
    }
    link = inbox.link_alive(signals, repeat_s=repeat_s, now=now)
    rows: list[dict[str, str]] = []
    for ehal_id in sorted(set(signals) | set(expected_ids or [])):
        row = signals.get(ehal_id)
        state, derived = inbox.derive_state(ehal_id, row, link=link, repeat_s=repeat_s, now=now)
        age = inbox.age_seconds(row, now=now) if row else None
        poll = _poll_row_for(ehal_id, by_field) if by_field else None
        poll_text, diff_text = ("", "")
        if poll is not None:
            poll_text, diff_text = _compare(derived, str(poll.get("Wert") or ""))
        interval = (row or {}).get("interval_ema_s")
        rows.append(
            {
                "EHAL-ID": ehal_id,
                "Wert (abgeleitet)": "" if derived is None else f"{derived:g}",
                "Status": state,
                "Roh": str((row or {}).get("raw") or ""),
                "Alter (s)": "" if age is None else str(int(age)),
                "Intervall Ø (s)": "" if interval is None else f"{float(interval):.1f}",
                "Anzahl": str(int((row or {}).get("count") or 0)),
                "Poll-Wert": poll_text,
                "Abweichung": diff_text,
                "Mapping (Poll)": str((poll or {}).get("Mapping") or ""),
                "Zuletzt (lokal)": _local((row or {}).get("last_ts")),
                "Peer": str((row or {}).get("peer") or ""),
            }
        )
    return rows


def expected_signal_ids() -> list[str]:
    """IDs expected from the saved bindings (plus the heartbeat); empty if unreadable."""
    try:
        from ehal.push_signals import HEARTBEAT_ID, read_signals_from_docs
        from ui.house_config_io import _load_components_document, load_house_profiles

        signals = read_signals_from_docs(load_house_profiles(), _load_components_document())
        return [HEARTBEAT_ID] + [s.ehal_id for s in signals]
    except Exception:  # noqa: BLE001 — the expected list is only an aid
        return []


def _poll_rows() -> list[dict[str, str]]:
    """Live-Lesen rows from the Miniserver (same source as the Live-Lesen table)."""
    from integrations.loxone_connectivity import loxone_env_configured, run_read_checks
    from runtime_store.loxone_auth_error import load_loxone_auth_error
    from ui.loxone_debug_rows import build_read_rows

    if not loxone_env_configured() or load_loxone_auth_error():
        return []
    try:
        checks = run_read_checks()
    except Exception:  # noqa: BLE001 — comparison is optional
        return []
    return build_read_rows(checks, datetime.now().isoformat(timespec="seconds"))


@st.fragment(run_every=STATUS_FRAGMENT_RUN_EVERY)
def _render_inbox_fragment() -> None:
    compare = st.checkbox(
        "Mit Poll-Wert vergleichen (liest die gemappten Merker wie Live-Lesen)",
        value=True,
        key="pilot_push_compare",
    )
    signals = inbox.load_inbox()
    expected = expected_signal_ids()
    if not signals and not expected:
        st.caption("Noch keine Pushes empfangen.")
    else:
        rows = build_inbox_rows(
            signals, _poll_rows() if compare else None, expected_ids=expected
        )
        link = inbox.link_alive(signals)
        counts: dict[str, int] = {}
        for row in rows:
            counts[row["Status"]] = counts.get(row["Status"], 0) + 1
        summary = " · ".join(f"{n} {label}" for label, n in sorted(counts.items()))
        st.caption(
            f"Verbindung: **{'aktiv' if link else 'unklar (kein wiederholendes Signal frisch)'}** · "
            f"{len(rows)} Signale · {summary}"
        )
        st.caption(
            f"Analoge Signale: Schweigen länger als 3 × {inbox.expected_repeat_s():g} s gilt bei "
            "lebender Verbindung als 0 (Loxone sendet bei 0 nichts). Digitale Signale: letzter Wert gilt "
            "bis zur nächsten Flanke."
        )
        st.dataframe(rows, width="stretch", hide_index=True)
    if st.button("Inbox leeren", key="pilot_push_clear"):
        inbox.clear_inbox()
        st.rerun(scope="fragment")


def render_push_inbox_section() -> None:
    token_set = bool(str(os.getenv("EARNIE_PILOT_PUSH_TOKEN") or "").strip())
    st.caption(
        "Pilot: Loxone **Virtual Output** sendet den Wert mit Wiederholung an "
        f"`http://<Earnie-Host>:{_DEFAULT_PORT}/ehal/loxone/telemetry/<EHAL-ID>/<v>?t=<Token>` "
        "(`<v>` ist der Wert-Platzhalter im VO-Befehl). Das Token kann auch als Adress-Präfix "
        f"`http://<Earnie-Host>:{_DEFAULT_PORT}/t/<Token>` im VO-Gerät stehen (dann ohne `?t=` im Befehl). "
        "Nur Beobachtung — der Optimierer nutzt diese Werte nicht."
    )
    if not token_set:
        st.info(
            "Pilot-Endpunkt **deaktiviert**: `EARNIE_PILOT_PUSH_TOKEN` ist nicht gesetzt "
            "(in `config/.env`, dann `main.py` neu starten)."
        )
    _render_inbox_fragment()
