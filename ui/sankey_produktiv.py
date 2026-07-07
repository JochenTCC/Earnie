"""Produktiv-Durchlauf-Kontext für das Live-Sankey (main.py → App)."""
from __future__ import annotations

from optimizer import steuerbefehl_for_mode
from runtime_store import run_state
from ui.chart_colors import (
    SANKEY_DEFAULT_LINK_COLOR,
    SANKEY_FLEX_MISMATCH_COLOR,
    SANKEY_SOLL_PLACEHOLDER_LINK_COLOR,
)

PRODUKTIV_RUN_FRESH_SEC = 120
KW_TOLERANCE = 0.02
MIN_REAL_FLOW_KW = 0.01
SOLL_PLACEHOLDER_FLOW_KW = 0.05
FLEX_MISMATCH_COLOR = SANKEY_FLEX_MISMATCH_COLOR
_DEFAULT_LINK_COLOR = SANKEY_DEFAULT_LINK_COLOR
_SOLL_PLACEHOLDER_LINK_COLOR = SANKEY_SOLL_PLACEHOLDER_LINK_COLOR


def mode_label(mode: int) -> str:
    return {
        0: "Normal",
        1: "Zwangs-Laden",
        2: "Halten",
        3: "Zwangs-Entladen",
    }.get(int(mode), str(mode))


def kw_match(a: float, b: float) -> bool:
    return abs(float(a) - float(b)) <= KW_TOLERANCE


def has_produktiv_run(state: dict | None) -> bool:
    """Letzter erfolgreicher main.py-Lauf — Soll-Werte im Sankey anzeigen."""
    return bool(state and state.get("success"))


def produktiv_run_fresh(state: dict | None) -> bool:
    """Durchlauf jünger als PRODUKTIV_RUN_FRESH_SEC (z. B. für Live-Snapshot)."""
    if not has_produktiv_run(state):
        return False
    age = run_state.age_seconds(state)
    return age is not None and age <= PRODUKTIV_RUN_FRESH_SEC


def _format_age_text(age_sec: float | None) -> str:
    if age_sec is None:
        return "?"
    if age_sec < 120:
        return f"{int(age_sec)} s"
    return f"{int(age_sec // 60)} min"


def produktiv_caption(state: dict | None) -> str:
    if not has_produktiv_run(state):
        return (
            "Noch kein Produktiv-Durchlauf von **main.py** — Anzeige nur mit Live-Daten aus Loxone."
        )
    completed = state.get("completed_at", "?")
    age_txt = _format_age_text(run_state.age_seconds(state))
    target_power = float(state.get("target_power_kw", 0.0) or 0.0)
    target_soc = float(state.get("target_soc_percent", 0.0) or 0.0)
    caption = (
        f"Letzter Produktiv-Durchlauf: **{completed}** · vor **{age_txt}** · "
        f"Modus: **{mode_label(int(state.get('mode', 0)))}** · "
        f"Ziel: **{target_power:.2f} kW** / **{target_soc:.0f} % SoC**"
    )
    if not produktiv_run_fresh(state):
        caption += " · _Soll-Werte aus diesem Lauf, Live kann abweichen._"
    return caption


def _soll_flex_kw(state: dict, consumer_id: str) -> float:
    return float((state.get("consumer_powers_kw") or {}).get(consumer_id, 0.0) or 0.0)


def battery_node_label(current_soc: float, battery_kw: float, state: dict) -> str:
    if battery_kw >= 0:
        live_txt = f"live Entladen {battery_kw:.2f} kW"
    else:
        live_txt = f"live Laden {abs(battery_kw):.2f} kW"
    mode = int(state.get("mode", 0))
    target_power = float(state.get("target_power_kw", 0.0) or 0.0)
    target_soc = float(state.get("target_soc_percent", 0.0) or 0.0)
    cmd = steuerbefehl_for_mode(mode, target_power)
    return (
        f"🔋 Batterie ({current_soc:.1f} % · {live_txt} · "
        f"Soll: {cmd} → {target_soc:.0f} % SoC)"
    )


def flex_node_label(name: str, live_kw: float, consumer_id: str, state: dict) -> str:
    soll_kw = _soll_flex_kw(state, consumer_id)
    return f"⚡ {name} (live {live_kw:.2f} kW · Soll {soll_kw:.2f} kW)"


def flex_node_color(
    palette_color: str,
    live_kw: float,
    consumer_id: str,
    state: dict,
) -> str:
    if not kw_match(live_kw, _soll_flex_kw(state, consumer_id)):
        return FLEX_MISMATCH_COLOR
    return palette_color


def flex_sankey_link(
    live_kw: float,
    consumer_id: str,
    state: dict | None,
) -> tuple[float | None, bool]:
    """
    Sankey-Link für einen Flex-Verbraucher.

    Gibt (link_kw, is_soll_placeholder) zurück. link_kw=None → kein sichtbarer Link.
    Platzhalter-Band nur zur Knoten-Sichtbarkeit wenn live≈0, Soll>0.
    """
    live = float(live_kw or 0.0)
    if live > MIN_REAL_FLOW_KW:
        return live, False
    if not has_produktiv_run(state):
        return None, False
    soll = _soll_flex_kw(state, consumer_id)
    if soll > MIN_REAL_FLOW_KW:
        return SOLL_PLACEHOLDER_FLOW_KW, True
    return None, False


def flex_link_hover(live_kw: float, consumer_id: str, state: dict, is_placeholder: bool) -> str:
    if is_placeholder:
        soll = _soll_flex_kw(state, consumer_id)
        return f"Geplant (inaktiv)<br>Soll: {soll:.2f} kW<br>Ist: 0,00 kW"
    return f"Ist: {float(live_kw or 0.0):.2f} kW"
