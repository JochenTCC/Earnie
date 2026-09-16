"""Loxone Meter cumulative energy (total / totalNeg) for slot-Ist ΔkWh overlay."""
from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Plant EHAL power fields that may share a Meter control with energy states.
_PV_FIELD = "sens_pv_production_active"
_GRID_FIELD = "sens_grid_power_active"
CHANNEL_PV = "pv"
CHANNEL_GRID = "grid"

# Structure-file / WS use total|totalNeg; HTTP /all uses Meter block abbreviations.
_ENERGY_NAME_ALIASES = {
    "total": "total",
    "totalneg": "total_neg",
    "mr": "total",  # unidirectional Meter reading
    "mrc": "total",  # bidirectional consumption reading
    "mrd": "total_neg",  # bidirectional delivery reading
}


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


def energy_from_io_all(ll: dict[str, Any] | None) -> dict[str, float] | None:
    """Parse Meter ``total`` / ``totalNeg`` kWh from ``/jdev/sps/io/{name}/all`` LL."""
    if not isinstance(ll, dict):
        return None
    found: dict[str, float] = {}
    for item in ll.values():
        if not isinstance(item, dict):
            continue
        raw_name = str(item.get("name") or item.get("Name") or "").strip()
        key = _ENERGY_NAME_ALIASES.get(raw_name.casefold())
        if not key:
            continue
        parsed = _parse_energy_value(item.get("value"))
        if parsed is None:
            continue
        found[key] = parsed
    return found or None


def _parse_energy_value(raw: Any) -> float | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        from integrations.loxone_client import _parse_loxone_numeric

        return float(_parse_loxone_numeric(text))
    except (ValueError, TypeError, ImportError):
        try:
            return float(text.replace(",", ".").split()[0])
        except (ValueError, TypeError, IndexError):
            return None


def fetch_meter_energy_kwh(
    meter_name: str,
    *,
    fetch_all: Callable[[str], dict[str, Any] | None] | None = None,
) -> dict[str, float] | None:
    """Live cumulative kWh for one Meter control name."""
    name = str(meter_name or "").strip()
    if not name:
        return None
    if fetch_all is None:
        from integrations.loxone_client import _fetch_loxone_io_all

        fetch_all = _fetch_loxone_io_all
    try:
        ll = fetch_all(name)
    except Exception as exc:  # noqa: BLE001
        logger.debug("meter energy /all failed for %r: %s", name, exc)
        return None
    return energy_from_io_all(ll)


def plant_energy_meter_names(
    *,
    plant: dict[str, Any] | None = None,
    config_get: Callable[[str], Any] | None = None,
) -> dict[str, str]:
    """Map channel → Meter name from ``loxone_meter_energy`` or power bindings."""
    plant = plant if isinstance(plant, dict) else {}
    energy_map = plant.get("loxone_meter_energy")
    bindings = plant.get("ehal_bindings") if isinstance(plant.get("ehal_bindings"), dict) else {}
    out: dict[str, str] = {}
    for channel, field in ((CHANNEL_PV, _PV_FIELD), (CHANNEL_GRID, _GRID_FIELD)):
        name = ""
        if isinstance(energy_map, dict):
            raw = energy_map.get(field)
            if isinstance(raw, dict):
                name = str(raw.get("name") or "").strip()
            else:
                name = str(raw or "").strip()
        if not name:
            name = str(bindings.get(field) or "").strip()
        if not name and config_get is not None:
            cfg_key = (
                "LOXONE_PV_POWER_NAME"
                if channel == CHANNEL_PV
                else "LOXONE_GRID_POWER_NAME"
            )
            name = str(config_get(cfg_key) or "").strip()
        if name:
            out[channel] = name
    return out


def read_plant_energy_readings(
    meter_names: dict[str, str],
    *,
    fetch_meter: Callable[[str], dict[str, float] | None] | None = None,
) -> dict[str, dict[str, float]]:
    """``{pv|grid: {total[, total_neg]}}`` for configured Meter names."""
    fetch = fetch_meter or fetch_meter_energy_kwh
    readings: dict[str, dict[str, float]] = {}
    for channel, name in meter_names.items():
        energy = fetch(name)
        if energy:
            readings[channel] = energy
    return readings


def _consumer_has_shared_meter(consumer: dict[str, Any]) -> bool:
    subtract_ids = (consumer.get("loxone_inputs") or {}).get("subtract_consumer_ids") or []
    return bool(subtract_ids)


def _consumer_power_meter_name(consumer: dict[str, Any]) -> str:
    from settings.ehal_marker_resolve import (
        marker_flex_power,
        marker_sens_evcs_active_power,
    )

    name = marker_flex_power(consumer) or marker_sens_evcs_active_power(consumer)
    if name:
        return name
    inputs = consumer.get("loxone_inputs")
    if isinstance(inputs, dict):
        return str(inputs.get("power_name") or "").strip()
    return ""


def flex_energy_meter_config(
    consumers: list[dict[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    """``{consumer_id: {name, bidirectional}}`` for slot-Ist ΔE candidates."""
    out: dict[str, dict[str, Any]] = {}
    for consumer in consumers or []:
        if not isinstance(consumer, dict):
            continue
        cid = str(consumer.get("id") or "").strip()
        if not cid or _consumer_has_shared_meter(consumer):
            continue
        energy_map = consumer.get("loxone_meter_energy")
        if isinstance(energy_map, dict):
            name = str(energy_map.get("name") or "").strip()
            if name:
                out[cid] = {
                    "name": name,
                    "bidirectional": bool(energy_map.get("bidirectional")),
                }
                continue
        name = _consumer_power_meter_name(consumer)
        if name:
            out[cid] = {"name": name, "bidirectional": False}
    return out


def flex_energy_meter_names(
    consumers: list[dict[str, Any]] | None,
) -> dict[str, str]:
    """Map flex consumer id → Meter name (skips shared-meter primaries)."""
    cfg = flex_energy_meter_config(consumers)
    return {cid: meta["name"] for cid, meta in cfg.items()}


def read_flex_energy_readings(
    meter_names: dict[str, str],
    *,
    fetch_meter: Callable[[str], dict[str, float] | None] | None = None,
) -> dict[str, dict[str, float]]:
    """``{consumer_id: {total[, total_neg]}}`` for configured flex Meter names."""
    fetch = fetch_meter or fetch_meter_energy_kwh
    readings: dict[str, dict[str, float]] = {}
    for consumer_id, name in meter_names.items():
        energy = fetch(name)
        if energy:
            readings[str(consumer_id)] = energy
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


def bind_consumer_meter_energy(
    consumer: dict[str, Any],
    *,
    meter_name: str,
    bidirectional: bool = False,
) -> None:
    """Record Loxone-local energy binding on a flex consumer (in-place)."""
    name = str(meter_name or "").strip()
    if not name:
        return
    consumer["loxone_meter_energy"] = {
        "name": name,
        "bidirectional": bool(bidirectional),
    }


def bind_plant_meter_energy(
    plant: dict[str, Any],
    *,
    ehal_field: str,
    meter_name: str,
    bidirectional: bool = False,
) -> None:
    """Record Loxone-local energy binding next to plant power (in-place)."""
    name = str(meter_name or "").strip()
    field = str(ehal_field or "").strip()
    if not name or field not in {_PV_FIELD, _GRID_FIELD}:
        return
    energy = dict(plant.get("loxone_meter_energy") or {})
    energy[field] = {"name": name, "bidirectional": bool(bidirectional)}
    plant["loxone_meter_energy"] = energy


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
