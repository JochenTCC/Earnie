"""Resolve Live export-power ceilings (2.7.a / 2.7.l) from HK + inbound EHAL."""
from __future__ import annotations

from typing import Any

from optimizer.export_power_limit import (
    effective_export_cap_kw,
    inbound_limit_w_to_kw,
    physical_max_export_kw,
    physical_max_export_kw_from_inverters,
    plant_max_export_power_kw,
)


def load_house_doc() -> dict:
    from house_config.profiles_store import load_house_profiles_document
    from runtime_store.persist_paths import resolve_house_profiles_json_path

    return load_house_profiles_document(resolve_house_profiles_json_path())


def _force_dischargeable_discharge_kw(battery_params: dict) -> float:
    from house_config.battery_control import (
        BATTERY_CONTROL_FULL,
        control_from_battery_params,
    )
    from house_config.powerstation import is_powerstation

    # Powerstations never feed the house grid / export unconstrained sum (2.7.g/h).
    if is_powerstation(battery_params):
        return 0.0
    if control_from_battery_params(battery_params) != BATTERY_CONTROL_FULL:
        return 0.0
    return float(
        battery_params.get(
            "max_discharge_power_kw",
            battery_params.get("max_power_kw") or 0.0,
        )
        or 0.0
    )


def _planning_list(config: Any, attr: str) -> list[dict]:
    raw = getattr(config, attr, None)
    if raw is None and hasattr(config, "get"):
        try:
            raw = config.get(attr, None)
        except TypeError:
            raw = None
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _battery_params_list(config: Any) -> list[dict]:
    get_list = getattr(config, "get_battery_params_list", None)
    if callable(get_list):
        return [b for b in (get_list() or []) if isinstance(b, dict)]
    return [config.get_battery_params()]


def live_unconstrained_export_kw() -> float | None:
    """Plant export maximum written as "unconstrained" on the export-limit setpoint.

    With ``_planning_inverters`` (2.7.l): Σ over grid-tied inverters of
    ``min(max_ac_power_kw, PV kWp capped by max_pv_input_kw + force-discharge)``.
    Island inverters contribute nothing.

    Legacy fallback (no planning inverters): PV nameplate sum + max discharge of
    every force-dischargeable battery (``control = full``; skip powerstations).
    """
    import config

    inverters = _planning_list(config, "_planning_inverters")
    if inverters:
        pv_by_inv: dict[str, float] = {}
        for pv in _planning_list(config, "_planning_pv_systems"):
            inv_id = str(pv.get("inverter_id") or "").strip()
            if not inv_id:
                continue
            pv_by_inv[inv_id] = pv_by_inv.get(inv_id, 0.0) + float(
                pv.get("pv_kwp") or 0.0
            )
        discharge_by_inv: dict[str, float] = {}
        for bat in _battery_params_list(config):
            inv_id = str(bat.get("inverter_id") or "").strip()
            if not inv_id:
                continue
            discharge_by_inv[inv_id] = discharge_by_inv.get(inv_id, 0.0) + (
                _force_dischargeable_discharge_kw(bat)
            )
        return physical_max_export_kw_from_inverters(
            inverters=inverters,
            pv_kwp_by_inverter=pv_by_inv,
            force_discharge_kw_by_inverter=discharge_by_inv,
        )

    discharge_kw = 0.0
    for bat in _battery_params_list(config):
        discharge_kw += _force_dischargeable_discharge_kw(bat)
    return physical_max_export_kw(config.get("PV_KWP", 0.0, float), discharge_kw)


def read_inbound_export_limit_kw(telemetry: dict[str, Any] | None) -> float | None:
    if not isinstance(telemetry, dict):
        return None
    return inbound_limit_w_to_kw(telemetry.get("get_grid_export_power_limit"))


def resolve_live_export_context(
    *,
    matrix_row: dict[str, Any] | None = None,
    telemetry: dict[str, Any] | None = None,
    house_doc: dict | None = None,
) -> dict[str, Any]:
    """HK + inbound + pay-to-export → effective cap for Live/MILP t0."""
    doc = house_doc if house_doc is not None else load_house_doc()
    hk = plant_max_export_power_kw(doc)
    inbound = read_inbound_export_limit_kw(telemetry)
    k_push = None
    if isinstance(matrix_row, dict):
        k_push = matrix_row.get("k_push_act")
    effective = effective_export_cap_kw(
        hk_max_export_kw=hk,
        inbound_limit_kw=inbound,
        k_push_act=k_push,
    )
    return {
        "hk_max_export_kw": hk,
        "inbound_export_limit_kw": inbound,
        "effective_export_cap_kw": effective,
    }
