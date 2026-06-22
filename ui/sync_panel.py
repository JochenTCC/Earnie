"""Panel für den letzten Produktiv-Durchlauf von main.py."""
from __future__ import annotations

import streamlit as st

import config
from runtime_store import run_state


def _mode_label(mode: int) -> str:
    return {
        0: "Normal",
        1: "Zwangs-Laden",
        2: "Halten",
        3: "Zwangs-Entladen",
    }.get(int(mode), str(mode))


def render_main_run_sync_panel() -> dict | None:
    """Zeigt den letzten erfolgreichen Produktiv-Durchlauf von main.py."""
    state = run_state.load_run_state()
    if not state or not state.get("success"):
        st.info(
            "Noch kein Produktiv-Durchlauf von **main.py** gespeichert "
            f"(`{run_state.RUN_STATE_FILE}`)."
        )
        return None

    completed = state.get("completed_at", "")
    age = run_state.age_seconds(state)
    age_txt = f"{int(age)} s" if age is not None and age < 120 else (
        f"{int(age // 60)} min" if age is not None else "?"
    )

    st.markdown("#### 🛰️ Produktiv-Durchlauf (main.py)")
    st.caption(
        f"Letzter Lauf: **{completed}** · vor **{age_txt}** · "
        f"Daten read-only aus `{run_state.RUN_STATE_FILE}`"
    )

    cols = st.columns(5)
    cols[0].metric("SoC", f"{state.get('soc_percent', 0):.1f} %")
    cols[1].metric("Modus", _mode_label(state.get("mode", 0)))
    cols[2].metric("Ziel-Leistung", f"{state.get('target_power_kw', 0):.2f} kW")
    cols[3].metric("Ziel-SoC", f"{state.get('target_soc_percent', 0):.0f} %")
    cols[4].metric("PV (letzte h)", f"{state.get('pv_delta_kwh', 0):.3f} kWh")

    flex_live = state.get("flex_live_kw") or {}
    flex_opt = state.get("consumer_powers_kw") or {}
    if flex_live or flex_opt:
        flex_cols = st.columns(max(1, len(config.get_flexible_consumers())))
        for idx, consumer in enumerate(config.get_flexible_consumers()):
            cid = consumer["id"]
            live_kw = float(flex_live.get(cid, 0.0) or 0.0)
            opt_kw = float(flex_opt.get(cid, 0.0) or 0.0)
            flex_cols[idx].metric(
                consumer["name"],
                f"{live_kw:.2f} kW live",
                delta=f"Soll {opt_kw:.2f} kW",
            )

    return state
