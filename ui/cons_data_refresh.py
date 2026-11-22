"""Regenerate the consumption baseline (cons_data + profiles) after a house-profile change."""
from __future__ import annotations

import streamlit as st

from data import cons_data_store

_STALE_REASONS = {
    "profile_mismatch": "Die Hauskonfiguration wurde seit der letzten Erzeugung geändert",
    "id_mismatch": "Die Verbraucher der Hauskonfiguration haben sich geändert",
    "missing_meta": "Zu den Verbrauchsdaten fehlt die Meta-Datei",
}


def regenerate_consumption_baseline() -> None:
    """Rewrite the synthetic cons_data rows (measured hours stay) and the profiles from it.

    The profiles (base load, total, flex shape) feed the live planning; without this step
    they would follow the new data only at the next month change.
    """
    from data import profile_manager
    from scripts.generate_cons_data import generate

    generate(source="synthetic")
    profile_manager.generate_consumption_profile()


def stale_baseline_reason() -> str | None:
    """Why the stored consumption baseline no longer fits the live house profile, or None."""
    if not cons_data_store.is_cons_data_populated():
        return None
    return cons_data_store.cons_data_consumer_match_reason()


def render_stale_baseline_notice() -> None:
    """Live monitor: warn about a stale baseline and offer to regenerate it."""
    reason = stale_baseline_reason()
    if reason is None:
        return
    cause = _STALE_REASONS.get(reason, f"Abgleich fehlgeschlagen ({reason})")
    st.warning(
        f"**Verbrauchs-Baseline veraltet:** {cause}. Die synthetischen Verbrauchsdaten "
        "und die daraus berechneten Profile (Planung, SoC BL Ziel) passen nicht mehr dazu. "
        "Beim Neu-Erzeugen bleiben alle gemessenen Stunden erhalten."
    )
    if not st.button("Baseline neu erzeugen", key="live_cons_data_regenerate_btn"):
        return
    with st.status("Erzeuge Verbrauchs-Baseline…", expanded=True) as status:
        try:
            regenerate_consumption_baseline()
        except Exception as exc:
            status.update(label="Erzeugung fehlgeschlagen", state="error")
            st.error(f"Erzeugung fehlgeschlagen: {exc}")
        else:
            status.update(label="Verbrauchs-Baseline erneuert", state="complete")
            st.rerun()
