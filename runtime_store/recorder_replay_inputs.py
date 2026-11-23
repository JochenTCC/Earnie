"""Recorder replay: recorded live inputs (planning moment, EV/thermal reads, limits, battery params).

Split from ``runtime_store.recorder_replay`` (KPI refactor); that module re-exports these names.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from typing import Any


def _recorded_planning_moment(entry: dict[str, Any]) -> datetime:
    """The instant ``planning_now()`` returned in the live cycle.

    An early-start cycle begins a few seconds before its quarter-hour tick and
    plans for it: ``planning_now() = max(real now, tick)``. The recorded
    ``timestamp`` is the real clock, ``planning_window.start`` is that tick
    (a late or out-of-band cycle has a start before its timestamp). Freezing at
    the timestamp put 23:59:57 on the previous day and 08:59:53 in the hour
    before the plan, so day/hour-bound consumer state differed from live.
    """
    recorded = datetime.fromisoformat(str(entry.get("timestamp") or ""))
    window = entry.get("planning_window")
    if not isinstance(window, dict) or not window.get("start"):
        raise ValueError("entry missing planning_window.start")
    start = datetime.fromisoformat(str(window["start"]))
    # Naive values are system-local, like the recorder's ``datetime.now()`` stamp.
    return max(_aware_local(recorded), _aware_local(start))


def _aware_local(moment: datetime) -> datetime:
    return moment.astimezone() if moment.tzinfo is None else moment


@contextmanager
def _recorded_ev_limit_soc(entry: dict[str, Any], config_module: Any):
    """Serve the recorded ``get_evcs_limit_soc`` for the EV markers during replay.

    Fails loud when the marker is actually read but the entry has no recorded
    value (cycles recorded before ``ev_limit_soc_percent`` existed). Cycles that
    never read it replay as before.
    """
    from integrations import ehal_live
    from settings.ehal_marker_resolve import marker_get_evcs_limit_soc

    recorded = (entry.get("start_state") or {}).get("ev_limit_soc_percent") or {}
    cid_by_marker: dict[str, str] = {}
    for consumer in config_module.get_flexible_consumers(optimizer_only=True) or []:
        marker = marker_get_evcs_limit_soc(consumer)
        if marker:
            cid_by_marker[marker] = str(consumer["id"])

    original = ehal_live.read_generic_value

    def _read(address: str):
        cid = cid_by_marker.get(address)
        if cid is None:
            return original(address)
        if cid not in recorded:
            raise ValueError(
                f"entry has no recorded start_state.ev_limit_soc_percent for "
                f"consumer {cid!r} (marker {address!r}); cycle was recorded by an "
                f"older version and cannot be replayed offline"
            )
        return float(recorded[cid])

    ehal_live.read_generic_value = _read
    try:
        yield
    finally:
        ehal_live.read_generic_value = original


@contextmanager
def _recorded_thermal_readings(entry: dict[str, Any]):
    """Serve the recorded ``fetch_thermal_readings`` per consumer during replay.

    Fails loud when a consumer's readings are actually fetched but the entry has
    none (cycles recorded before ``thermal_readings`` existed).
    """
    from integrations import ehal_live

    recorded = (entry.get("start_state") or {}).get("thermal_readings") or {}
    original = ehal_live.fetch_thermal_readings

    def _fetch(consumer: dict, **_kwargs):
        cid = str(consumer.get("id"))
        if cid not in recorded:
            raise ValueError(
                f"entry has no recorded start_state.thermal_readings for consumer "
                f"{cid!r}; cycle was recorded by an older version and cannot be "
                f"replayed offline"
            )
        return dict(recorded[cid])

    ehal_live.fetch_thermal_readings = _fetch
    try:
        yield
    finally:
        ehal_live.fetch_thermal_readings = original


def _require_push_price_cent(config_module: Any) -> float:
    raw = config_module.get_push_price_cent()
    if raw is None:
        raise ValueError(
            "get_push_price_cent() returned None; snapshot export tariff / "
            "push price must be configured for offline replay"
        )
    return float(raw)


def _recorded_sunrise_soc_min_index(entry: dict[str, Any]) -> int | None:
    """Index of the live PV-only charge limit, or None when the cycle had none.

    Seed / historical fixtures omit ``sunrise_anchor``; those replays keep the
    previous unconstrained charge path. A live window that records the anchor
    without ``slot_datetimes`` fails loud.
    """
    window = entry.get("planning_window")
    if not isinstance(window, dict):
        raise ValueError("entry missing planning_window")
    anchor_raw = window.get("sunrise_anchor")
    if not anchor_raw:
        return None
    slots = window.get("slot_datetimes")
    if not isinstance(slots, list) or not slots:
        raise ValueError(
            "planning_window has sunrise_anchor but no slot_datetimes; "
            "replay cannot apply the live PV-only charge limit"
        )
    anchor = _normalize_slot(anchor_raw)
    try:
        return [_normalize_slot(raw) for raw in slots].index(anchor)
    except ValueError as exc:
        raise ValueError(
            f"sunrise anchor {anchor.isoformat()} is not in the recorded planning window"
        ) from exc


def _normalize_slot(raw: Any) -> datetime:
    from optimizer.slot_duration import normalize_quarter_hour_slot

    moment = raw if isinstance(raw, datetime) else datetime.fromisoformat(str(raw))
    return normalize_quarter_hour_slot(moment)


def _battery_params_from_config(config_module: Any) -> dict | list[dict]:
    get_list = getattr(config_module, "get_battery_params_list", None)
    if callable(get_list):
        batteries = get_list()
        if batteries:
            return batteries
    return config_module.get_battery_params()


def _battery_params_with_recorded_reserves(
    battery_params: dict | list[dict],
    start_state: dict[str, Any],
) -> dict | list[dict]:
    """Apply the reserves the live cycle planned with (virtual refill carve-out).

    Cycles recorded before ``active_reserves`` existed keep plain config params. The SoC
    reading tolerance at the floor follows from the replayed SoC inside the MILP (Reserve P3).
    """
    if "active_reserves" not in start_state:
        return battery_params
    reserves = start_state["active_reserves"]
    if not isinstance(reserves, list):
        raise TypeError("start_state.active_reserves must be a list when present")
    from optimizer.powerstation_live import apply_reserves_to_battery_params

    return apply_reserves_to_battery_params(battery_params, reserves)


def _battery_params_with_recorded_ess_limits(
    battery_params: dict | list[dict],
    start_state: dict[str, Any],
) -> dict | list[dict]:
    """Apply the effective SOC / power limits the live cycle planned with.

    Live tightens the HK limits with ``get_ess_*`` telemetry. Cycles recorded
    before ``ess_limits`` existed keep plain config params.
    """
    if "ess_limits" not in start_state:
        return battery_params
    recorded = start_state["ess_limits"]
    if not isinstance(recorded, dict):
        raise TypeError("start_state.ess_limits must be a dict when present")

    def _apply(bat: dict) -> dict:
        ess_id = str(bat.get("id") or "")
        if ess_id not in recorded:
            raise ValueError(
                f"start_state.ess_limits has no entry for ESS {ess_id!r}; "
                f"recorded: {sorted(recorded)}"
            )
        return {**bat, **{k: float(v) for k, v in recorded[ess_id].items()}}

    if isinstance(battery_params, list):
        return [_apply(bat) for bat in battery_params]
    return _apply(battery_params)


def _filter_batteries_with_soc(
    battery_params: dict | list[dict],
    soc_by_id: dict[str, float] | None,
    start_state: dict[str, Any],
) -> dict | list[dict]:
    """Drop multi-ESS batteries without an own SoC, as the live cycle does.

    Only for cycles that recorded ``ess_limits`` (same version as the live
    filter); older cycles replay as before.
    """
    if "ess_limits" not in start_state:
        return battery_params
    from integrations.ehal_live_soc import filter_planning_batteries_with_soc

    return filter_planning_batteries_with_soc(battery_params, soc_by_id)


def _recorded_export_limits(start_state: dict[str, Any]) -> dict[str, float | None]:
    """Export ceilings of the live cycle (HK + inbound telemetry limit).

    Cycles recorded before ``export_limits`` existed replay without them, as before.
    """
    if "export_limits" not in start_state:
        return {"hk_max_export_kw": None, "inbound_export_limit_kw": None}
    recorded = start_state["export_limits"]
    if not isinstance(recorded, dict):
        raise TypeError("start_state.export_limits must be a dict when present")

    def _kw(key: str) -> float | None:
        if key not in recorded:
            raise ValueError(f"start_state.export_limits missing {key!r}")
        value = recorded[key]
        return None if value is None else float(value)

    return {
        "hk_max_export_kw": _kw("hk_max_export_kw"),
        "inbound_export_limit_kw": _kw("inbound_export_limit_kw"),
    }


def _recorded_import_caps(start_state: dict[str, Any]) -> Any:
    """Import limits of the live cycle, exactly as planned (max-power tariff P5b).

    Cycles recorded before ``import_caps`` existed replay without them, as before.
    """
    from optimizer.import_power_limit import ImportCaps

    if "import_caps" not in start_state:
        return None
    recorded = start_state["import_caps"]
    if not isinstance(recorded, dict):
        raise TypeError("start_state.import_caps must be a dict when present")
    for key in ("limits_kw", "months"):
        if key not in recorded:
            raise ValueError(f"start_state.import_caps missing {key!r}")
    limits, months = recorded["limits_kw"], recorded["months"]
    if limits is None and months is None:
        return None
    if not isinstance(limits, list) or not isinstance(months, list) or len(limits) != len(months):
        raise ValueError("start_state.import_caps: limits_kw and months must be lists of one length")
    return ImportCaps(
        tuple(None if value is None else float(value) for value in limits),
        tuple(None if value is None else str(value) for value in months),
    )


def _recorded_import_cap_observe(start_state: dict[str, Any]) -> bool:
    """Whether the live cycle ran the cap in observe mode (P6d).

    ``mode`` is recorded since P6d; a cycle recorded before had only ``optimize``, so a record
    with limits and no ``mode`` replays as planned under the cap.
    """
    from house_config.import_cap import IMPORT_CAP_MODES, MODE_OBSERVE

    recorded = start_state.get("import_caps")
    if not isinstance(recorded, dict) or "mode" not in recorded:
        return False
    mode = recorded["mode"]
    if mode is not None and mode not in IMPORT_CAP_MODES:
        raise ValueError(f"start_state.import_caps: unknown mode {mode!r}")
    return mode == MODE_OBSERVE


def _inverter_params_from_config(config_module: Any) -> list[dict] | None:
    get_list = getattr(config_module, "get_planning_inverters", None)
    if callable(get_list):
        return list(get_list() or [])
    return None


def _pv_systems_from_config(config_module: Any) -> list[dict] | None:
    get_list = getattr(config_module, "get_planning_pv_systems", None)
    if callable(get_list):
        return list(get_list() or [])
    return None
