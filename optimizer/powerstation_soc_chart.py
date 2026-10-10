"""Chart1 SoC helpers for house ESS + physical/virtual powerstations."""
from __future__ import annotations

from typing import Any

from house_config.powerstation import (
    BACKING_VIRTUAL,
    is_virtual_powerstation,
)
from optimizer.powerstation_reserve import asap_charge_kwh_from_state
from runtime_store.powerstation_reserves import (
    STATE_CHARGING,
    STATE_DISCHARGING,
    STATE_EMPTY,
    STATE_STANDBY,
)

VIRTUAL_SOC_LINE_WIDTH = 1.0
HOUSE_SOC_LINE_WIDTH = 2.5


def virtual_soc_percent(stored_kwh: float, capacity_kwh: float) -> float:
    """Reserve fill as SoC % of the virtual carve-out capacity (0–100)."""
    cap = float(capacity_kwh or 0.0)
    if cap <= 1e-9:
        return 0.0
    return max(0.0, min(100.0, (float(stored_kwh) / cap) * 100.0))


def _entity_from_battery(bat: dict, *, virtual: bool) -> dict[str, Any] | None:
    ess_id = str(bat.get("id") or "").strip()
    if not ess_id:
        return None
    label = str(bat.get("label") or ess_id).strip() or ess_id
    capacity = float(
        bat.get("battery_capacity_kwh")
        or bat.get("capacity_kwh")
        or 0.0
    )
    return {
        "id": ess_id,
        "label": label,
        "battery_capacity_kwh": capacity,
        "virtual": bool(virtual),
    }


def chart_soc_entities(
    house_batteries: list[dict] | None,
    powerstations: list[dict] | None,
) -> list[dict[str, Any]]:
    """House ESS then powerstations (physical + virtual) for Chart1 SoC columns."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for bat in house_batteries or []:
        if not isinstance(bat, dict):
            continue
        entity = _entity_from_battery(bat, virtual=False)
        if entity is None or entity["id"] in seen:
            continue
        seen.add(entity["id"])
        out.append(entity)
    for ps in powerstations or []:
        if not isinstance(ps, dict):
            continue
        entity = _entity_from_battery(ps, virtual=is_virtual_powerstation(ps))
        if entity is None or entity["id"] in seen:
            continue
        seen.add(entity["id"])
        out.append(entity)
    return out


def load_chart_soc_entities() -> list[dict[str, Any]]:
    """Chart SoC entities from live resolved settings (house + all powerstations)."""
    import config
    from house_config.entity_resolution import battery_params_from_planning

    houses = list(config.get_battery_params_list() or [])
    resolved = config.get_resolved_runtime_settings() or {}
    raw_ps = resolved.get("_planning_powerstations") or []
    powerstations: list[dict] = []
    for entry in raw_ps:
        if not isinstance(entry, dict) or not str(entry.get("id") or "").strip():
            continue
        try:
            powerstations.append(battery_params_from_planning(entry))
        except (KeyError, TypeError, ValueError):
            powerstations.append(entry)
    return chart_soc_entities(houses, powerstations)


def virtual_soc_labels(entities: list[dict[str, Any]] | None) -> set[str]:
    """Bezeichnung set for virtual powerstation SoC series."""
    labels: set[str] = set()
    for entity in entities or []:
        if not entity.get("virtual"):
            continue
        label = str(entity.get("label") or entity.get("id") or "").strip()
        if label:
            labels.add(label)
    return labels


def virtual_soc_by_id_from_states(
    powerstations: list[dict] | None,
    reserve_states: dict[str, dict[str, Any]] | None,
) -> dict[str, float]:
    """SoC % per virtual powerstation id from reserve ``stored_kwh``."""
    states = reserve_states or {}
    out: dict[str, float] = {}
    for ps in powerstations or []:
        if not isinstance(ps, dict) or not is_virtual_powerstation(ps):
            continue
        ps_id = str(ps.get("id") or "").strip()
        if not ps_id:
            continue
        entry = states.get(ps_id) or {}
        stored = float(entry.get("stored_kwh") or 0.0)
        capacity = float(ps.get("battery_capacity_kwh") or 0.0)
        out[ps_id] = round(virtual_soc_percent(stored, capacity), 2)
    return out


def load_virtual_soc_by_id() -> dict[str, float]:
    """Live virtual PS SoC % from config powerstations + reserve store."""
    import config
    from house_config.entity_resolution import battery_params_from_planning
    from runtime_store.powerstation_reserves import load_reserve_states

    resolved = config.get_resolved_runtime_settings() or {}
    raw_ps = resolved.get("_planning_powerstations") or []
    powerstations: list[dict] = []
    for entry in raw_ps:
        if not isinstance(entry, dict):
            continue
        try:
            powerstations.append(battery_params_from_planning(entry))
        except (KeyError, TypeError, ValueError):
            powerstations.append(entry)
    return virtual_soc_by_id_from_states(powerstations, load_reserve_states())


def _apply_slot_to_entry(
    entry: dict[str, Any],
    *,
    charged_kwh: float = 0.0,
    discharged_kwh: float = 0.0,
) -> None:
    """In-memory mirror of ``advance_reserve_after_slot`` (no store I/O)."""
    target = max(0.0, float(entry.get("target_kwh") or 0.0))
    stored = max(0.0, float(entry.get("stored_kwh") or 0.0))
    state = str(entry.get("state") or STATE_EMPTY)

    if state == STATE_DISCHARGING or entry.get("trigger_active"):
        stored = max(0.0, stored - max(0.0, discharged_kwh))
        if stored <= 1e-6:
            entry["state"] = STATE_EMPTY
            entry["stored_kwh"] = 0.0
            entry["trigger_active"] = False
        else:
            entry["state"] = STATE_DISCHARGING
            entry["stored_kwh"] = stored
        entry["asap_charge_kwh"] = asap_charge_kwh_from_state(entry)
        return

    stored = min(target, stored + max(0.0, charged_kwh))
    entry["stored_kwh"] = stored
    if target <= 1e-9:
        entry["state"] = STATE_EMPTY
    elif stored + 1e-6 >= target:
        entry["state"] = STATE_STANDBY
    else:
        entry["state"] = STATE_CHARGING
    entry["asap_charge_kwh"] = asap_charge_kwh_from_state(entry)


def initial_virtual_sim_entries(
    *,
    powerstations: list[dict] | None,
    reserve_states: dict[str, dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Mutable virtual-reserve copies for horizon forward-sim (no store writes)."""
    states = reserve_states or {}
    entries: list[dict[str, Any]] = []
    for ps in powerstations or []:
        if not isinstance(ps, dict) or not is_virtual_powerstation(ps):
            continue
        ps_id = str(ps.get("id") or "").strip()
        if not ps_id:
            continue
        raw = states.get(ps_id) or {}
        entry = {
            "powerstation_id": ps_id,
            "backing": BACKING_VIRTUAL,
            "state": str(raw.get("state") or STATE_EMPTY),
            "stored_kwh": max(0.0, float(raw.get("stored_kwh") or 0.0)),
            "target_kwh": max(0.0, float(raw.get("target_kwh") or 0.0)),
            "trigger_active": bool(raw.get("trigger_active")),
            "capacity_kwh": float(ps.get("battery_capacity_kwh") or 0.0),
        }
        entry["asap_charge_kwh"] = asap_charge_kwh_from_state(entry)
        entries.append(entry)
    return entries


def simulate_virtual_reserve_soc_after_slot(
    *,
    battery_plan_kw: float,
    dt_h: float,
    virtual_entries: list[dict[str, Any]],
) -> dict[str, float]:
    """Advance in-memory virtual reserves one slot; return SoC % by id.

    Attribution mirrors ``advance_virtual_reserves_from_plan``.
    """
    if not virtual_entries:
        return {}
    charge_kwh = max(0.0, float(battery_plan_kw)) * float(dt_h)
    discharge_kwh = max(0.0, -float(battery_plan_kw)) * float(dt_h)

    needing = [
        r for r in virtual_entries if float(r.get("asap_charge_kwh") or 0.0) > 1e-9
    ]
    if needing and charge_kwh > 1e-9:
        share = charge_kwh / len(needing)
        for reserve in needing:
            _apply_slot_to_entry(reserve, charged_kwh=share)

    discharging = [
        r
        for r in virtual_entries
        if r.get("state") == STATE_DISCHARGING or r.get("trigger_active")
    ]
    if discharging and discharge_kwh > 1e-9:
        share = discharge_kwh / len(discharging)
        for reserve in discharging:
            _apply_slot_to_entry(reserve, discharged_kwh=share)
    elif discharging:
        for reserve in discharging:
            target = float(reserve.get("target_kwh") or 0.0)
            runtime_h = max(0.25, target / max(0.1, target or 0.1))
            step = target * min(1.0, float(dt_h) / max(runtime_h, float(dt_h)))
            _apply_slot_to_entry(reserve, discharged_kwh=step)

    return {
        str(r["powerstation_id"]): round(
            virtual_soc_percent(
                float(r.get("stored_kwh") or 0.0),
                float(r.get("capacity_kwh") or 0.0),
            ),
            1,
        )
        for r in virtual_entries
    }


def soc_percent_map_for_entities(
    entities: list[dict[str, Any]],
    virtual_entries: list[dict[str, Any]],
) -> dict[str, float]:
    """Current virtual SoC % from in-memory sim entries (pre-advance snapshot)."""
    by_id = {
        str(r["powerstation_id"]): round(
            virtual_soc_percent(
                float(r.get("stored_kwh") or 0.0),
                float(r.get("capacity_kwh") or 0.0),
            ),
            1,
        )
        for r in virtual_entries
    }
    out: dict[str, float] = {}
    for entity in entities:
        if not entity.get("virtual"):
            continue
        ess_id = str(entity.get("id") or "").strip()
        if ess_id in by_id:
            out[ess_id] = by_id[ess_id]
    return out
