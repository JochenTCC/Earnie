"""EHAL-Com warning for energy counters too coarse for quarter-hour Ist."""
from __future__ import annotations

from typing import Any

from integrations.loxone_meter_energy import COUNTER_MAX_STEP_KWH, coarse_channel_label


def coarse_counter_warning_text(
    channels: dict[str, str],
    consumers: list[dict[str, Any]] | None = None,
) -> str | None:
    """Markdown warning for ``{channel: last seen}``; ``None`` when nothing is coarse."""
    if not channels:
        return None
    lines = [
        f"- {coarse_channel_label(channel, consumers)} — zuletzt {seen.replace('T', ' ')}"
        for channel, seen in sorted(channels.items())
    ]
    step = f"{COUNTER_MAX_STEP_KWH:.2f}".replace(".", ",")
    return (
        "**Zählerstände zu grob — bitte handeln.** Diese Zähler melden ihren Stand nur "
        f"in Schritten über {step} kWh (z. B. ganze kWh):\n\n"
        + "\n".join(lines)
        + "\n\nEine Viertelstunde bekäme sonst den ganzen Zählerschritt (1 kWh = 4 kW) und "
        "die übrigen 0. Earnie nimmt für diese Kanäle deshalb den Leistungs-Mittelwert, "
        "nicht den Zähler. **Abhilfe:** den Zählerstand mit 3 Nachkommastellen senden — "
        "Loxone: im Virtual-Output-Befehl `<v.3>` statt `<v>`; kommt der Wert schon als "
        "`…000` an, liefert bereits der Zähler in Loxone nur ganze kWh (Quelle bzw. "
        "Zählerbaustein prüfen). Home Assistant: Energie-Sensor mit Wh-Auflösung. Die "
        "Warnung verschwindet, sobald der Zähler wieder fein genug zählt."
    )


def render_coarse_counter_warning() -> None:
    import streamlit as st

    from integrations.loxone_meter_energy import load_live_profile_consumers
    from runtime_store.power_interval_sampler import coarse_counter_channels

    text = coarse_counter_warning_text(
        coarse_counter_channels(), load_live_profile_consumers()
    )
    if text:
        st.warning(text)
