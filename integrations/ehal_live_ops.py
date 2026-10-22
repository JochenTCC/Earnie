"""Named live I/O ops for the ehal_live façade (SH-backend concentration).

Callers outside ``integrations/`` must use ``integrations.ehal_live`` re-exports,
not ``loxone_client`` / ``loxone_writes`` / ``loxone_live_power`` directly.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from integrations.loxone_comm_trace import LoxoneWriteRecord
from integrations.loxone_writes import _OMIT_EXPORT_CAP as OMIT_EXPORT_CAP

ABSENT_EHAL_FIELD = "sens_absent_mode"


def read_generic_value(address: str) -> Optional[float]:
    """Numeric live read from the Loxone VO push inbox (no Merker poll).

    Returns ``None`` when unbound/missing — never invents ``0``. Prefer
    adapter ``read_telemetry`` / field-specific ops on HA/OpenEMS; those
    backends have no Merker address space for this helper.
    """
    from integrations import loxone_client

    return loxone_client.fetch_loxone_generic_value(address)


def read_optional_temp_c(io_name: str) -> float | None:
    """Optional temperature °C from a live address (Loxone push)."""
    name = str(io_name or "").strip()
    if not name:
        return None
    return read_generic_value(name)


def resolve_consumer_live_power_kw(
    consumer: dict,
    *,
    fallback_kw: float | None = None,
) -> float | None:
    from integrations.loxone_live_power import resolve_consumer_live_power_kw as _impl

    return _impl(consumer, fallback_kw=fallback_kw)


def consumers_with_live_nominal_power(consumers: list | None = None) -> list:
    from integrations.loxone_live_power import consumers_with_live_nominal_power as _impl

    return _impl(consumers)


def resolve_flexible_consumers_live_power(
    fallbacks: dict[str, float] | None = None,
    consumers: list | None = None,
    *,
    filter_contexts: dict[str, dict] | None = None,
    slot_datetime: datetime | None = None,
):
    from integrations.loxone_live_power import (
        resolve_flexible_consumers_live_power as _impl,
    )

    return _impl(
        fallbacks,
        consumers,
        filter_contexts=filter_contexts,
        slot_datetime=slot_datetime,
    )


def fetch_flexible_consumers_live_kw(
    fallbacks: dict[str, float] | None = None,
    consumers: list | None = None,
    *,
    filter_contexts: dict[str, dict] | None = None,
    slot_datetime: datetime | None = None,
) -> dict[str, float]:
    from integrations.loxone_live_power import fetch_flexible_consumers_live_kw as _impl

    return _impl(
        fallbacks,
        consumers,
        filter_contexts=filter_contexts,
        slot_datetime=slot_datetime,
    )


def fetch_live_power() -> dict | None:
    """Plant live power dict from Loxone push meters (legacy plant-flat path)."""
    from integrations.loxone_live_power import fetch_loxone_live_power

    return fetch_loxone_live_power()


def resolve_consumer_battery_capacity_kwh(consumer: dict) -> float | None:
    from integrations.loxone_live_power import (
        resolve_consumer_battery_capacity_kwh as _impl,
    )

    return _impl(consumer)


def resolve_consumer_nominal_power_kw(consumer: dict) -> float:
    from integrations.loxone_live_power import resolve_consumer_nominal_power_kw as _impl

    return _impl(consumer)


def read_consumer_meter_kw(consumer: dict) -> float | None:
    from integrations.loxone_live_power import _read_consumer_meter_kw

    return _read_consumer_meter_kw(consumer)


def house_profile_power_consumers():
    from integrations.loxone_live_power import _house_profile_power_consumers

    return _house_profile_power_consumers()


def write_flexible_consumer_states(
    consumer_powers: dict[str, float],
    charging_contexts: dict[str, dict] | None = None,
    consumer_pv_follow: dict[str, int] | None = None,
) -> list[LoxoneWriteRecord]:
    from integrations.loxone_writes import send_flexible_consumer_states

    return send_flexible_consumer_states(
        consumer_powers, charging_contexts, consumer_pv_follow
    )


def write_flexible_consumer_enables(
    consumer_powers: dict[str, float],
    charging_contexts: dict[str, dict] | None = None,
    consumer_pv_follow: dict[str, int] | None = None,
) -> list[LoxoneWriteRecord]:
    from integrations.loxone_writes import send_flexible_consumer_enables

    return send_flexible_consumer_enables(
        consumer_powers, charging_contexts, consumer_pv_follow
    )


def write_huawei_modbus_states(
    mode: int,
    target_power_kw: float,
    target_soc: float,
    *,
    export_cap_kw: float | None | object = OMIT_EXPORT_CAP,
) -> list[LoxoneWriteRecord]:
    from integrations.loxone_writes import send_huawei_modbus_states

    return send_huawei_modbus_states(
        mode, target_power_kw, target_soc, export_cap_kw=export_cap_kw
    )


def build_sent_loxone_snapshot(
    mode: int,
    target_power_kw: float,
    target_soc: float,
    consumer_powers: dict[str, float],
    charging_contexts: dict[str, dict] | None,
    consumer_pv_follow: dict[str, int] | None = None,
    *,
    export_cap_kw: float | None | object = OMIT_EXPORT_CAP,
) -> dict[str, float]:
    from integrations.loxone_writes import build_sent_loxone_snapshot as _impl

    return _impl(
        mode,
        target_power_kw,
        target_soc,
        consumer_powers,
        charging_contexts,
        consumer_pv_follow,
        export_cap_kw=export_cap_kw,
    )


def publish_setpoint_traced(
    qualified_id: str,
    value: float,
    *,
    io_name: str = "",
) -> LoxoneWriteRecord:
    from integrations.loxone_writes import _publish_setpoint_traced

    return _publish_setpoint_traced(qualified_id, value, io_name=io_name)


def map_ess_setpoints(
    mode: int,
    target_power_kw: float,
    max_charge_power_kw: float,
    max_discharge_power_kw: float | None = None,
) -> tuple[float | None, float, float, int]:
    from integrations.loxone_writes import map_ess_setpoints as _impl

    return _impl(
        mode, target_power_kw, max_charge_power_kw, max_discharge_power_kw
    )


def fetch_ready_by_time(io_name: str) -> str | float | None:
    from integrations import loxone_client

    return loxone_client.fetch_loxone_ready_by_time(io_name)


def fetch_filter_native_start_hour(
    io_name: str,
) -> tuple[float | None, str, str | None]:
    from integrations import loxone_client

    return loxone_client.fetch_filter_native_start_hour(io_name)


def format_ready_by_display(value: str | float) -> str:
    from integrations import loxone_client

    return loxone_client.format_ready_by_display(value)


def fetch_heat_storage_temps(
    consumer: dict,
    *,
    house_doc: dict | None = None,
) -> dict:
    from integrations import loxone_client

    return loxone_client.fetch_heat_storage_temps(consumer, house_doc=house_doc)


def fetch_thermal_readings(
    consumer: dict,
    *,
    house_doc: dict | None = None,
    config_doc: dict | None = None,
) -> dict:
    from integrations import loxone_client

    return loxone_client.fetch_thermal_readings(
        consumer, house_doc=house_doc, config_doc=config_doc
    )


def _split_openems_channel(binding: str) -> tuple[str, str] | None:
    text = str(binding or "").strip()
    if "/" not in text:
        return None
    component, channel = text.split("/", 1)
    component = component.strip()
    channel = channel.strip()
    if not component or not channel:
        return None
    return component, channel


def _read_absent_loxone(binding: str) -> bool | None:
    from integrations.loxone_value_parse import parse_binary_value

    raw = read_generic_value(binding)
    return parse_binary_value(raw)


def _read_absent_ha(binding: str) -> bool | None:
    """Read plant absent mode from the push inbox (Binding P5e)."""
    from integrations.ha_push_read import PushReadError, read_push_ehal_value
    from integrations.loxone_value_parse import parse_binary_value

    del binding  # SB name unused; activation uses qualified EHAL id
    qid = ABSENT_EHAL_FIELD
    sign: dict = {}
    try:
        from integrations.ehal_live import get_ha_adapter

        adapter = get_ha_adapter()
        qid = str((adapter.cfg.push_read_qids or {}).get(ABSENT_EHAL_FIELD) or qid)
        sign = dict(getattr(adapter.cfg, "sign", {}) or {})
    except Exception:
        pass
    try:
        raw = read_push_ehal_value(qid, sign=sign, adapter_field=ABSENT_EHAL_FIELD)
    except PushReadError:
        return None
    return parse_binary_value(raw)


def _read_absent_openems(binding: str) -> bool | None:
    from integrations.ehal_live import get_openems_adapter
    from integrations.loxone_value_parse import parse_binary_value

    parts = _split_openems_channel(binding)
    if parts is None:
        return None
    component, channel = parts
    raw = get_openems_adapter().read_channel(component, channel)
    return parse_binary_value(raw)


def read_absent_mode(house_doc: dict | None = None) -> tuple[bool | None, bool]:
    """Read plant ``sens_absent_mode`` via the active EHAL backend.

    Returns ``(value, bound)`` where ``value`` is True/False/None (read failure)
    and ``bound`` is whether a plant binding is configured.
    """
    from house_config.ehal_bindings import resolve_plant_binding
    from house_config.profiles_store import load_default_house_profiles_doc
    from integrations import ehal_live

    if house_doc is None:
        house_doc = load_default_house_profiles_doc()
    binding = resolve_plant_binding(house_doc, ABSENT_EHAL_FIELD)
    if not binding:
        return None, False
    if ehal_live.is_ha_backend():
        return _read_absent_ha(binding), True
    if ehal_live.is_openems_backend():
        return _read_absent_openems(binding), True
    return _read_absent_loxone(binding), True


def load_default_house_doc() -> dict | None:
    from house_config.profiles_store import load_default_house_profiles_doc

    return load_default_house_profiles_doc()
