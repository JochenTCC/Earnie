"""HA cumulative energy entities for slot-Ist ΔkWh overlay (2.6.c).

Side channel only — does not extend EHAL telemetry. Readings use the same
shape as ``loxone_meter_energy`` so ``overlay_counter_on_closed`` can reuse
``total`` / ``total_neg`` (import / export).
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from integrations.loxone_meter_energy import CHANNEL_GRID, CHANNEL_PV

logger = logging.getLogger(__name__)

FIELD_PV_ENERGY = "sens_pv_energy"
FIELD_GRID_IMPORT = "sens_grid_energy_import"
FIELD_GRID_EXPORT = "sens_grid_energy_export"

ENERGY_OPTIONAL = (
    FIELD_PV_ENERGY,
    FIELD_GRID_IMPORT,
    FIELD_GRID_EXPORT,
)


def parse_ha_energy_kwh(state: str, *, unit: str | None) -> float:
    """Parse HA energy state; convert Wh → kWh when unit indicates watt-hours."""
    text = str(state).strip().replace(",", ".")
    if text.lower() in ("", "unavailable", "unknown", "none"):
        raise ValueError(f"HA energy state is not numeric: {state!r}")
    value = float(text)
    unit_l = str(unit or "").strip().lower()
    if unit_l in ("wh", "watt-hour", "watt-hours", "watthour", "watthours"):
        return value / 1000.0
    return value


def plant_energy_entity_ids(
    entities: dict[str, str] | None,
) -> dict[str, str]:
    """Return mapped energy entity IDs (empty values omitted)."""
    raw = entities or {}
    out: dict[str, str] = {}
    for field in ENERGY_OPTIONAL:
        eid = str(raw.get(field) or "").strip()
        if eid:
            out[field] = eid
    return out


def _read_entity_kwh(
    adapter: Any,
    entity_id: str,
) -> float | None:
    try:
        payload = adapter.read_state(entity_id)
    except Exception as exc:  # noqa: BLE001 — best-effort side channel
        logger.debug("ha_meter_energy: read %s failed: %s", entity_id, exc)
        return None
    if not isinstance(payload, dict):
        return None
    attrs = payload.get("attributes") if isinstance(payload.get("attributes"), dict) else {}
    try:
        return parse_ha_energy_kwh(
            str(payload.get("state")),
            unit=attrs.get("unit_of_measurement"),
        )
    except (TypeError, ValueError) as exc:
        logger.debug("ha_meter_energy: parse %s failed: %s", entity_id, exc)
        return None


def read_plant_energy_readings(
    adapter: Any,
    *,
    entities: dict[str, str] | None = None,
) -> dict[str, dict[str, float]]:
    """Read PV / grid cumulative kWh; omit channels with missing maps or reads."""
    mapped = plant_energy_entity_ids(entities if entities is not None else adapter.cfg.entities)
    readings: dict[str, dict[str, float]] = {}
    pv_id = mapped.get(FIELD_PV_ENERGY)
    if pv_id:
        total = _read_entity_kwh(adapter, pv_id)
        if total is not None:
            readings[CHANNEL_PV] = {"total": float(total)}

    import_id = mapped.get(FIELD_GRID_IMPORT)
    export_id = mapped.get(FIELD_GRID_EXPORT)
    grid: dict[str, float] = {}
    if import_id:
        total = _read_entity_kwh(adapter, import_id)
        if total is not None:
            grid["total"] = float(total)
    if export_id:
        total_neg = _read_entity_kwh(adapter, export_id)
        if total_neg is not None:
            grid["total_neg"] = float(total_neg)
    if "total" in grid:
        readings[CHANNEL_GRID] = grid
    return readings


def read_ha_plant_energy(
    *,
    get_adapter: Callable[[], Any] | None = None,
) -> dict[str, dict[str, float]] | None:
    """Live HA plant energy for the power_interval_sampler side channel."""
    try:
        from integrations import ehal_live

        adapter_fn = get_adapter or ehal_live.get_ha_adapter
        if not ehal_live.is_ha_backend():
            return None
        adapter = adapter_fn()
    except Exception as exc:  # noqa: BLE001
        logger.debug("ha_meter_energy: adapter unavailable: %s", exc)
        return None
    if adapter is None:
        return None
    try:
        readings = read_plant_energy_readings(adapter)
    except Exception as exc:  # noqa: BLE001
        logger.debug("ha_meter_energy: plant read failed: %s", exc)
        return None
    return readings or None
