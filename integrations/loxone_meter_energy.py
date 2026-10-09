"""Loxone meter cumulative energy for slot-Ist ΔkWh overlay (VO push / inbox)."""
from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

CHANNEL_PV = "pv"
CHANNEL_GRID = "grid"

FIELD_PV_ENERGY = "sens_pv_energy"
FIELD_GRID_IMPORT = "sens_grid_energy_import"
FIELD_GRID_EXPORT = "sens_grid_energy_export"
FIELD_CONSUMER_TOTAL = "sens_energy_total"
FIELD_ESS_CHARGE = "sens_ess_energy_charge"
FIELD_ESS_DISCHARGE = "sens_ess_energy_discharge"

PLANT_ENERGY_FIELDS = (
    FIELD_PV_ENERGY,
    FIELD_GRID_IMPORT,
    FIELD_GRID_EXPORT,
)
CONSUMER_ENERGY_FIELDS = (FIELD_CONSUMER_TOTAL,)
BATTERY_ENERGY_FIELDS = (FIELD_ESS_CHARGE, FIELD_ESS_DISCHARGE)
ENERGY_ACTIVATION_KINDS = frozenset(
    PLANT_ENERGY_FIELDS + CONSUMER_ENERGY_FIELDS + BATTERY_ENERGY_FIELDS
)


def meter_has_energy_states(meta: dict[str, Any] | None) -> bool:
    """True when LoxAPP3 Meter control exposes cumulative ``total``."""
    if not isinstance(meta, dict):
        return False
    if str(meta.get("type") or "") != "Meter":
        return False
    states = meta.get("states")
    if not isinstance(states, dict):
        return False
    return bool(str(states.get("total") or "").strip())


def meter_is_bidirectional(meta: dict[str, Any] | None) -> bool:
    if not isinstance(meta, dict):
        return False
    details = meta.get("details") if isinstance(meta.get("details"), dict) else {}
    details_type = str(details.get("type") or "").strip().lower()
    if details_type == "bidirectional":
        return True
    states = meta.get("states") if isinstance(meta.get("states"), dict) else {}
    return bool(str(states.get("totalNeg") or "").strip())


def energy_binding_activated(bindings: dict[str, Any] | None, field: str) -> bool:
    """True when the energy field key is present (Merker name may be empty)."""
    if not isinstance(bindings, dict):
        return False
    return field in bindings


def activate_plant_energy_bindings(
    plant: dict[str, Any],
    *,
    pv: bool = False,
    grid: bool = False,
    bidirectional: bool = False,
) -> None:
    """Activate plant energy push fields on ``ehal_bindings`` (in-place)."""
    bindings = (
        dict(plant["ehal_bindings"])
        if isinstance(plant.get("ehal_bindings"), dict)
        else {}
    )
    if pv:
        bindings.setdefault(FIELD_PV_ENERGY, "")
    if grid:
        bindings.setdefault(FIELD_GRID_IMPORT, "")
        if bidirectional:
            bindings.setdefault(FIELD_GRID_EXPORT, "")
    plant["ehal_bindings"] = bindings


def activate_consumer_energy_bindings(consumer: dict[str, Any]) -> None:
    """Activate consumer energy push field on ``ehal_bindings`` (in-place).

    Consumers are mono only (``sens_energy_total``); they cannot export energy.
    """
    bindings = (
        dict(consumer["ehal_bindings"])
        if isinstance(consumer.get("ehal_bindings"), dict)
        else {}
    )
    bindings.setdefault(FIELD_CONSUMER_TOTAL, "")
    consumer["ehal_bindings"] = bindings


def activate_battery_energy_bindings(
    battery: dict[str, Any],
    *,
    bidirectional: bool = True,
) -> None:
    """Activate ESS energy push fields on ``batteries[].ehal_bindings`` (in-place).

    Storage meters are bipolar by default (charge + discharge). Keys are Pattern B
    ``ess.{id}.sens_ess_energy_*`` when the battery has an id, else flat kinds.
    """
    from ehal.ess_fields import ess_field

    bindings = (
        dict(battery["ehal_bindings"])
        if isinstance(battery.get("ehal_bindings"), dict)
        else {}
    )
    bid = str(battery.get("id") or "").strip()
    charge_key = ess_field(bid, FIELD_ESS_CHARGE) if bid else FIELD_ESS_CHARGE
    discharge_key = ess_field(bid, FIELD_ESS_DISCHARGE) if bid else FIELD_ESS_DISCHARGE
    bindings.setdefault(charge_key, "")
    if bidirectional:
        bindings.setdefault(discharge_key, "")
    battery["ehal_bindings"] = bindings


def _read_counter(
    ehal_id: str,
    *,
    read_counter: Callable[..., float | None] | None,
    now: Any = None,
) -> float | None:
    if read_counter is not None:
        return read_counter(ehal_id, now=now) if now is not None else read_counter(ehal_id)
    from runtime_store.loxone_push_inbox import read_push_counter

    return (
        read_push_counter(ehal_id, now=now)
        if now is not None
        else read_push_counter(ehal_id)
    )


def read_plant_energy_readings(
    plant: dict[str, Any] | None = None,
    *,
    read_counter: Callable[..., float | None] | None = None,
    now: Any = None,
) -> dict[str, dict[str, float]]:
    """``{pv|grid: {total[, total_neg]}}`` from fresh inbox counters."""
    from ehal.qualified_ids import qualified_plant_id

    bindings = (
        (plant or {}).get("ehal_bindings")
        if isinstance((plant or {}).get("ehal_bindings"), dict)
        else {}
    )
    readings: dict[str, dict[str, float]] = {}
    if energy_binding_activated(bindings, FIELD_PV_ENERGY):
        # PV still bare plant (grid.meter-style pv.* deferred — see backlog 2.7.n).
        total = _read_counter(FIELD_PV_ENERGY, read_counter=read_counter, now=now)
        if total is not None:
            readings[CHANNEL_PV] = {"total": float(total)}
    if energy_binding_activated(bindings, FIELD_GRID_IMPORT):
        grid: dict[str, float] = {}
        import_id = qualified_plant_id(FIELD_GRID_IMPORT)
        total = _read_counter(import_id, read_counter=read_counter, now=now)
        if total is not None:
            grid["total"] = float(total)
        if energy_binding_activated(bindings, FIELD_GRID_EXPORT):
            export_id = qualified_plant_id(FIELD_GRID_EXPORT)
            total_neg = _read_counter(export_id, read_counter=read_counter, now=now)
            if total_neg is not None:
                grid["total_neg"] = float(total_neg)
        if "total" in grid:
            readings[CHANNEL_GRID] = grid
    return readings


def _consumer_has_shared_meter(consumer: dict[str, Any]) -> bool:
    subtract_ids = (consumer.get("loxone_inputs") or {}).get("subtract_consumer_ids") or []
    return bool(subtract_ids)


def flex_energy_meter_config(
    consumers: list[dict[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    """``{consumer_id: {}}`` for slot-Ist ΔE candidates (push fields; mono only)."""
    out: dict[str, dict[str, Any]] = {}
    for consumer in consumers or []:
        if not isinstance(consumer, dict):
            continue
        cid = str(consumer.get("id") or "").strip()
        if not cid or _consumer_has_shared_meter(consumer):
            continue
        bindings = consumer.get("ehal_bindings")
        if not energy_binding_activated(bindings, FIELD_CONSUMER_TOTAL):
            continue
        out[cid] = {}
    return out


def read_flex_energy_readings(
    consumers: list[dict[str, Any]] | None,
    *,
    read_counter: Callable[..., float | None] | None = None,
    now: Any = None,
) -> dict[str, dict[str, float]]:
    """``{consumer_id: {total}}`` from fresh inbox counters (mono only)."""
    from ehal.qualified_ids import qualified_consumer_id

    readings: dict[str, dict[str, float]] = {}
    for consumer in consumers or []:
        if not isinstance(consumer, dict):
            continue
        cid = str(consumer.get("id") or "").strip()
        if not cid or _consumer_has_shared_meter(consumer):
            continue
        bindings = consumer.get("ehal_bindings")
        if not energy_binding_activated(bindings, FIELD_CONSUMER_TOTAL):
            continue
        ctype = str(consumer.get("type") or "")
        total_id = qualified_consumer_id(cid, ctype, FIELD_CONSUMER_TOTAL)
        total = _read_counter(total_id, read_counter=read_counter, now=now)
        if total is None:
            continue
        readings[cid] = {"total": float(total)}
    return readings


def load_live_profile_consumers() -> list[dict[str, Any]]:
    """Consumers from ``house_profiles.json`` live profile."""
    try:
        import os

        from house_config.profiles_store import load_house_profiles_document
        from runtime_store.persist_paths import resolve_house_profiles_json_path
        from ui.ehal_loxone_mapping import resolve_live_profile_id
    except ImportError:
        return []
    path = resolve_house_profiles_json_path()
    if not path or not os.path.isfile(path):
        return []
    try:
        doc = load_house_profiles_document(path)
    except (OSError, ValueError, TypeError):
        return []
    if not isinstance(doc, dict):
        return []
    profile_id = resolve_live_profile_id(doc)
    profiles = doc.get("profiles")
    if not profile_id or not isinstance(profiles, dict):
        return []
    profile = profiles.get(profile_id)
    if not isinstance(profile, dict):
        return []
    return [
        c for c in (profile.get("consumers") or []) if isinstance(c, dict)
    ]


def load_live_plant() -> dict[str, Any]:
    """Plant block from ``house_profiles.json``."""
    try:
        import os

        from house_config.profiles_store import load_house_profiles_document
        from runtime_store.persist_paths import resolve_house_profiles_json_path
    except ImportError:
        return {}
    path = resolve_house_profiles_json_path()
    if not path or not os.path.isfile(path):
        return {}
    try:
        doc = load_house_profiles_document(path)
    except (OSError, ValueError, TypeError):
        return {}
    if not isinstance(doc, dict):
        return {}
    plant = doc.get("plant")
    return plant if isinstance(plant, dict) else {}


def _flex_power_sources(flex_kw: dict[str, Any] | None) -> dict[str, str]:
    return {str(key): "mean" for key in (flex_kw or {})}


def _overlay_flex_counters(
    out: dict[str, Any],
    *,
    open_r: dict[str, Any],
    end_r: dict[str, Any],
    dt_h: float,
    flex_meter_config: dict[str, dict[str, Any]] | None,
) -> None:
    flex_open = open_r.get("flex")
    flex_end = end_r.get("flex")
    if not isinstance(flex_open, dict) or not isinstance(flex_end, dict):
        return
    flex_kw = dict(out.get("flex_kw") or {})
    flex_energy: dict[str, float] = dict(out.get("flex_energy_kwh") or {})
    flex_sources = _flex_power_sources(flex_kw)
    cfg = flex_meter_config or {}
    for consumer_id, open_read in flex_open.items():
        fid = str(consumer_id)
        end_read = flex_end.get(consumer_id)
        if not isinstance(open_read, dict) or not isinstance(end_read, dict):
            continue
        bipolar = bool((cfg.get(fid) or {}).get("bidirectional"))
        delta = channel_delta_kwh(open_read, end_read, bipolar=bipolar)
        if delta is None:
            continue
        flex_kw[fid] = round(delta / dt_h, 3)
        flex_energy[fid] = round(delta, 4)
        flex_sources[fid] = "counter"
    out["flex_kw"] = flex_kw
    if flex_energy:
        out["flex_energy_kwh"] = flex_energy
    sources = out.setdefault("ist_power_source", {})
    sources["flex"] = flex_sources


def mono_delta_kwh(start: float | None, end: float | None) -> float | None:
    """Non-negative counter delta; None on missing or reset."""
    if start is None or end is None:
        return None
    try:
        delta = float(end) - float(start)
    except (TypeError, ValueError):
        return None
    if delta < -1e-6:
        return None
    return max(0.0, delta)


def channel_delta_kwh(
    start: dict[str, float] | None,
    end: dict[str, float] | None,
    *,
    bipolar: bool,
) -> float | None:
    """PV: Δtotal. Grid bipolar: Δtotal − Δtotal_neg (EHAL + = import)."""
    if not isinstance(start, dict) or not isinstance(end, dict):
        return None
    d_pos = mono_delta_kwh(start.get("total"), end.get("total"))
    if d_pos is None:
        return None
    if not bipolar:
        return d_pos
    if "total_neg" not in start or "total_neg" not in end:
        return d_pos
    d_neg = mono_delta_kwh(start.get("total_neg"), end.get("total_neg"))
    if d_neg is None:
        return None
    return d_pos - d_neg


def overlay_counter_on_closed(
    closed: dict[str, Any],
    *,
    open_readings: dict[str, dict[str, float]] | None,
    end_readings: dict[str, dict[str, float]] | None,
    dt_h: float,
    flex_meter_config: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Prefer measured ΔkWh → avg kW for pv/grid and flex Meters; others stay mean."""
    out = dict(closed)
    sources: dict[str, Any] = {
        "pv": "mean",
        "grid": "mean",
        "battery": "mean",
        "house": "mean",
        "baseload": "mean",
        "flex": _flex_power_sources(out.get("flex_kw")),
    }
    open_r = open_readings or {}
    end_r = end_readings or {}
    pv_delta = channel_delta_kwh(
        open_r.get(CHANNEL_PV), end_r.get(CHANNEL_PV), bipolar=False
    )
    if pv_delta is not None:
        out["pv_energy_kwh"] = round(pv_delta, 4)
        out["pv_kw"] = round(pv_delta / dt_h, 3)
        sources["pv"] = "counter"
    grid_delta = channel_delta_kwh(
        open_r.get(CHANNEL_GRID), end_r.get(CHANNEL_GRID), bipolar=True
    )
    if grid_delta is not None:
        out["grid_energy_kwh"] = round(grid_delta, 4)
        out["grid_kw"] = round(grid_delta / dt_h, 3)
        sources["grid"] = "counter"
    out["ist_power_source"] = sources
    _overlay_flex_counters(
        out,
        open_r=open_r,
        end_r=end_r,
        dt_h=dt_h,
        flex_meter_config=flex_meter_config,
    )
    return out


def controls_by_name(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """LoxAPP3 control name → meta (casefold key for lookup)."""
    controls = doc.get("controls") if isinstance(doc.get("controls"), dict) else {}
    out: dict[str, dict[str, Any]] = {}
    for meta in controls.values():
        if not isinstance(meta, dict):
            continue
        name = str(meta.get("name") or "").strip()
        if name:
            out[name.casefold()] = meta
    return out
