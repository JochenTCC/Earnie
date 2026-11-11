"""Report of the slots whose plan cannot hold the import cap (max-power tariff P6a, L4).

Built after the solve from the slack of ``milp_import_cap`` (decision D6): a slot with slack names
the overshoot and a cause read from the solved model, so the report never disagrees with the plan.

Causes, checked in this order; the first that applies is the main cause, all that apply are kept:

1. ``base_load``: load minus PV, without the flexible consumers the plan runs, stays above the
   limit even with every battery discharging at its maximum power.
2. ``battery_power``: the batteries discharge at their maximum power, or an inverter's AC limit
   binds.
3. ``battery_energy``: the batteries charge in the slot (reserve refill) or reach their floor
   (``min_soc`` plus virtual reserve) before they charge again.
4. ``consumer_target``: a flexible consumer that still has energy to deliver runs in the slot.
5. ``none_detected``: none of the above; said as such, never filled in with a guess.

Live adds two causes outside the plan: ``forecast`` (the plan held, the measured quarter hour did
not) and ``not_planned`` (trivial window or Automatik, no plan held the cap).

Every report names its ``mode`` (plan P6d, decision O1). In ``observe`` mode Live executes a plan
without the cap and the report comes from a second, never executed plan with it (decision O2); its
``observe`` block compares slot 0 of both plans and the extra energy cost of holding the cap.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from house_config.import_cap import IMPORT_CAP_MODES, MODE_OBSERVE, MODE_OPTIMIZE

from .import_power_limit import ImportCaps
from .milp_horizon_types import MilpHorizonModel

REPORT_SCHEMA = 2  # 2: ``mode`` and, in observe mode, ``observe`` (P6d)

CAUSE_BASE_LOAD = "base_load"
CAUSE_BATTERY_POWER = "battery_power"
CAUSE_BATTERY_ENERGY = "battery_energy"
CAUSE_CONSUMER_TARGET = "consumer_target"
CAUSE_NONE = "none_detected"
CAUSE_FORECAST = "forecast"
CAUSE_NOT_PLANNED = "not_planned"

PLAN_CAUSE_ORDER = (
    CAUSE_BASE_LOAD,
    CAUSE_BATTERY_POWER,
    CAUSE_BATTERY_ENERGY,
    CAUSE_CONSUMER_TARGET,
)

CAUSE_LABELS_DE = {
    CAUSE_BASE_LOAD: "Grundlast über der Grenze, auch mit voller Batterieleistung",
    CAUSE_BATTERY_POWER: "Batterie oder Wechselrichter an der Leistungsgrenze",
    CAUSE_BATTERY_ENERGY: "Batterie leer oder Reserve",
    CAUSE_CONSUMER_TARGET: "Verbraucher muss sein Ziel erreichen",
    CAUSE_NONE: "Keine Ursache erkannt",
    CAUSE_FORECAST: "Lastprognose: Plan hielt, Messung lag darüber",
    CAUSE_NOT_PLANNED: "Grenze nicht eingeplant",
}

NOT_PLANNED_TRIVIAL = "trivial_window"
NOT_PLANNED_AUTOMATIK = "automatik"
NOT_PLANNED_SHADOW = "shadow_failed"  # observe mode: the plan with the cap did not solve
NOT_PLANNED_REASONS = (NOT_PLANNED_TRIVIAL, NOT_PLANNED_AUTOMATIK, NOT_PLANNED_SHADOW)

SLACK_TOLERANCE_KW = 0.01
_POWER_TOLERANCE_KW = 0.01
_ENERGY_TOLERANCE_KWH = 0.01
_INVERTER_DISCHARGE_PREFIXES = ("inv_ac_dis_", "inv_ac_clip_")


def _value(var: Any) -> float:
    value = getattr(var, "varValue", None)
    return 0.0 if value is None else float(value)


def _slot_iso(matrix: Sequence[Mapping[str, Any]], t: int) -> str:
    """Quarter-hour start of slot ``t`` in the house's local time, as the caps were built."""
    slot = matrix[t]["slot_datetime"]
    slot = slot.replace(tzinfo=None) if slot.tzinfo else slot
    return slot.isoformat(timespec="minutes")


def _ess_lists(model: MilpHorizonModel) -> tuple[list[list], list[list]]:
    """Per battery: discharge variables and energy variables (aggregate when there is one ESS)."""
    if model.ess_ids and model.p_discharge_by_ess and model.e_batt_by_ess:
        return (
            [model.p_discharge_by_ess[eid] for eid in model.ess_ids],
            [model.e_batt_by_ess[eid] for eid in model.ess_ids],
        )
    return [model.p_discharge], [model.e_batt]


def _max_discharge_kw(discharge: list[list], t: int) -> float:
    return sum(float(getattr(series[t], "upBound", None) or 0.0) for series in discharge)


def _binding_inverter_slots(model: MilpHorizonModel) -> set[int]:
    """Slots in which an inverter's AC discharge limit binds."""
    slots: set[int] = set()
    for constraint in model.prob.constraints():
        name = str(constraint.name or "")
        if not name.startswith(_INVERTER_DISCHARGE_PREFIXES):
            continue
        value = constraint.value()
        if value is None or value < -_POWER_TOLERANCE_KW:
            continue
        _, _, index = name.rpartition("_")
        if index.isdigit():
            slots.add(int(index))
    return slots


def _energy_above_floor_kwh(energy: list[list], k: int) -> float:
    return sum(
        _value(series[k]) - float(getattr(series[k], "lowBound", None) or 0.0) for series in energy
    )


def _battery_energy_limited(model: MilpHorizonModel, energy: list[list], t: int) -> bool:
    """Charging now (reserve refill), or empty before the next charge."""
    if _value(model.p_charge[t]) > _POWER_TOLERANCE_KW:
        return True
    for k in range(t, model.horizon):
        if k > t and _value(model.p_charge[k]) > _POWER_TOLERANCE_KW:
            return False
        if _energy_above_floor_kwh(energy, k) <= _ENERGY_TOLERANCE_KWH:
            return True
    return False


def _running_target_consumers(
    model: MilpHorizonModel, t: int, consumer_remaining_kwh: Mapping[str, float]
) -> dict[str, float]:
    from .milp_consumer_vars import _consumer_powers_at

    powers, _total = _consumer_powers_at(model, t)
    return {
        cid: power
        for cid, power in powers.items()
        if power > _POWER_TOLERANCE_KW and float(consumer_remaining_kwh.get(cid, 0.0)) > 0.0
    }


def _slot_causes(
    model: MilpHorizonModel,
    t: int,
    limit_kw: float,
    discharge: list[list],
    energy: list[list],
    inverter_slots: set[int],
    consumer_remaining_kwh: Mapping[str, float],
) -> tuple[list[str], dict[str, float]]:
    from .milp_consumer_vars import _consumer_powers_at

    flex_kw = _consumer_powers_at(model, t)[1]
    discharge_kw = _value(model.p_discharge[t])
    max_discharge = _max_discharge_kw(discharge, t)
    # The balance gives load − PV of the slot without solving PV again: buy + discharge − sell
    # − charge − curtail = load − PV + flex.
    base_net_kw = (
        _value(model.p_grid_buy[t])
        + discharge_kw
        - _value(model.p_grid_sell[t])
        - _value(model.p_charge[t])
        - (_value(model.p_pv_curtail[t]) if model.p_pv_curtail else 0.0)
        - flex_kw
    )
    consumers = _running_target_consumers(model, t, consumer_remaining_kwh)
    # A house without battery power has no battery cause: nothing could have discharged.
    has_battery = max_discharge > _POWER_TOLERANCE_KW
    found = {
        CAUSE_BASE_LOAD: base_net_kw - max_discharge > limit_kw + SLACK_TOLERANCE_KW,
        CAUSE_BATTERY_POWER: has_battery
        and (discharge_kw >= max_discharge - _POWER_TOLERANCE_KW or t in inverter_slots),
        CAUSE_BATTERY_ENERGY: has_battery and _battery_energy_limited(model, energy, t),
        CAUSE_CONSUMER_TARGET: bool(consumers),
    }
    causes = [cause for cause in PLAN_CAUSE_ORDER if found[cause]]
    return causes or [CAUSE_NONE], consumers


def _over_slots(
    model: MilpHorizonModel,
    matrix: Sequence[Mapping[str, Any]],
    caps: ImportCaps,
    consumer_remaining_kwh: Mapping[str, float] | None,
) -> list[tuple[int, dict[str, Any]]]:
    """Slot index and report entry of every slot whose plan goes over its limit."""
    slack = model.import_cap_slack
    if slack is None:
        raise ValueError("Bezugsgrenzen-Bericht: das Modell hat keine Bezugsgrenze.")
    discharge, energy = _ess_lists(model)
    inverter_slots = _binding_inverter_slots(model)
    remaining = consumer_remaining_kwh or {}
    slots: list[tuple[int, dict[str, Any]]] = []
    for t in range(model.horizon):
        if slack[t] is None:
            continue
        over_kw = _value(slack[t])
        if over_kw <= SLACK_TOLERANCE_KW:
            continue
        limit_kw = float(caps.limits_kw[t])
        causes, consumers = _slot_causes(
            model, t, limit_kw, discharge, energy, inverter_slots, remaining
        )
        slots.append(
            (t, {
                "slot": _slot_iso(matrix, t),
                "month": caps.months[t],
                "import_kw": round(_value(model.p_grid_buy[t]), 3),
                "limit_kw": round(limit_kw, 3),
                "over_kw": round(over_kw, 3),
                "cause": causes[0],
                "causes": causes,
                "consumers_kw": {cid: round(kw, 3) for cid, kw in consumers.items()},
            })
        )
    return slots


def report_from_model(
    model: MilpHorizonModel,
    matrix: Sequence[Mapping[str, Any]],
    caps: ImportCaps,
    consumer_remaining_kwh: Mapping[str, float] | None,
    *,
    mode: str = MODE_OPTIMIZE,
) -> dict[str, Any]:
    """The report of a solved model that was planned under ``caps``.

    ``mode`` ``observe``: ``model`` is the shadow plan; ``observe_report`` adds the comparison.
    """
    slots = [entry for _t, entry in _over_slots(model, matrix, caps, consumer_remaining_kwh)]
    return _report(planned=True, reason=None, caps=caps, matrix=matrix, slots=slots, mode=mode)


# --- observe mode (P6d) --------------------------------------------------------------------


def _slot0_of(model: MilpHorizonModel) -> dict[str, Any]:
    """What a plan does in slot 0: grid import, battery (discharge − charge) and consumers."""
    from .milp_consumer_vars import _consumer_powers_at

    powers, _total = _consumer_powers_at(model, 0)
    return {
        "import_kw": round(_value(model.p_grid_buy[0]), 3),
        "battery_kw": round(_value(model.p_discharge[0]) - _value(model.p_charge[0]), 3),
        "consumers_kw": {cid: round(kw, 3) for cid, kw in powers.items()},
    }


def plan_energy_cost_cent(
    model: MilpHorizonModel, matrix: Sequence[Mapping[str, Any]], fallback_k_push: float
) -> float:
    """Grid cash flow of a solved plan over its horizon, as the objective prices it, in cent.

    Without wear, curtail, credits and the cap penalty, so two plans of one matrix compare on
    energy alone.
    """
    from data.feed_in_prices import k_push_act_for_matrix_row

    return sum(
        (
            _value(model.p_grid_buy[t]) * float(matrix[t]["k_act"])
            - _value(model.p_grid_sell[t])
            * k_push_act_for_matrix_row(dict(matrix[t]), fallback_k_push)
        )
        * float(model.dt_h)
        for t in range(model.horizon)
    )


def _observe_block(
    matrix: Sequence[Mapping[str, Any]],
    *,
    delta_import_kw: float | None,
    executed: dict[str, Any] | None,
    shadow: dict[str, Any] | None,
    energy_cost_extra_eur: float | None,
) -> dict[str, Any]:
    return {
        "slot": _slot_iso(matrix, 0),
        "delta_import_kw": None if delta_import_kw is None else round(float(delta_import_kw), 3),
        "executed": executed,
        "shadow": shadow,
        "energy_cost_extra_eur": energy_cost_extra_eur,
    }


def observe_report(
    shadow_model: MilpHorizonModel,
    executed_model: MilpHorizonModel,
    matrix: Sequence[Mapping[str, Any]],
    caps: ImportCaps,
    consumer_remaining_kwh: Mapping[str, float] | None,
    fallback_k_push: float,
) -> dict[str, Any]:
    """Observe mode: the shadow plan's report plus slot 0 of both plans.

    ``delta_import_kw`` = slot-0 import of the shadow plan − that of the executed plan; Live adds
    it to the measured quarter hour for the hypothetical month peak (decision O3). The extra energy
    cost is over the whole horizon, never slot 0 alone: a plan that discharges more now pays for
    it with a recharge later (decision O4).
    """
    report = report_from_model(
        shadow_model, matrix, caps, consumer_remaining_kwh, mode=MODE_OBSERVE
    )
    executed = _slot0_of(executed_model)
    shadow = _slot0_of(shadow_model)
    extra_cent = plan_energy_cost_cent(shadow_model, matrix, fallback_k_push) - plan_energy_cost_cent(
        executed_model, matrix, fallback_k_push
    )
    report["observe"] = _observe_block(
        matrix,
        delta_import_kw=shadow["import_kw"] - executed["import_kw"],
        executed=executed,
        shadow=shadow,
        energy_cost_extra_eur=round(extra_cent / 100.0, 4),
    )
    return report


# --- marks per plan slot, for the Scenario Explorer log (P6c) ------------------------------

SLOT_LIMIT_KEY = "import_cap_limit"
SLOT_CAUSE_KEY = "import_cap_cause"


def _mark(limit_kw: float, cause: str | None) -> dict[str, Any]:
    return {SLOT_LIMIT_KEY: float(limit_kw), SLOT_CAUSE_KEY: cause}


def plan_slot_marks(
    model: MilpHorizonModel,
    matrix: Sequence[Mapping[str, Any]],
    caps: ImportCaps,
    consumer_remaining_kwh: Mapping[str, float] | None,
) -> list[dict[str, Any] | None]:
    """Per slot: the limit and, if the plan goes over it, the main cause; ``None`` without a limit."""
    causes = {t: entry["cause"] for t, entry in _over_slots(model, matrix, caps, consumer_remaining_kwh)}
    return [
        None if limit is None else _mark(limit, causes.get(t))
        for t, limit in enumerate(caps.limits_kw[: model.horizon])
    ]


def not_planned_slot_marks(caps: ImportCaps, slots: int) -> list[dict[str, Any] | None]:
    """Trivial window or Automatik: every slot with a limit is marked as not planned."""
    return [
        None if limit is None else _mark(limit, CAUSE_NOT_PLANNED)
        for limit in caps.limits_kw[:slots]
    ]


def first_slot_mark(plan: Mapping[str, Any], caps: ImportCaps) -> dict[str, Any] | None:
    """Mark of slot 0 from ``milp_optimizer``'s plan; used when the SE solves slot by slot."""
    limit = caps.limits_kw[0] if caps.limits_kw else None
    if limit is None:
        return None
    report = plan.get("import_cap_report")
    if not isinstance(report, Mapping):
        raise ValueError("Bezugsgrenzen-Bericht fehlt im Plan, obwohl eine Grenze gilt.")
    if not report["planned"]:
        return _mark(limit, CAUSE_NOT_PLANNED)
    # Slot 0 comes first, so its entry, if any, is the first one; the slack says whether it has one.
    over = float(plan.get("import_cap_slack_kw") or 0.0) > SLACK_TOLERANCE_KW
    if over and not report["slots"]:
        raise ValueError("Bezugsgrenzen-Bericht: Slot 0 über der Grenze, aber kein Eintrag.")
    return _mark(limit, report["slots"][0]["cause"] if over else None)


def not_planned_report(
    caps: ImportCaps,
    matrix: Sequence[Mapping[str, Any]],
    reason: str,
    *,
    mode: str = MODE_OPTIMIZE,
) -> dict[str, Any]:
    """Trivial window, Automatik or (observe mode) a failed shadow solve: no plan holds the cap.

    In observe mode the ``observe`` block says what is known of slot 0: the trivial window has
    nothing to steer, so a plan with the cap would import the same (delta 0); after Automatik or a
    failed shadow solve the delta is unknown (``None``) and the quarter hour counts as missing.
    """
    if reason not in NOT_PLANNED_REASONS:
        raise ValueError(f"Bezugsgrenzen-Bericht: unbekannter Grund {reason!r}.")
    if reason == NOT_PLANNED_SHADOW and mode != MODE_OBSERVE:
        raise ValueError("Bezugsgrenzen-Bericht: shadow_failed gibt es nur im Beobachtungsmodus.")
    report = _report(planned=False, reason=reason, caps=caps, matrix=matrix, slots=[], mode=mode)
    if mode == MODE_OBSERVE:
        trivial = reason == NOT_PLANNED_TRIVIAL
        report["observe"] = _observe_block(
            matrix,
            delta_import_kw=0.0 if trivial else None,
            executed=None,
            shadow=None,
            energy_cost_extra_eur=0.0 if trivial else None,
        )
    return report


def _report(
    *,
    planned: bool,
    reason: str | None,
    caps: ImportCaps,
    matrix: Sequence[Mapping[str, Any]],
    slots: list[dict[str, Any]],
    mode: str,
) -> dict[str, Any]:
    if mode not in IMPORT_CAP_MODES:
        raise ValueError(f"Bezugsgrenzen-Bericht: unbekannter Modus {mode!r}.")
    indices = [t for t, limit in enumerate(caps.limits_kw) if limit is not None and t < len(matrix)]
    months: dict[str, dict[str, Any]] = {}
    for entry in slots:
        month = months.setdefault(entry["month"], {"slots_over": 0, "max_over_kw": 0.0})
        month["slots_over"] += 1
        month["max_over_kw"] = max(month["max_over_kw"], entry["over_kw"])
    return {
        "schema": REPORT_SCHEMA,
        "mode": mode,
        "planned": planned,
        "reason": reason,
        "first_slot": _slot_iso(matrix, indices[0]) if indices else None,
        "limits_kw": {
            month: round(min(caps.limits_kw[t] for t in indices if caps.months[t] == month), 3)
            for month in sorted({caps.months[t] for t in indices})
        },
        "slots": slots,
        "months": months,
    }
