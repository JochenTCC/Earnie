"""Resolve Live export-power ceilings (2.7.a) from HK + inbound EHAL."""
from __future__ import annotations

from typing import Any

from optimizer.battery import MODE_EINSPEISESPERRE
from optimizer.export_power_limit import (
    effective_export_cap_kw,
    inbound_limit_w_to_kw,
    plant_max_export_power_kw,
)


def load_house_doc() -> dict:
    from house_config.profiles_store import load_house_profiles_document
    from runtime_store.persist_paths import resolve_house_profiles_json_path

    return load_house_profiles_document(resolve_house_profiles_json_path())


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


def apply_einspeisesperre_mode(mode: int, effective_cap_kw: float | None) -> int:
    """When effective export cap is hard 0, prefer Einspeisesperre mode."""
    if effective_cap_kw is not None and float(effective_cap_kw) <= 1e-12:
        return MODE_EINSPEISESPERRE
    return mode
