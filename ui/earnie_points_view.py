"""Read-only Earnie-Points of the live plant (Optimierer-Dienst)."""
from __future__ import annotations

import logging

import streamlit as st

from runtime_store.usage_points import compute_live_points

logger = logging.getLogger(__name__)

PART_LABELS = (
    ("pv", "PV-Anlage"),
    ("storage", "Speicher"),
    ("wallbox", "Wallboxen"),
    ("heat", "Wärmepumpe / Klimaanlage"),
    ("other", "Weitere flexible Großverbraucher"),
)


def _breakdown_rows(result: dict[str, int]) -> list[dict[str, object]]:
    return [{"Bereich": label, "Punkte": int(result[key])} for key, label in PART_LABELS]


def render_earnie_points() -> None:
    """Subheader, total and breakdown; a calculation error is shown, never hidden."""
    st.subheader("Earnie-Points dieser Anlage")
    st.caption(
        "Grobe Größenkennzahl des **Live-Szenarios** (PV, Speicher, Wallboxen, "
        "Wärmepumpen / Klimaanlagen, flexible Großverbraucher). Nur die Gesamtsumme "
        "kann Teil der Nutzungsstatistik sein. Regel: Betriebs-Doku, Abschnitt "
        "Nutzungsstatistik."
    )
    try:
        result = compute_live_points()
    except Exception as exc:  # noqa: BLE001 — UI shows the reason instead of a number
        logger.warning("earnie_points_view: Earnie-Points nicht berechenbar: %s", exc)
        st.warning(f"Earnie-Points nicht berechenbar: {exc}")
        return
    st.metric("Earnie-Points gesamt", int(result["total"]))
    st.table(_breakdown_rows(result))
