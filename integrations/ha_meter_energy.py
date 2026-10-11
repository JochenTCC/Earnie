"""HA cumulative energy entities for slot-Ist ΔkWh overlay (2.6.c).

Side channel only — does not extend EHAL telemetry. Readings use the same
``{total[, total_neg]}`` shape as the Loxone VO-push reader so
``overlay_counter_on_closed`` can reuse import / export.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from ehal.functions import available_functions
from integrations.ha_units import UnitMismatchError, to_ehal
from integrations.loxone_meter_energy import CHANNEL_GRID, CHANNEL_PV

logger = logging.getLogger(__name__)


def _adapter_weg_b(adapter: Any) -> bool:
    from runtime_store.ehal_setup import HA_TRANSPORT_WEG_B

    transport = str(getattr(getattr(adapter, "cfg", None), "transport", "") or "")
    return transport == HA_TRANSPORT_WEG_B

FIELD_PV_ENERGY = "sens_pv_energy"
FIELD_GRID_IMPORT = "sens_grid_energy_import"
FIELD_GRID_EXPORT = "sens_grid_energy_export"

ENERGY_OPTIONAL = (
    FIELD_PV_ENERGY,
    FIELD_GRID_IMPORT,
    FIELD_GRID_EXPORT,
)


def parse_ha_energy_kwh(
    state: str, *, unit: str | None, field: str = FIELD_PV_ENERGY
) -> float:
    """Parse HA energy state into kWh (Wh / kWh / MWh from the entity unit).

    Raises ``UnitMismatchError`` if the unit is not an energy unit (e.g. W).
    """
    text = str(state).strip().replace(",", ".")
    if text.lower() in ("", "unavailable", "unknown", "none"):
        raise ValueError(f"HA energy state is not numeric: {state!r}")
    return to_ehal(field, float(text), unit)


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
    field: str = FIELD_PV_ENERGY,
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
            field=field,
        )
    except UnitMismatchError as exc:
        logger.warning("ha_meter_energy: %s skipped: %s", entity_id, exc)
        return None
    except (TypeError, ValueError) as exc:
        logger.debug("ha_meter_energy: parse %s failed: %s", entity_id, exc)
        return None


def _weg_b_energy_readings(
    adapter: Any,
    mapped: dict[str, str],
) -> dict[str, dict[str, float]]:
    from integrations.ha_push_read import read_push_energy_kwh

    qids = getattr(adapter.cfg, "push_read_qids", {}) or {}
    readings: dict[str, dict[str, float]] = {}
    pv_field = FIELD_PV_ENERGY
    pv_id = mapped.get(pv_field)
    if pv_field in qids:
        total = read_push_energy_kwh(qids[pv_field])
        if total is not None:
            readings[CHANNEL_PV] = {"total": float(total)}
    elif pv_id:
        total = _read_entity_kwh(adapter, pv_id, FIELD_PV_ENERGY)
        if total is not None:
            readings[CHANNEL_PV] = {"total": float(total)}

    grid: dict[str, float] = {}
    for field, attr in (
        (FIELD_GRID_IMPORT, "total"),
        (FIELD_GRID_EXPORT, "total_neg"),
    ):
        if field in qids:
            val = read_push_energy_kwh(qids[field])
            if val is not None:
                grid[attr] = float(val)
        else:
            eid = mapped.get(field)
            if eid:
                val = _read_entity_kwh(adapter, eid, field)
                if val is not None:
                    grid[attr] = float(val)
    if "total" in grid:
        readings[CHANNEL_GRID] = grid
    return readings


def read_plant_energy_readings(
    adapter: Any,
    *,
    entities: dict[str, str] | None = None,
) -> dict[str, dict[str, float]]:
    """Read PV / grid cumulative kWh; omit channels with missing reads.

    Empty unless all three counters are mapped (function ``slot_energy``): a
    partial map would mix counter-based and sampled values in one slot.
    """
    mapped = plant_energy_entity_ids(entities if entities is not None else adapter.cfg.entities)
    if "slot_energy" not in available_functions(
        mapped,
        require_nonempty_value=not _adapter_weg_b(adapter),
    ):
        if mapped:
            logger.debug("ha_meter_energy: counters incomplete %s — slot Ist stays on mean", sorted(mapped))
        return {}
    if _adapter_weg_b(adapter):
        return _weg_b_energy_readings(adapter, mapped)
    readings: dict[str, dict[str, float]] = {}
    pv_id = mapped.get(FIELD_PV_ENERGY)
    if pv_id:
        total = _read_entity_kwh(adapter, pv_id, FIELD_PV_ENERGY)
        if total is not None:
            readings[CHANNEL_PV] = {"total": float(total)}

    import_id = mapped.get(FIELD_GRID_IMPORT)
    export_id = mapped.get(FIELD_GRID_EXPORT)
    grid: dict[str, float] = {}
    if import_id:
        total = _read_entity_kwh(adapter, import_id, FIELD_GRID_IMPORT)
        if total is not None:
            grid["total"] = float(total)
    if export_id:
        total_neg = _read_entity_kwh(adapter, export_id, FIELD_GRID_EXPORT)
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
