"""Thin Live façade: OpenEMS/HA/Loxone EHAL adapters for plant I/O."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Protocol

import config
from ehal import EHAL_SCHEMA_VERSION, EhalWriteError, validate_write_error
from ehal.models import canonicalize_ha_entity_keys
from integrations import loxone_client
from integrations.ehal_live_ops import (  # noqa: F401 — façade re-exports
    OMIT_EXPORT_CAP,
    build_sent_loxone_snapshot,
    consumers_with_live_nominal_power,
    fetch_filter_native_start_hour,
    fetch_flexible_consumers_live_kw,
    fetch_heat_storage_temps,
    fetch_live_power,
    fetch_ready_by_time,
    fetch_thermal_readings,
    format_ready_by_display,
    house_profile_power_consumers,
    load_default_house_doc,
    map_ess_setpoints,
    publish_setpoint_traced,
    read_absent_mode,
    read_consumer_meter_kw,
    read_generic_value,
    read_optional_temp_c,
    resolve_consumer_battery_capacity_kwh,
    resolve_consumer_live_power_kw,
    resolve_consumer_nominal_power_kw,
    resolve_flexible_consumers_live_power,
    write_flexible_consumer_states,
    write_huawei_modbus_states,
)
from integrations.ha_adapter import HaAdapter, HaConfig, HaHttpError
from integrations.loxone_adapter import LoxoneAdapter, LoxoneAdapterError, LoxoneConfig
from integrations.loxone_client import LOXONE_EPOCH_TO_UNIX  # noqa: F401
from integrations.loxone_live_power import LiveFlexPowerResult  # noqa: F401
from integrations.openems_adapter import OpenemsAdapter, OpenemsConfig, OpenemsHttpError
from runtime_store.persist_paths import runtime_path
from settings.ev_power import ev_nominal_power_conversion, kw_to_ampere

logger = logging.getLogger(__name__)

WRITE_ERROR_FILENAME = "ehal_write_error.json"

_openems_adapter: OpenemsAdapter | None = None
_ha_adapter: HaAdapter | None = None
_loxone_adapter: LoxoneAdapter | None = None
_soc_missing_warned: set[str] = set()


class _EhalNetworkAdapter(Protocol):
    def read_telemetry(self) -> dict[str, Any]: ...

    def write_setpoints(self, setpoint: dict[str, Any], **kwargs: Any) -> EhalWriteError | None: ...

    def capabilities(self) -> dict[str, Any]: ...

    @property
    def cfg(self) -> Any: ...


def is_openems_backend() -> bool:
    return str(config.get("EHAL_BACKEND") or "").strip().lower() == "openems"


def is_ha_backend() -> bool:
    return str(config.get("EHAL_BACKEND") or "").strip().lower() == "ha"


def is_ha_weg_b_transport() -> bool:
    from runtime_store.ehal_setup import HA_TRANSPORT_WEG_B

    return (
        is_ha_backend()
        and str(config.get("EHAL_HA_TRANSPORT") or "").strip().lower()
        == HA_TRANSPORT_WEG_B
    )


def is_loxone_backend() -> bool:
    backend = str(config.get("EHAL_BACKEND") or "").strip().lower()
    return backend in ("", "loxone")


def is_ehal_network_backend() -> bool:
    """True for OpenEMS/HA only (skips Loxone flex / Huawei extras write path)."""
    return is_openems_backend() or is_ha_backend()


def write_error_path() -> str:
    return runtime_path(WRITE_ERROR_FILENAME)


def persist_write_error(error: EhalWriteError | None) -> None:
    path = write_error_path()
    if error is None:
        clear_write_error()
        return
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(dict(error), handle, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def clear_write_error() -> None:
    path = write_error_path()
    if os.path.isfile(path):
        try:
            os.remove(path)
        except OSError as exc:
            logger.warning("Could not clear EHAL write error file: %s", exc)


def load_write_error() -> EhalWriteError | None:
    path = write_error_path()
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
        return validate_write_error(payload)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        logger.warning("Invalid EHAL write error file %s: %s", path, exc)
        return None


def _plant_from_house_profiles() -> dict:
    try:
        from integrations.pv_attribution import load_house_for_attribution

        house = load_house_for_attribution()
        plant = house.get("plant") if isinstance(house, dict) else None
        return plant if isinstance(plant, dict) else {}
    except Exception:  # noqa: BLE001 — derive must stay usable in tests
        return {}


def derive_sens_power_consumers_w(
    telemetry: dict[str, Any],
    *,
    plant: dict | None = None,
) -> float:
    """House load W: mapped value if present, else PV + grid + ESS with P2 tolerance."""
    from integrations.plant_balance import (
        balance_tolerances_from_plant,
        derive_sens_power_consumers_w as derive_balanced,
    )

    plant_map = plant if isinstance(plant, dict) else _plant_from_house_profiles()
    pct, watts = balance_tolerances_from_plant(plant_map)
    return derive_balanced(
        telemetry, tolerance_pct=pct, tolerance_w=watts
    )


def with_derived_sens_power_consumers(
    telemetry: dict[str, Any],
    *,
    plant: dict | None = None,
) -> dict[str, Any]:
    """Return a copy with sens_power_consumers filled when missing/null."""
    out = dict(telemetry)
    if out.get("sens_power_consumers") is None:
        out["sens_power_consumers"] = derive_sens_power_consumers_w(
            out, plant=plant
        )
    return out


def collect_scoped_pv_live_w() -> dict[str, float]:
    """Mapped ``inv.*.sens_inv_power_pv`` / ``pv.*.sens_pv_production_active`` live W."""
    from integrations.pv_attribution import (
        collect_scoped_pv_live_from_bindings,
        load_components_for_attribution,
        read_scoped_pv_ha,
        read_scoped_pv_loxone,
    )

    components = load_components_for_attribution()
    backend = str(config.get("EHAL_BACKEND") or "loxone").strip().lower()
    if backend == "ha":
        return collect_scoped_pv_live_from_bindings(
            components, read_value=read_scoped_pv_ha
        )
    if backend == "loxone":
        return collect_scoped_pv_live_from_bindings(
            components, read_value=read_scoped_pv_loxone
        )
    return {}


def with_live_pv_attribution(telemetry: dict[str, Any]) -> dict[str, Any]:
    """Fill plant PV from Σ grid-tied inv PV · η_inv when plant is missing.

    Also derives missing ``inv.*.sens_inv_power_pv`` from complete per-PV maps.
    Fail loud on partial coverage when plant must be derived.
    """
    from integrations.plant_balance import pv_covers_all_inverters_from_plant
    from integrations.pv_attribution import (
        load_components_for_attribution,
        load_house_for_attribution,
        with_attributed_plant_pv,
    )

    house = load_house_for_attribution()
    plant = house.get("plant") if isinstance(house, dict) else {}
    components = load_components_for_attribution()
    inverters = list(components.get("inverters") or [])
    pv_systems = list(components.get("pv_systems") or [])
    scoped = collect_scoped_pv_live_w()
    # Prefer values already on telemetry (tests / adapters) over fresh reads.
    for key, value in telemetry.items():
        key_s = str(key)
        if (
            key_s.startswith("inv.") and key_s.endswith(".sens_inv_power_pv")
        ) or (
            key_s.startswith("pv.") and key_s.endswith(".sens_pv_production_active")
        ):
            if value is not None:
                scoped[key_s] = max(0.0, float(value))
    out = with_attributed_plant_pv(
        telemetry,
        scoped_live=scoped,
        inverters=inverters,
        pv_systems=pv_systems,
        pv_covers_all_inverters=pv_covers_all_inverters_from_plant(
            plant if isinstance(plant, dict) else {}
        ),
    )
    if out.get("sens_pv_production_active") is None:
        raise ValueError(
            "sens_pv_production_active missing after live PV attribution "
            "(map plant PV or complete grid-tied inv/pv coverage)."
        )
    return out


def prepare_live_telemetry(telemetry: dict[str, Any]) -> dict[str, Any]:
    """Post-read: PV attribution then house-load derive."""
    return with_derived_sens_power_consumers(with_live_pv_attribution(telemetry))


def get_openems_adapter() -> OpenemsAdapter:
    global _openems_adapter
    base_url = str(config.get("EHAL_OPENEMS_BASE_URL") or "").strip()
    if not base_url:
        raise ValueError(
            "ehal.backend=openems requires ehal.openems.base_url "
            "(EHAL_OPENEMS_BASE_URL)."
        )
    cfg = OpenemsConfig(
        base_url=base_url,
        username=str(config.get("EHAL_OPENEMS_USERNAME") or "x"),
        password=str(config.get("EHAL_OPENEMS_PASSWORD") or "admin"),
        adapter_id=str(config.get("EHAL_ADAPTER_ID") or "openems-lab"),
        ess_component=str(config.get("EHAL_OPENEMS_ESS_COMPONENT") or "ess0"),
        evcs_component=str(config.get("EHAL_OPENEMS_EVCS_COMPONENT") or "evcs0"),
        timeout_sec=float(config.get("GLOBAL_TIMEOUT") or 10),
    )
    if _openems_adapter is not None and _openems_adapter.cfg != cfg:
        _openems_adapter = None
    if _openems_adapter is None:
        _openems_adapter = OpenemsAdapter(cfg)
    return _openems_adapter


def get_ha_adapter() -> HaAdapter:
    global _ha_adapter
    from house_config.ha_ehal_bindings import (
        aggregate_ha_entities,
        load_house_profiles_for_ha,
    )
    from integrations.ha_supervisor import resolve_ha_base_url, resolve_ha_token

    base_url = resolve_ha_base_url(str(config.get("EHAL_HA_BASE_URL") or ""))
    token = resolve_ha_token(str(config.get("EHAL_HA_TOKEN") or ""))
    if not base_url:
        raise ValueError(
            "ehal.backend=ha requires EHAL_HA_BASE_URL in config/.env "
            "(or Supervisor Core URL in the Home Assistant add-on)."
        )
    if not token:
        raise ValueError(
            "ehal.backend=ha requires EHAL_HA_TOKEN in config/.env, "
            "or SUPERVISOR_TOKEN when running as the Home Assistant add-on."
        )
    house = load_house_profiles_for_ha()
    transport = str(config.get("EHAL_HA_TRANSPORT") or "pull").strip().lower()
    aggregated = aggregate_ha_entities(house, transport=transport)
    if aggregated:
        entities = aggregated
    else:
        legacy = config.get("EHAL_HA_ENTITIES") or {}
        entities = legacy if isinstance(legacy, dict) else {}
    from integrations.ha_push_read import (
        load_house_components_for_ha,
        push_read_qualified_ids,
        setpoint_qualified_ids,
    )

    house_doc, components_doc = load_house_components_for_ha()
    if house is not None and isinstance(house, dict):
        house_doc = house
    push_qids = push_read_qualified_ids(house_doc, components_doc)
    setpoint_qids = setpoint_qualified_ids(house_doc, components_doc)
    sign = config.get("EHAL_HA_SIGN") or {}
    if not isinstance(sign, dict):
        sign = {}
    boolean_invert = config.get("EHAL_HA_BOOLEAN_INVERT") or {}
    if not isinstance(boolean_invert, dict):
        boolean_invert = {}
    ha_ess_force = None
    if isinstance(house, dict):
        plant = house.get("plant")
        if isinstance(plant, dict) and plant.get("ha_ess_force"):
            ha_ess_force = plant.get("ha_ess_force")
    cfg = HaConfig(
        base_url=base_url,
        token=token,
        adapter_id=str(config.get("EHAL_ADAPTER_ID") or "earnie-hems"),
        entities=canonicalize_ha_entity_keys(
            {str(k): str(v) for k, v in entities.items()},
            keep_empty=str(transport).strip().lower() == "weg_b",
        ),
        sign=canonicalize_ha_entity_keys({str(k): str(v) for k, v in sign.items()}),
        boolean_invert=canonicalize_ha_entity_keys(
            {str(k): str(v) for k, v in boolean_invert.items()}
        ),
        timeout_sec=float(config.get("GLOBAL_TIMEOUT") or 10),
        ha_ess_force=ha_ess_force if isinstance(ha_ess_force, dict) else None,
        transport=transport,
        push_read_qids=push_qids,
        setpoint_qids=setpoint_qids,
    )
    if _ha_adapter is not None and _ha_adapter.cfg != cfg:
        _ha_adapter = None
    if _ha_adapter is None:
        _ha_adapter = HaAdapter(cfg)
    return _ha_adapter


def _standby_source_select_merker() -> str:
    """Entity-scoped Quellenwahl Merker from the physical standby_backup battery."""
    from ehal.ess_fields import binding_address
    from house_config.powerstation import (
        BACKING_PHYSICAL,
        ROLE_STANDBY_BACKUP,
        ehal_mappable_batteries,
        is_powerstation,
    )

    try:
        from house_config.components_store import load_components_document
        from runtime_store.persist_paths import resolve_components_json_path

        path = resolve_components_json_path()
        if not path:
            return ""
        doc = load_components_document(path)
        raw = doc.get("batteries") if isinstance(doc, dict) else []
    except Exception:  # noqa: BLE001
        return ""
    for bat in ehal_mappable_batteries(raw if isinstance(raw, list) else []):
        if not is_powerstation(bat):
            continue
        if str(bat.get("role") or "") != ROLE_STANDBY_BACKUP:
            continue
        if str(bat.get("backing") or "") != BACKING_PHYSICAL:
            continue
        bid = str(bat.get("id") or "").strip()
        if not bid:
            continue
        bindings = bat.get("ehal_bindings")
        addr = binding_address(
            bindings if isinstance(bindings, dict) else {},
            bid,
            "set_ess_source_select",
        )
        if addr:
            return addr
    return ""


def get_loxone_adapter() -> LoxoneAdapter:
    global _loxone_adapter
    from house_config.ehal_bindings import resolve_plant_binding
    from house_config.ess_bindings import resolve_primary_ess_binding
    from optimizer.live_export_limit import load_house_doc

    ev = _first_ev_loxone_bindings()
    house = load_house_doc()
    export_out = resolve_plant_binding(house, "set_grid_export_power_limit")
    # Capability / residual flat write_setpoints: entity-scoped standby Merker only.
    ess_source_select = _standby_source_select_merker()
    cfg = LoxoneConfig(
        adapter_id=str(config.get("EHAL_ADAPTER_ID") or "loxone-home"),
        charge_power_name=str(
            resolve_primary_ess_binding("set_ess_charge_power_limit") or ""
        ),
        discharge_power_name=str(
            resolve_primary_ess_binding("set_ess_discharge_power_limit") or ""
        ),
        active_power_name=str(
            resolve_primary_ess_binding("set_ess_active_power") or ""
        ),
        control_cmd_name=str(resolve_primary_ess_binding("set_ess_mode") or ""),
        evcs_max_current_name=str(ev.get("evcs_max_current_name") or ""),
        evcs_mode_name=str(ev.get("evcs_mode_name") or ""),
        grid_export_limit_out_name=str(export_out or ""),
        ess_source_select_name=str(ess_source_select or ""),
        timeout_sec=float(config.get("GLOBAL_TIMEOUT") or 10),
    )
    if _loxone_adapter is not None and _loxone_adapter.cfg != cfg:
        _loxone_adapter = None
    if _loxone_adapter is None:
        _loxone_adapter = LoxoneAdapter(cfg)
    return _loxone_adapter


def get_network_adapter() -> _EhalNetworkAdapter:
    """OpenEMS or HA adapter (raises if Loxone backend)."""
    if is_ha_backend():
        return get_ha_adapter()
    if is_openems_backend():
        return get_openems_adapter()
    raise ValueError("get_network_adapter requires ehal.backend openems or ha")


def get_adapter() -> _EhalNetworkAdapter:
    """Active EHAL adapter including Loxone (default production path)."""
    if is_ha_backend():
        return get_ha_adapter()
    if is_openems_backend():
        return get_openems_adapter()
    return get_loxone_adapter()


def reset_adapter_cache() -> None:
    """Test helper: drop cached adapter instances."""
    global _openems_adapter, _ha_adapter, _loxone_adapter
    _openems_adapter = None
    _ha_adapter = None
    _loxone_adapter = None


def read_ess_soc() -> float | None:
    """Primary house-battery SoC (%) via entity-scoped path only."""
    from house_config.powerstation import primary_house_battery

    try:
        by_id = read_ess_soc_by_id()
    except (
        OpenemsHttpError,
        HaHttpError,
        LoxoneAdapterError,
        ValueError,
        OSError,
    ) as exc:
        logger.error("EHAL SoC read failed: %s", exc)
        return None
    batteries = _mappable_batteries_for_soc()
    primary = primary_house_battery(batteries)
    primary_id = str((primary or {}).get("id") or "").strip()
    if primary_id and primary_id in by_id:
        return float(by_id[primary_id])
    if by_id:
        # Single mapped SoC when primary id is unknown / empty
        return float(next(iter(by_id.values())))
    if primary_id:
        logger.error(
            "EHAL SoC read failed: missing ess.%s.sens_ess_soc for primary "
            "battery (map SoC on that battery in EHAL-Com / "
            "batteries[].ehal_bindings, or ensure Live delivers it)",
            primary_id,
        )
    else:
        logger.error(
            "EHAL SoC read failed: no primary house battery id and no "
            "ess.*.sens_ess_soc values available"
        )
    return None


def _soc_address_for_battery(bat: dict) -> str:
    """Resolve SoC read key: Loxone uses qualified ID; HA uses binding address."""
    from ehal.ess_fields import binding_address
    from ehal.qualified_ids import qualified_battery_id

    ess_id = str(bat.get("id") or "").strip()
    if not ess_id:
        return ""
    if is_loxone_backend() or not is_ehal_network_backend():
        return qualified_battery_id(ess_id, "sens_ess_soc")
    if is_openems_backend():
        bindings = bat.get("ehal_bindings")
        if isinstance(bindings, dict):
            addr = binding_address(bindings, ess_id, "sens_ess_soc")
            if addr:
                return addr
        # Primary OpenEMS channel from adapter config (no plant telemetry key).
        from house_config.powerstation import primary_house_battery

        primary = primary_house_battery(_mappable_batteries_for_soc())
        if primary and str(primary.get("id") or "").strip() == ess_id:
            adapter = get_openems_adapter()
            return f"{adapter.cfg.ess_component}/Soc"
        return ""
    bindings = bat.get("ehal_bindings")
    if not isinstance(bindings, dict):
        return ""
    return str(binding_address(bindings, ess_id, "sens_ess_soc") or "").strip()


def _read_soc_from_address(address: str) -> float | None:
    addr = str(address or "").strip()
    if not addr:
        return None
    try:
        if is_openems_backend():
            parts = _openems_channel_parts(addr)
            if parts is None:
                return None
            component, channel = parts
            adapter = get_openems_adapter()
            raw = adapter.read_channel(component, channel)
            if raw is None and channel == "Soc":
                raw = adapter.read_channel("_sum", "EssSoc")
            return None if raw is None else float(raw)
        if is_ha_backend():
            adapter = get_ha_adapter()
            entities = getattr(adapter.cfg, "entities", {}) or {}
            entity_id = str(entities.get(addr) or addr).strip()
            if not entity_id:
                return None
            payload = adapter.read_state(entity_id)
            raw = payload.get("state")
            return None if raw is None else float(raw)
        if is_loxone_backend() or not is_ehal_network_backend():
            from ehal.field_registry import apply_loxone_read, loxone_spec

            raw = loxone_client.fetch_loxone_generic_value(addr)
            spec = loxone_spec("sens_ess_soc")
            if spec is not None:
                return apply_loxone_read(raw, spec)
            return None if raw is None else float(raw)
    except (
        OpenemsHttpError,
        HaHttpError,
        LoxoneAdapterError,
        TypeError,
        ValueError,
        OSError,
        KeyError,
    ) as exc:
        logger.debug("Per-ESS SoC read failed for %s: %s", addr, exc)
        return None
    return None


def _mappable_batteries_for_soc() -> list[dict]:
    """House + physical PS from components; fallback to planning battery list."""
    try:
        from house_config.components_store import load_components_document
        from house_config.powerstation import ehal_mappable_batteries
        from runtime_store.persist_paths import resolve_components_json_path

        path = resolve_components_json_path()
        if path:
            doc = load_components_document(path)
            raw = doc.get("batteries") if isinstance(doc, dict) else []
            mapped = ehal_mappable_batteries(raw if isinstance(raw, list) else [])
            if mapped:
                return mapped
    except Exception as exc:  # noqa: BLE001
        logger.debug("SoC battery list from components failed: %s", exc)
    get_list = getattr(config, "get_battery_params_list", None)
    batteries = get_list() if callable(get_list) else []
    return [b for b in (batteries or []) if isinstance(b, dict)]


def _warn_soc_missing_once(ess_id: str) -> None:
    if ess_id in _soc_missing_warned:
        return
    _soc_missing_warned.add(ess_id)
    logger.warning(
        "ESS SoC missing for %s — refuse planning (no primary SoC fallback)",
        ess_id,
    )


def filter_planning_batteries_with_soc(
    battery_params: list | dict,
    current_soc_by_id: dict[str, float] | None,
) -> list | dict:
    """Drop multi-ESS house batteries without an own SoC from this cycle's plan."""
    if not isinstance(battery_params, list):
        return battery_params
    soc_map = current_soc_by_id or {}
    kept: list[dict] = []
    for bat in battery_params:
        if not isinstance(bat, dict):
            continue
        ess_id = str(bat.get("id") or "").strip()
        if ess_id and ess_id not in soc_map:
            logger.warning(
                "Dropping ESS %s from this cycle — no own SoC",
                ess_id,
            )
            continue
        kept.append(bat)
    return kept if kept else battery_params


def read_ess_soc_by_id() -> dict[str, float]:
    """SoC (%) per mappable battery id; omit when own SoC missing.

    Each battery needs its own ``ess.{{id}}.sens_ess_soc`` (or OpenEMS primary
    channel for the primary house battery). No plant-flat SoC alias.
    """
    batteries = _mappable_batteries_for_soc()
    out: dict[str, float] = {}
    for bat in batteries:
        ess_id = str(bat.get("id") or "").strip()
        if not ess_id:
            continue
        soc = _read_soc_from_address(_soc_address_for_battery(bat))
        if soc is None:
            _warn_soc_missing_once(ess_id)
            continue
        out[ess_id] = float(soc)
    return out


def read_live_power_kw() -> dict[str, float] | None:
    """Return Live power dict (kW): grid ``+`` = import, battery ``+`` = discharge."""
    try:
        telemetry = prepare_live_telemetry(get_adapter().read_telemetry())
    except (
        OpenemsHttpError,
        HaHttpError,
        LoxoneAdapterError,
        ValueError,
        OSError,
    ) as exc:
        logger.error("EHAL live power read failed: %s", exc)
        return None

    pv = max(0.0, float(telemetry["sens_pv_production_active"]) / 1000.0)
    grid = float(telemetry["sens_grid_power_active"]) / 1000.0
    ess_w = telemetry.get("sens_ess_power")
    if ess_w is None:
        battery = 0.0
    else:
        # EHAL sens_ess_power and Live dict share the sign: + = discharge
        battery = float(ess_w) / 1000.0
    house = pv + battery + grid
    return {
        "pv": round(pv, 2),
        "house": round(house, 2),
        "battery": round(battery, 2),
        "grid": round(grid, 2),
    }


_OMIT_EXPORT_CAP = object()


def write_ess_setpoints_from_control(
    mode: int,
    target_power_kw: float,
    max_power_kw: float | None = None,
    *,
    max_charge_power_kw: float | None = None,
    max_discharge_power_kw: float | None = None,
    export_cap_kw: float | None | object = _OMIT_EXPORT_CAP,
    telemetry: dict[str, Any] | None = None,
) -> tuple[EhalWriteError | None, list[dict[str, Any]]]:
    """Map optimizer mode/power to EHAL Design C1 ESS setpoints.

    When ``export_cap_kw`` is passed (including ``None`` = unconstrained), also write
    ``set_grid_export_power_limit`` (W magnitude; plant export maximum = PV kWp + force
    discharge kW when unconstrained, see ``live_unconstrained_export_kw``).
    """
    from house_config.battery_control import (
        BATTERY_CONTROL_LIMITS_ONLY,
        BATTERY_CONTROL_READ_ONLY,
        control_from_battery_params,
    )
    from optimizer.export_power_limit import export_limit_setpoint_w
    from optimizer.live_export_limit import live_unconstrained_export_kw
    from settings.ess_limits_resolve import apply_effective_ess_limits

    battery_params = apply_effective_ess_limits(
        config.get_battery_params(), telemetry=telemetry
    )
    control = control_from_battery_params(battery_params)
    if control == BATTERY_CONTROL_READ_ONLY:
        return None, []

    if max_charge_power_kw is None and max_discharge_power_kw is None and max_power_kw is not None:
        max_charge_power_kw = float(max_power_kw)
        max_discharge_power_kw = float(max_power_kw)
    if max_charge_power_kw is None:
        max_charge_power_kw = float(battery_params.get("max_charge_power_kw") or 0.0)
    if max_discharge_power_kw is None:
        max_discharge_power_kw = float(
            battery_params.get("max_discharge_power_kw") or 0.0
        )
    active_kw, charge_kw, discharge_kw, control_cmd = map_ess_setpoints(
        mode,
        target_power_kw,
        float(max_charge_power_kw),
        float(max_discharge_power_kw),
    )
    if control == BATTERY_CONTROL_LIMITS_ONLY:
        active_kw = None
        if mode in (1, 3):
            mode = 0
            active_kw, charge_kw, discharge_kw, control_cmd = map_ess_setpoints(
                0,
                0.0,
                float(max_charge_power_kw),
                float(max_discharge_power_kw),
            )
    adapter = get_network_adapter()
    ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    charge_w = max(0.0, float(charge_kw) * 1000.0)
    discharge_w = max(0.0, float(discharge_kw) * 1000.0)
    setpoint: dict[str, Any] = {
        "schema_version": EHAL_SCHEMA_VERSION,
        "ts": ts,
        "adapter_id": adapter.cfg.adapter_id,
        "set_ess_charge_power_limit": charge_w,
        "set_ess_discharge_power_limit": discharge_w,
        "set_ess_mode": control_cmd,
    }
    record_fields: dict[str, float] = {
        "set_ess_charge_power_limit": charge_w,
        "set_ess_discharge_power_limit": discharge_w,
        "set_ess_mode": float(control_cmd),
    }
    if active_kw is not None:
        active_w = float(active_kw) * 1000.0
        setpoint["set_ess_active_power"] = active_w
        record_fields["set_ess_active_power"] = active_w
    if export_cap_kw is not _OMIT_EXPORT_CAP:
        cap = None if export_cap_kw is None else float(export_cap_kw)  # type: ignore[arg-type]
        limit_w = export_limit_setpoint_w(
            cap, unconstrained_kw=live_unconstrained_export_kw()
        )
        setpoint["set_grid_export_power_limit"] = limit_w
        record_fields["set_grid_export_power_limit"] = limit_w
    error = adapter.write_setpoints(setpoint)
    if error is not None:
        persist_write_error(error)
    records = build_ehal_write_records(
        record_fields,
        written_at=ts,
        error=error,
        skipped=_last_skipped(adapter),
    )
    return error, records


def _planning_inverters() -> list[dict]:
    raw = getattr(config, "_planning_inverters", None)
    if raw is None and hasattr(config, "get"):
        try:
            raw = config.get("_planning_inverters", None)
        except TypeError:
            raw = None
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _planning_pv_systems() -> list[dict]:
    raw = getattr(config, "_planning_pv_systems", None)
    if raw is None and hasattr(config, "get"):
        try:
            raw = config.get("_planning_pv_systems", None)
        except TypeError:
            raw = None
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _openems_channel_parts(binding: str) -> tuple[str, str] | None:
    text = str(binding or "").strip()
    if "/" not in text:
        return None
    component, channel = text.split("/", 1)
    component = component.strip()
    channel = channel.strip()
    if not component or not channel:
        return None
    return component, channel


def _mapped_inv_limit_ids() -> set[str]:
    """Inverter ids with a non-empty ``set_inv_ac_power_limit`` binding."""
    from ehal.inverter_fields import binding_address, inv_field

    mapped: set[str] = set()
    for inv in _planning_inverters():
        inv_id = str(inv.get("id") or "").strip()
        if not inv_id:
            continue
        bindings = inv.get("ehal_bindings")
        bind_map = bindings if isinstance(bindings, dict) else {}
        addr = binding_address(bind_map, inv_id, "set_inv_ac_power_limit")
        field = inv_field(inv_id, "set_inv_ac_power_limit")
        if not addr and field in bind_map:
            addr = str(bind_map.get(field) or "").strip()
        if not addr:
            continue
        if is_openems_backend() and _openems_channel_parts(addr) is None:
            continue
        mapped.add(inv_id)
    return mapped


def _battery_params_for_inv_limits() -> list[dict]:
    get_list = getattr(config, "get_battery_params_list", None)
    if callable(get_list):
        return [b for b in (get_list() or []) if isinstance(b, dict)]
    bat = config.get_battery_params()
    return [bat] if isinstance(bat, dict) else []


def _inv_limit_fields_w(
    *,
    plant_curtail_kw: float,
    matrix_row: dict[str, Any] | None,
    milp_plan: dict[str, Any] | None,
) -> dict[str, float]:
    """Qualified ``inv.{id}.set_inv_ac_power_limit`` → EHAL W for writable inverters."""
    from ehal.inverter_fields import inv_field
    from optimizer.inv_ac_power_limit import (
        allocate_inv_ac_limits_kw,
        eligible_inv_limit_ids,
        force_discharge_kw_by_inverter,
        inv_ac_limit_setpoint_w,
        planned_discharge_kw_by_inverter,
        pv_kwp_by_inverter,
    )

    inverters = _planning_inverters()
    if not inverters:
        return {}
    writable = eligible_inv_limit_ids(inverters, mapped_ids=_mapped_inv_limit_ids())
    if not writable:
        return {}
    pv_systems = _planning_pv_systems()
    batteries = _battery_params_for_inv_limits()
    limits_kw = allocate_inv_ac_limits_kw(
        inverters=inverters,
        writable_ids=writable,
        plant_curtail_kw=float(plant_curtail_kw or 0.0),
        matrix_row=matrix_row if isinstance(matrix_row, dict) else {},
        pv_systems=pv_systems,
        pv_kwp_by_inverter=pv_kwp_by_inverter(pv_systems),
        force_discharge_kw_by_inverter=force_discharge_kw_by_inverter(batteries),
        planned_discharge_by_inverter=planned_discharge_kw_by_inverter(
            milp_plan, battery_params=batteries
        ),
    )
    return {
        inv_field(inv_id, "set_inv_ac_power_limit"): inv_ac_limit_setpoint_w(limit_kw)
        for inv_id, limit_kw in limits_kw.items()
    }


def write_inv_ac_limits_from_plan(
    *,
    plant_curtail_kw: float = 0.0,
    matrix_row: dict[str, Any] | None = None,
    milp_plan: dict[str, Any] | None = None,
) -> tuple[EhalWriteError | None, list[dict[str, Any]]]:
    """Write per-inverter AC limits (P5 curtail-only sticky loop)."""
    fields_w = _inv_limit_fields_w(
        plant_curtail_kw=plant_curtail_kw,
        matrix_row=matrix_row,
        milp_plan=milp_plan,
    )
    if not fields_w:
        return None, []

    ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    if is_ehal_network_backend():
        adapter = get_network_adapter()
        writer = getattr(adapter, "write_mapped_fields", None)
        if not callable(writer):
            logger.warning(
                "EHAL: adapter has no write_mapped_fields — skip inverter AC limits"
            )
            return None, []
        error = writer(fields_w)
        if error is not None:
            persist_write_error(error)
        return error, build_ehal_write_records(
            fields_w,
            written_at=ts,
            error=error,
            skipped=_last_skipped(adapter),
        )

    from integrations.loxone_writes import write_inv_ac_power_limits

    records = write_inv_ac_power_limits(fields_w)
    rows = [
        {
            "field": getattr(row, "io_name", ""),
            "value": float(getattr(row, "value", 0.0) or 0.0),
            "success": bool(getattr(row, "success", False)),
            "written_at": str(getattr(row, "written_at", ts) or ts),
            "message": "",
        }
        for row in records
    ]
    return None, rows


def push_safe_setpoints_on_startup() -> None:
    """Force-write safe ESS/flex setpoints once at daemon start (before first optimize).

    Does not update ``optimizer_run_state`` / ``loxone_sent``. Soft-fail: log only.
    Skip via ``EARNIE_SKIP_SAFE_SETPOINTS_ON_START=1`` or silent mode.
    """
    from runtime_store.env_vars import is_truthy

    if is_truthy("SKIP_SAFE_SETPOINTS_ON_START"):
        logger.info(
            "Safe setpoint startup push skipped (EARNIE_SKIP_SAFE_SETPOINTS_ON_START)."
        )
        return
    if config.is_loxone_silent_mode():
        logger.info("Silent-Modus: Safe setpoint startup push übersprungen.")
        return
    if is_ehal_network_backend():
        _push_safe_setpoints_network()
    else:
        _push_safe_setpoints_loxone()


def _push_safe_setpoints_network() -> None:
    backend = "HA" if is_ha_backend() else "OpenEMS"
    logger.info(
        "Startup: sende sichere EHAL-Sollwerte (ESS Automatik, EVCS 0 A) an %s...",
        backend,
    )
    err_ess, _ess_records = write_ess_setpoints_from_control(0, 0.0)
    err_evcs, _evcs_records = write_evcs_max_current_from_consumers({})
    err_inv, _inv_records = write_inv_ac_limits_from_plan(plant_curtail_kw=0.0)
    if err_ess is None and err_evcs is None and err_inv is None:
        clear_write_error()
        logger.info("Startup: sichere EHAL-Sollwerte an %s gesendet.", backend)
        return
    parts: list[str] = []
    if err_ess is not None:
        parts.append(str(err_ess.get("message") or "ESS"))
    if err_evcs is not None:
        parts.append(str(err_evcs.get("message") or "EVCS"))
    if err_inv is not None:
        parts.append(str(err_inv.get("message") or "INV"))
    logger.error(
        "Startup: sichere EHAL-Sollwerte an %s teilweise fehlgeschlagen: %s",
        backend,
        "; ".join(parts),
    )


def _push_safe_setpoints_loxone() -> None:
    logger.info(
        "Startup: sende sichere Loxone-Sollwerte "
        "(ESS Automatik, Freigabe/Sollwerte aus)..."
    )
    huawei = write_huawei_modbus_states(0, 0.0, 0.0)
    flex = write_flexible_consumer_states({}, None, None)
    _inv_err, inv_rows = write_inv_ac_limits_from_plan(plant_curtail_kw=0.0)
    failed = [
        row
        for row in (huawei + flex)
        if not getattr(row, "success", True)
    ]
    failed_inv = [row for row in inv_rows if not row.get("success")]
    if not failed and not failed_inv:
        logger.info("Startup: sichere Loxone-Sollwerte gesendet.")
        return
    logger.error(
        "Startup: sichere Loxone-Sollwerte teilweise fehlgeschlagen (%s Feld(er)).",
        len(failed) + len(failed_inv),
    )


def write_evcs_max_current_from_consumers(
    consumer_powers: dict[str, float],
    charging_contexts: dict[str, dict] | None = None,
) -> tuple[EhalWriteError | None, list[dict[str, Any]]]:
    """Write set_evcs_max_current from first EV consumer planned power (kW→A)."""
    consumer = _first_ev_consumer()
    if consumer is None:
        logger.info("EHAL: no EV consumer configured — skip EVCS write")
        return None, []

    cid = consumer["id"]
    planned_kw = max(0.0, float(consumer_powers.get(cid, 0.0) or 0.0))
    ctx = (charging_contexts or {}).get(cid)
    if ctx is not None and not ctx.get("active", True):
        planned_kw = 0.0
    if ctx is not None and ctx.get("anticipated") and not ctx.get("plugged_in"):
        planned_kw = 0.0

    voltage_v, phases = ev_nominal_power_conversion(consumer)
    amps = kw_to_ampere(planned_kw, voltage_v=voltage_v, phases=phases)
    adapter = get_network_adapter()
    if not adapter.capabilities()["supports_evcs_current"]:
        logger.info("EHAL: supports_evcs_current=false — skip EVCS write")
        return None, []

    ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    amps_out = max(0.0, amps)
    setpoint = {
        "schema_version": EHAL_SCHEMA_VERSION,
        "ts": ts,
        "adapter_id": adapter.cfg.adapter_id,
        "set_evcs_max_current": amps_out,
    }
    error = adapter.write_setpoints(
        setpoint, evcs_voltage_v=voltage_v, evcs_phases=phases
    )
    if error is not None:
        persist_write_error(error)
    records = build_ehal_write_records(
        {"set_evcs_max_current": amps_out},
        written_at=ts,
        error=error,
        skipped=_last_skipped(adapter),
    )
    return error, records


SKIPPED_MESSAGE = "Übersprungen: Funktion nicht verfügbar (Mapping unvollständig)"


def _last_skipped(adapter: Any) -> list[str]:
    getter = getattr(adapter, "last_skipped_fields", None)
    return list(getter()) if callable(getter) else []


def build_ehal_write_records(
    fields: dict[str, float],
    *,
    written_at: str,
    error: EhalWriteError | None,
    skipped: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Compact write trace rows for optimizer_run_state.ehal_writes."""
    failed = set(error.get("failed_fields") or []) if error else set()
    message = str(error.get("message") or "") if error else ""
    skipped_set = set(skipped or [])
    rows: list[dict[str, Any]] = []
    for field, value in fields.items():
        if field in skipped_set:
            rows.append(
                {
                    "field": field,
                    "value": value,
                    "success": False,
                    "skipped": True,
                    "written_at": written_at,
                    "message": SKIPPED_MESSAGE,
                }
            )
            continue
        if error is None:
            ok = True
        elif failed:
            ok = field not in failed
        else:
            ok = False
        rows.append(
            {
                "field": field,
                "value": value,
                "success": ok,
                "written_at": written_at,
                "message": "" if ok else message,
            }
        )
    return rows


def _first_ev_consumer() -> dict | None:
    for consumer in config.get_flexible_consumers():
        if consumer.get("type") == "ev":
            return consumer
        sched = consumer.get("charging_schedule")
        if sched and sched.get("enabled"):
            return consumer
    return None


def _first_ev_loxone_bindings() -> dict[str, str]:
    """EV write markers from first EV consumer ``ehal_bindings`` (entity-scoped only)."""
    from settings.ehal_marker_resolve import (
        marker_set_evcs_max_current,
        marker_set_evcs_mode,
    )

    consumer = _first_ev_consumer()
    if consumer is None:
        return {}
    return {
        "evcs_max_current_name": marker_set_evcs_max_current(consumer),
        "evcs_mode_name": marker_set_evcs_mode(consumer),
    }
