"""HA cumulative energy via push inbox for slot-Ist ΔkWh overlay (2.6.c / Binding P5e).

Side channel only — does not extend EHAL telemetry. Readings use the same
``{total[, total_neg]}`` shape as the Loxone VO-push reader so
``overlay_counter_on_closed`` can reuse import / export.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from ehal.functions import available_functions
from integrations.ha_units import to_ehal
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


def parse_ha_energy_kwh(
    state: str, *, unit: str | None, field: str = FIELD_PV_ENERGY
) -> float:
    """Parse an energy state string into kWh (Wh / kWh / MWh).

    Kept for unit tests and Jinja-side documentation; live reads use the push inbox.
    """
    text = str(state).strip().replace(",", ".")
    if text.lower() in ("", "unavailable", "unknown", "none"):
        raise ValueError(f"HA energy state is not numeric: {state!r}")
    return to_ehal(field, float(text), unit)


def plant_energy_entity_ids(
    entities: dict[str, str] | None,
) -> dict[str, str]:
    """Return activated energy binding keys (values may be empty activation flags)."""
    raw = entities or {}
    out: dict[str, str] = {}
    for field in ENERGY_OPTIONAL:
        if field in raw:
            out[field] = str(raw.get(field) or "").strip()
    return out


def _push_energy_readings(
    adapter: Any,
    mapped: dict[str, str],
) -> dict[str, dict[str, float]]:
    from integrations.ha_push_read import read_push_energy_kwh

    qids = getattr(adapter.cfg, "push_read_qids", {}) or {}
    readings: dict[str, dict[str, float]] = {}
    pv_field = FIELD_PV_ENERGY
    if pv_field in mapped and pv_field in qids:
        total = read_push_energy_kwh(qids[pv_field])
        if total is not None:
            readings[CHANNEL_PV] = {"total": float(total)}

    grid: dict[str, float] = {}
    for field, attr in (
        (FIELD_GRID_IMPORT, "total"),
        (FIELD_GRID_EXPORT, "total_neg"),
    ):
        if field not in mapped or field not in qids:
            continue
        val = read_push_energy_kwh(qids[field])
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
    """Read PV / grid cumulative kWh from the push inbox; omit incomplete maps."""
    mapped = plant_energy_entity_ids(
        entities if entities is not None else adapter.cfg.entities
    )
    if "slot_energy" not in available_functions(
        mapped,
        require_nonempty_value=False,
    ):
        if mapped:
            logger.debug(
                "ha_meter_energy: counters incomplete %s — slot Ist stays on mean",
                sorted(mapped),
            )
        return {}
    return _push_energy_readings(adapter, mapped)


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
