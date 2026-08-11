"""Empfehlungsmodus für manuelle Geräte: günstigste Startzeit im Kurzhorizont.

Reine Kosten-/Startzeit-Logik ohne Streamlit-Abhängigkeit (Schritt 3a).
Bewusst getroffene Modell-Entscheidungen:

- Startgüte = Opportunitätskosten (€) je möglicher Startstunde: PV-Überschuss
  bewertet mit Einspeisetarif ``k_push_act``, Rest mit Bezugspreis ``k_act``
  (MILP-aligned; ersetzt die reine Netzbezug-Regel von 2026-07).
- Sterne (1–5) nach kombinierter Regel: zuerst absolute Marge der fiktiven
  ct/kWh-Serie, danach prozentuale Mehrkosten gegenüber der günstigsten
  Startstunde.
- Ein Lauf darf über das Horizontende hinausreichen, solange genügend
  Planungs-Slots vorliegen; sonst entfallen die betroffenen Startstunden.

Die Planungs-Slots sind stündlich (siehe ``data.profile_manager``); ein Slot
entspricht daher einer Stunde.
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

DEFAULT_ABS_MARGIN_CENT = 0.05
DEFAULT_PCT_STARS_4 = 10.0
DEFAULT_PCT_STARS_1 = 30.0


@dataclass(frozen=True)
class StarThresholdSettings:
    """Schwellen für die Sterne-Vergabe (konfigurierbar in config.json)."""

    abs_margin_cent: float
    pct_stars_4: float
    pct_stars_1: float


DEFAULT_STAR_THRESHOLDS = StarThresholdSettings(
    abs_margin_cent=DEFAULT_ABS_MARGIN_CENT,
    pct_stars_4=DEFAULT_PCT_STARS_4,
    pct_stars_1=DEFAULT_PCT_STARS_1,
)


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


def _validate_star_settings(settings: StarThresholdSettings) -> None:
    if settings.abs_margin_cent < 0:
        raise ValueError("abs_margin_cent muss >= 0 sein.")
    if settings.pct_stars_4 <= 0:
        raise ValueError("pct_stars_4 muss > 0 sein.")
    if settings.pct_stars_1 <= settings.pct_stars_4:
        raise ValueError("pct_stars_1 muss größer als pct_stars_4 sein.")


def _slot_run_weights(runtime_h: float) -> list[float]:
    """Anteil (in Stunden) je Stundenslot, den ein Lauf von runtime_h belegt."""
    full_hours = int(math.floor(runtime_h + _EPS))
    remainder = runtime_h - full_hours
    weights = [1.0] * full_hours
    if remainder > _EPS:
        weights.append(remainder)
    return weights


def _require_slot_float(slot: dict, key: str) -> float:
    """Liest ein Pflicht-Float-Feld aus dem Planungs-Slot; Fehler statt Default."""
    if key not in slot or slot[key] is None:
        raise ValueError(
            f"recommend_start_times: Planungs-Slot ohne '{key}'."
        )
    return float(slot[key])


def _slot_opportunity_cost_cent(slot: dict, power_kw: float) -> float:
    """Opportunitätskosten (Cent) für 1 h Betrieb mit ``power_kw`` in diesem Slot.

    PV-Überschuss (``expected_p_pv − expected_p_act``) wird mit ``k_push_act``
    bewertet, der Rest mit ``k_act``.
    """
    k_act = _require_slot_float(slot, "k_act")
    k_push = _require_slot_float(slot, "k_push_act")
    p_pv = _require_slot_float(slot, "expected_p_pv")
    p_act = _require_slot_float(slot, "expected_p_act")
    surplus_kw = max(0.0, p_pv - p_act)
    pv_share = min(power_kw, surplus_kw)
    grid_share = power_kw - pv_share
    return pv_share * k_push + grid_share * k_act


def _slot_effective_price_cent(slot: dict, power_kw: float) -> float:
    """Fiktiver Durchschnittspreis (Cent/kWh) für ``power_kw`` in diesem Slot."""
    return _slot_opportunity_cost_cent(slot, power_kw) / power_kw


def run_cost_eur(
    slots: list, start_index: int, power_kw: float, weights: list[float]
) -> float:
    """Laufkosten (€) für einen Start bei start_index über die gegebenen Slot-Gewichte."""
    cost_cent = 0.0
    for offset, weight in enumerate(weights):
        cost_cent += weight * _slot_opportunity_cost_cent(
            slots[start_index + offset], power_kw
        )
    return cost_cent / 100.0


def _max_effective_price_for_run(
    slots: list, start_index: int, weights: list[float], power_kw: float
) -> float:
    values = [
        _slot_effective_price_cent(slots[start_index + offset], power_kw)
        for offset in range(len(weights))
    ]
    return max(values)


def _stars_from_pct(pct: float, settings: StarThresholdSettings) -> float:
    if pct <= settings.pct_stars_4:
        return STAR_MAX - (STAR_MAX - 4) * (pct / settings.pct_stars_4)
    if pct >= settings.pct_stars_1:
        return float(STAR_MIN)
    span = settings.pct_stars_1 - settings.pct_stars_4
    ratio = (pct - settings.pct_stars_4) / span
    return 4.0 - (4.0 - STAR_MIN) * ratio


def _assign_stars(
    slots: list,
    valid_starts: list[int],
    weights: list[float],
    costs: list[float],
    settings: StarThresholdSettings,
    horizon_h: int,
    power_kw: float,
) -> list[int]:
    """Kombinierte Sterne-Regel: fiktive ct/kWh-Marge, danach %-Mehrkosten."""
    _validate_star_settings(settings)
    if not costs:
        return []
    min_cost = min(costs)
    if max(costs) - min_cost < _EPS:
        return [STAR_NEUTRAL] * len(costs)

    horizon_slots = min(horizon_h, len(slots))
    min_price = min(
        _slot_effective_price_cent(slots[i], power_kw) for i in range(horizon_slots)
    )
    stars: list[int] = []
    for start, cost in zip(valid_starts, costs):
        max_price = _max_effective_price_for_run(slots, start, weights, power_kw)
        if max_price <= min_price + settings.abs_margin_cent:
            stars.append(STAR_MAX)
            continue
        if min_cost < _EPS:
            stars.append(STAR_MIN)
            continue
        pct = (cost - min_cost) / min_cost * 100.0
        raw = _stars_from_pct(pct, settings)
        stars.append(int(min(STAR_MAX, max(STAR_MIN, round(raw)))))
    return stars


def recommend_start_times(
    slots: list,
    power_kw: float,
    runtime_h: float,
    horizon_h: int = DEFAULT_HORIZON_H,
    star_settings: StarThresholdSettings | None = None,
) -> ApplianceRecommendation:
    """Rankt die möglichen Startstunden im Horizont nach Opportunitätskosten.

    ``slots`` ist eine chronologische Liste stündlicher Planungs-Slots
    (dicts mit ``slot_datetime``, ``k_act``, ``k_push_act``, ``expected_p_pv``,
    ``expected_p_act``), z. B. aus ``data.profile_manager``.
    """
    _validate_inputs(slots, power_kw, runtime_h, horizon_h)
    thresholds = star_settings or DEFAULT_STAR_THRESHOLDS
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
    stars = _assign_stars(
        slots, valid_starts, weights, costs, thresholds, horizon_h, power_kw
    )
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
