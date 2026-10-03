"""Resolve Live export-power ceilings (2.7.a) from HK + inbound EHAL."""
from __future__ import annotations

from typing import Any

from optimizer.export_power_limit import (
    effective_export_cap_kw,
    inbound_limit_w_to_kw,
    physical_max_export_kw,
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

    if control_from_battery_params(battery_params) != BATTERY_CONTROL_FULL:
        return 0.0
    return float(
        battery_params.get(
            "max_discharge_power_kw",
            battery_params.get("max_power_kw") or 0.0,
        )
        or 0.0
    )


def live_unconstrained_export_kw() -> float | None:
    """Plant export maximum written as "unconstrained" on the export-limit setpoint.

    PV nameplate (sum of all PV systems) + max discharge power of every battery that
    can be force-discharged (``battery_control = full``). Skips ``limits_only`` /
    ``read_only`` (2.7.c). Powerstations (2.7.g/h) are not in the list yet.
    """
    import config

    discharge_kw = 0.0
    get_list = getattr(config, "get_battery_params_list", None)
    if callable(get_list):
        for bat in get_list() or []:
            discharge_kw += _force_dischargeable_discharge_kw(bat)
    else:
        discharge_kw = _force_dischargeable_discharge_kw(config.get_battery_params())
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
