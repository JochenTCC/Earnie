"""Empfehlungsmodus für manuelle Geräte: günstigste Startzeit im Kurzhorizont.

Reine Kosten-/Startzeit-Logik ohne Streamlit- oder Config-Abhängigkeit
(Schritt 3a, Backlog Z. 26). Bewusst getroffene Modell-Entscheidungen:

- Startgüte = reine Netzbezugskosten (€) je möglicher Startstunde; PV wird
  nicht berücksichtigt (Entscheidung 2026-07).
- Sterne (1–5) linear über die Kostenspanne: günstigste Startstunde = 5,
  teuerste = 1. Sind alle Startstunden gleich teuer, gibt es 3 (neutral).
- Ein Lauf darf über das Horizontende hinausreichen, solange genügend
  Planungs-Slots vorliegen; sonst entfallen die betroffenen Startstunden.

Die Planungs-Slots sind stündlich (siehe ``data.profile_manager``); ein Slot
entspricht daher einer Stunde. ``k_act`` ist der Brutto-Netzpreis in Cent/kWh.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

STAR_MIN = 1
STAR_MAX = 5
STAR_NEUTRAL = 3
DEFAULT_HORIZON_H = 6
_EPS = 1e-9


@dataclass(frozen=True)
class StartOption:
    """Eine mögliche Startstunde mit Kosten, Sternen und Ersparnis vs. sofort."""

    start_datetime: datetime
    cost_eur: float
    stars: int
    savings_vs_now_eur: float


@dataclass(frozen=True)
class ApplianceRecommendation:
    """Ergebnis der Startzeit-Empfehlung für ein Gerät."""

    options: list[StartOption]
    cheapest: StartOption
    immediate: StartOption
    skipped_start_slots: int


def _validate_inputs(slots: list, power_kw: float, runtime_h: float, horizon_h: int) -> None:
    if not slots:
        raise ValueError("recommend_start_times: 'slots' darf nicht leer sein.")
    if power_kw <= 0:
        raise ValueError(
            f"recommend_start_times: power_kw muss > 0 sein (erhalten: {power_kw})."
        )
    if runtime_h <= 0:
        raise ValueError(
            f"recommend_start_times: runtime_h muss > 0 sein (erhalten: {runtime_h})."
        )
    if horizon_h < 1:
        raise ValueError(
            f"recommend_start_times: horizon_h muss >= 1 sein (erhalten: {horizon_h})."
        )


def _slot_run_weights(runtime_h: float) -> list[float]:
    """Anteil (in Stunden) je Stundenslot, den ein Lauf von runtime_h belegt."""
    full_hours = int(math.floor(runtime_h + _EPS))
    remainder = runtime_h - full_hours
    weights = [1.0] * full_hours
    if remainder > _EPS:
        weights.append(remainder)
    return weights


def _slot_price_cent(slot: dict) -> float:
    """Brutto-Netzpreis (Cent/kWh) eines Planungs-Slots; Fehler statt Default."""
    value = slot.get("k_act")
    if value is None:
        raise ValueError(
            "recommend_start_times: Planungs-Slot ohne 'k_act' "
            "(Brutto-Netzpreis in Cent/kWh)."
        )
    return float(value)


def run_cost_eur(
    slots: list, start_index: int, power_kw: float, weights: list[float]
) -> float:
    """Laufkosten (€) für einen Start bei start_index über die gegebenen Slot-Gewichte."""
    cost_cent = 0.0
    for offset, weight in enumerate(weights):
        cost_cent += power_kw * weight * _slot_price_cent(slots[start_index + offset])
    return cost_cent / 100.0


def _assign_stars(costs: list[float]) -> list[int]:
    """Lineare 1–5-Sterne-Skala: günstigste Kosten = 5, teuerste = 1."""
    cost_min = min(costs)
    span = max(costs) - cost_min
    if span < _EPS:
        return [STAR_NEUTRAL] * len(costs)
    stars = []
    for cost in costs:
        ratio = (cost - cost_min) / span
        raw = STAR_MAX - (STAR_MAX - STAR_MIN) * ratio
        stars.append(int(min(STAR_MAX, max(STAR_MIN, round(raw)))))
    return stars


def recommend_start_times(
    slots: list,
    power_kw: float,
    runtime_h: float,
    horizon_h: int = DEFAULT_HORIZON_H,
) -> ApplianceRecommendation:
    """Rankt die möglichen Startstunden im Horizont nach Netzbezugskosten.

    ``slots`` ist eine chronologische Liste stündlicher Planungs-Slots
    (dicts mit ``slot_datetime`` und ``k_act`` in Cent/kWh), z. B. aus
    ``data.profile_manager.build_live_planning_matrix``.
    """
    _validate_inputs(slots, power_kw, runtime_h, horizon_h)
    weights = _slot_run_weights(runtime_h)
    run_slots = len(weights)
    max_start = min(horizon_h, len(slots))
    valid_starts = [s for s in range(max_start) if s + run_slots <= len(slots)]
    if not valid_starts:
        raise ValueError(
            f"recommend_start_times: nur {len(slots)} Planungs-Slots für eine "
            f"Laufzeit von {runtime_h} h ({run_slots} Slots) — keine Empfehlung möglich."
        )

    costs = [run_cost_eur(slots, s, power_kw, weights) for s in valid_starts]
    stars = _assign_stars(costs)
    immediate_cost = costs[0]
    options = [
        StartOption(
            start_datetime=slots[start]["slot_datetime"],
            cost_eur=cost,
            stars=star,
            savings_vs_now_eur=immediate_cost - cost,
        )
        for start, cost, star in zip(valid_starts, costs, stars)
    ]
    cheapest = min(options, key=lambda option: option.cost_eur)
    return ApplianceRecommendation(
        options=options,
        cheapest=cheapest,
        immediate=options[0],
        skipped_start_slots=max_start - len(valid_starts),
    )
