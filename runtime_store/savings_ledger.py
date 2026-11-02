"""Savings ledger: shadow plant slot engine (spec ``docs/dev/savings-ledger.md`` § 3).

Pure functions, no file I/O and no config reads. One closed quarter-hour slot of
the production log is compared with a shadow plant that has the same house load,
PV and prices, and a battery in vendor mode (``optimizer.battery.vendor_mode_step``,
the same step as the "Baseline" simulation) on its own continuous SoC chain.

Sign conventions: ``closed_interval`` stores ``battery_kw`` positive while
discharging (``house = pv + grid + battery``) and ``grid_kw`` positive while
importing. The vendor-mode step returns battery power positive while charging.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from optimizer import battery as bat
from optimizer.milp_horizon import (
    aggregate_battery_params_for_load,
    coerce_battery_params_list,
)
from optimizer.slot_duration import DEFAULT_DT_H, validate_dt_h
from runtime_store.power_interval_sampler import MIN_SAMPLE_COUNT_FOR_MEAN

SAVINGS_V = 1

# Plant channels that must be slot means for a slot to count (spec § 4).
_REQUIRED_MEAN_CHANNELS = ("pv", "grid", "battery", "house")
_REQUIRED_POWER_KEYS = ("pv_kw", "grid_kw", "house_kw")

SKIP_MISSING = "missing"
SKIP_FEW_SAMPLES = "few_samples"
SKIP_NOT_MEAN = "not_mean"
SKIP_NO_POWER = "no_power"


@dataclass(frozen=True)
class LedgerSlot:
    """Result of one closed slot. A skipped slot leaves both sides and the shadow SoC unchanged."""

    counted: bool
    skip_reason: str | None
    cost_with_eur: float
    cost_without_eur: float
    shadow_soc_next: float
    import_kwh_with: float
    import_kwh_without: float
    export_kwh_with: float
    export_kwh_without: float
    shadow_battery_kw: float

    @property
    def saving_eur(self) -> float:
        return self.cost_without_eur - self.cost_with_eur


def slot_skip_reason(closed: dict[str, Any] | None) -> str | None:
    """Why a ``closed_interval`` does not count, or ``None`` when it does.

    A slot counts when it is present, has at least ``MIN_SAMPLE_COUNT_FOR_MEAN``
    samples (same bar as "Ist bisher"), all four plant channels are slot means
    (not energy counters, which would break the ``house = pv + grid + battery``
    balance) and pv, grid and house powers are present.
    """
    if not isinstance(closed, dict) or not closed:
        return SKIP_MISSING
    try:
        samples = int(closed.get("sample_count") or 0)
    except (TypeError, ValueError):
        return SKIP_FEW_SAMPLES
    if samples < MIN_SAMPLE_COUNT_FOR_MEAN:
        return SKIP_FEW_SAMPLES
    sources = closed.get("ist_power_source")
    if not isinstance(sources, dict):
        return SKIP_NOT_MEAN
    if any(sources.get(channel) != "mean" for channel in _REQUIRED_MEAN_CHANNELS):
        return SKIP_NOT_MEAN
    for key in _REQUIRED_POWER_KEYS:
        value = closed.get(key)
        if value is None or isinstance(value, bool):
            return SKIP_NO_POWER
        try:
            float(value)
        except (TypeError, ValueError):
            return SKIP_NO_POWER
    return None


def shadow_battery_params(battery_params: dict | list[dict] | None) -> dict:
    """Battery the shadow plant runs: one ESS as is, several aggregated like the baseline."""
    batteries = coerce_battery_params_list(battery_params)
    if not batteries:
        raise ValueError("savings ledger: no house battery parameters for the shadow plant")
    if len(batteries) == 1:
        return batteries[0]
    return aggregate_battery_params_for_load(batteries)


def _cost_eur(grid_kwh: float, k_act_cent: float, k_push_cent: float) -> float:
    if grid_kwh >= 0.0:
        return grid_kwh * k_act_cent / 100.0
    return grid_kwh * k_push_cent / 100.0


def advance_slot(
    closed: dict[str, Any] | None,
    shadow_soc: float,
    battery_params: dict,
    *,
    k_act_cent: float,
    k_push_cent: float,
    dt_h: float = DEFAULT_DT_H,
) -> LedgerSlot:
    """Price one closed slot with and without Earnie and step the shadow battery.

    ``battery_params`` is the shadow battery (``shadow_battery_params``).
    ``k_act_cent`` / ``k_push_cent`` are the buy and sell prices of that slot's
    cycle. A slot that does not count (``slot_skip_reason``) is skipped on both
    sides: zero cost, shadow SoC unchanged, ``skip_reason`` set.
    """
    dt = validate_dt_h(dt_h)
    reason = slot_skip_reason(closed)
    if reason is not None:
        return LedgerSlot(
            counted=False,
            skip_reason=reason,
            cost_with_eur=0.0,
            cost_without_eur=0.0,
            shadow_soc_next=float(shadow_soc),
            import_kwh_with=0.0,
            import_kwh_without=0.0,
            export_kwh_with=0.0,
            export_kwh_without=0.0,
            shadow_battery_kw=0.0,
        )
    assert closed is not None
    pv_kw = float(closed["pv_kw"])
    house_kw = float(closed["house_kw"])
    grid_kw = float(closed["grid_kw"])
    load_kw = house_kw + bat.standby_power_kw(battery_params)
    soc_next, batt_kw = bat.vendor_mode_step(
        float(shadow_soc), pv_kw - load_kw, battery_params, dt_h=dt
    )
    grid_shadow_kw = load_kw - pv_kw + batt_kw
    grid_kwh = grid_kw * dt
    grid_shadow_kwh = grid_shadow_kw * dt
    k_act = float(k_act_cent)
    k_push = float(k_push_cent)
    return LedgerSlot(
        counted=True,
        skip_reason=None,
        cost_with_eur=_cost_eur(grid_kwh, k_act, k_push),
        cost_without_eur=_cost_eur(grid_shadow_kwh, k_act, k_push),
        shadow_soc_next=soc_next,
        import_kwh_with=max(grid_kwh, 0.0),
        import_kwh_without=max(grid_shadow_kwh, 0.0),
        export_kwh_with=max(-grid_kwh, 0.0),
        export_kwh_without=max(-grid_shadow_kwh, 0.0),
        shadow_battery_kw=batt_kw,
    )
