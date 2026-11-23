"""Shared names and small helpers of the HA push carrier YAML package (Binding P5c).

Split from ``integrations.ha_carrier_yaml`` (2.8 quality gate); that module stays the
import facade and re-exports these names.
"""
from __future__ import annotations

import json
import re

from ehal.push_signals import Signal
from ehal.qualified_ids import field_kind
from integrations.ha_units import QUANTITY_BASE_UNIT, field_quantity

STATUS_SENSOR_ENTITY = "sensor.earnie_ehal_status"
STATUS_SENSOR_NAME = "earnie_ehal_status"
_LOGGER = "earnie_ha_carrier"
# status.json unreachable for this long -> a forced active power is released (issue #60).
DEFAULT_WATCHDOG_TIMEOUT_S = 300.0
WATCHDOG_AUTOMATION_ID = "earnie_watchdog_release_force"


def entity_placeholder(ehal_id: str) -> str:
    """``ENTITY_*`` placeholder for a qualified EHAL ID (no real entity_ids)."""
    text = re.sub(r"[^A-Za-z0-9]+", "_", str(ehal_id).strip()).strip("_")
    return f"ENTITY_{text}" if text else "ENTITY_unknown"


def set_value_action(entity: str) -> str:
    """Templated HA action: ``number`` and ``input_number`` targets need their own domain.

    The real entity_id is only entered in Home Assistant (``ENTITY_*`` placeholder), so
    the domain is taken from it at run time instead of being fixed when generating.
    """
    return "{{ " + repr(entity) + ".split('.')[0] }}.set_value"


def rest_command_name(sig: Signal) -> str:
    """HA ``rest_command`` key for a read / heartbeat signal."""
    return sig.title.replace("Push_", "earnie_push_").lower()


def ehal_base_unit(ehal_id: str) -> str | None:
    """Canonical EHAL unit for a field, or ``None`` when unconstrained."""
    qty = field_quantity(field_kind(ehal_id))
    return QUANTITY_BASE_UNIT.get(qty) if qty else None


def _q(text: str) -> str:
    return json.dumps(text, ensure_ascii=False)


def _time_pattern_lines(repeat_s: float) -> list[str]:
    sec = max(1, int(round(repeat_s)))
    if sec >= 60 and sec % 60 == 0:
        return ["      - trigger: time_pattern", f'        minutes: "/{sec // 60}"']
    if sec >= 60:
        return ["      - trigger: time_pattern", '        minutes: "/1"']
    return ["      - trigger: time_pattern", f'        seconds: "/{sec}"']


def _sanitize_id(ehal_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", str(ehal_id).strip()).strip("_").lower()


def _active_power_write_ids(writes: list[Signal]) -> list[str]:
    return [s.ehal_id for s in writes if field_kind(s.ehal_id) == "set_ess_active_power"]


# Signals the watchdog sets to a fixed value while Earnie is unreachable. The value is part
# of the signal's meaning, not a user setting: SG-Ready 2 = normal (HeatControl P2), store
# charge target 0 = no target (P3).
MODE_FAIL_SAFE_VALUES: dict[str, int] = {
    "set_sg_ready_state": 2,
    "set_temperature_heat_storage_target": 0,
}


def _mode_fail_safe_ids(writes: list[Signal]) -> list[str]:
    return [s.ehal_id for s in writes if field_kind(s.ehal_id) in MODE_FAIL_SAFE_VALUES]
