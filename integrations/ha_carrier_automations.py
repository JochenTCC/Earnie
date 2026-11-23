"""Automation blocks of the HA push carrier YAML package (Binding P5c).

Push / heartbeat / setpoint automations, ``plant.ha_ess_force`` Huawei automations and
the watchdog. Split from ``integrations.ha_carrier_yaml`` (2.8 quality gate); that
module stays the import facade and re-exports these names.
"""
from __future__ import annotations

import json
from typing import Any

from ehal.push_signals import Signal
from ehal.qualified_ids import field_kind
from integrations.ha_carrier_common import (
    _LOGGER,
    MODE_FAIL_SAFE_VALUES,
    STATUS_SENSOR_ENTITY,
    WATCHDOG_AUTOMATION_ID,
    _active_power_write_ids,
    _mode_fail_safe_ids,
    _q,
    _sanitize_id,
    _time_pattern_lines,
    ehal_base_unit,
    entity_placeholder,
    rest_command_name,
    set_value_action,
)
from integrations.ha_carrier_jinja import (
    _UNIT_CONVERTED,
    _entity_unit_template,
    _hub_value_template,
    _jinja_from_ehal_vars,
    _jinja_to_ehal_vars,
    _log_skip_unknown_unit,
)


def _push_automation_analog(sig: Signal, repeat_s: float) -> list[str]:
    entity = entity_placeholder(sig.ehal_id)
    cmd = rest_command_name(sig)
    unit = ehal_base_unit(sig.ehal_id)
    auto_id = f"earnie_push_{_sanitize_id(sig.ehal_id)}"
    skip_msg = (
        f"Earnie push skipped for {sig.ehal_id}: {entity} is unavailable/non-numeric "
        f"or has an unknown or incompatible unit_of_measurement (need {unit or 'numeric'})"
    )
    return [
        f"  - id: {auto_id}",
        f"    alias: {_q(f'Earnie push {sig.ehal_id}')}",
        "    mode: queued",
        "    max: 5",
        "    triggers:",
        *_time_pattern_lines(repeat_s),
        "      - trigger: homeassistant",
        "        event: start",
        "      - trigger: state",
        f"        entity_id: {entity}",
        "    actions:",
        *_jinja_to_ehal_vars(entity, unit),
        *_log_skip_unknown_unit(skip_msg),
        f"          - action: rest_command.{cmd}",
        "            data:",
        f"              ehal_value: {_q('{{ ehal_value }}')}",
    ]


def _push_automation_digital(sig: Signal, repeat_s: float) -> list[str]:
    entity = entity_placeholder(sig.ehal_id)
    cmd = rest_command_name(sig)
    auto_id = f"earnie_push_{_sanitize_id(sig.ehal_id)}"
    on_expr = (
        f"is_state('{entity}', 'on') or "
        f"(states('{entity}') | is_number and (states('{entity}') | float | abs) >= 0.5)"
    )
    return [
        f"  - id: {auto_id}",
        f"    alias: {_q(f'Earnie push {sig.ehal_id}')}",
        "    mode: queued",
        "    max: 5",
        "    triggers:",
        *_time_pattern_lines(repeat_s),
        "      - trigger: homeassistant",
        "        event: start",
        "      - trigger: state",
        f"        entity_id: {entity}",
        "    actions:",
        "      - if:",
        "          - condition: template",
        f"            value_template: {_q('{{ ' + on_expr + ' }}')}",
        "        then:",
        f"          - action: rest_command.{cmd}_on",
        "        else:",
        f"          - action: rest_command.{cmd}_off",
    ]


def _heartbeat_automation(repeat_s: float) -> list[str]:
    return [
        "  - id: earnie_push_heartbeat",
        f"    alias: {_q('Earnie push heartbeat')}",
        "    mode: single",
        "    triggers:",
        *_time_pattern_lines(repeat_s),
        "      - trigger: homeassistant",
        "        event: start",
        "    actions:",
        "      - action: rest_command.earnie_push_heartbeat",
    ]


def _setpoint_apply_lines(ehal_id: str, entity: str) -> list[str]:
    """Drift-gated write plus a check after 5 s (nested under the unit guard's ``else:``)."""
    # Re-assert on every tick, but only write when the target drifted (≈1 %), so
    # a restart or a manual change is corrected without a write every interval.
    drift = (
        f"{{% set cur = states('{entity}') | float(none) %}}"
        "{{ cur is none or (cur - (hub_value | float)) | abs "
        "> 0.01 * (hub_value | float | abs) + 0.01 }}"
    )
    # Indent under else: of the unknown-unit guard (10 spaces before - if).
    not_applied_msg = (
        f"Earnie setpoint {ehal_id} not applied: {entity} still differs after the write"
    )
    # ``continue_on_error`` keeps a refusing target from aborting the script (4 nested
    # ERROR lines per attempt); the check after the delay then reports it to Earnie.
    return [
        "          - if:",
        "              - condition: template",
        f"                value_template: {_q(drift)}",
        "            then:",
        f"              - action: {_q(set_value_action(entity))}",
        "                continue_on_error: true",
        "                target:",
        f"                  entity_id: {entity}",
        "                data:",
        f"                  value: {_q('{{ hub_value }}')}",
        "              - delay:",
        "                  seconds: 5",
        "              - if:",
        "                  - condition: template",
        f"                    value_template: {_q(drift)}",
        "                then:",
        "                  - action: system_log.write",
        "                    data:",
        "                      level: warning",
        f"                      logger: {_LOGGER}",
        f"                      message: {_q(not_applied_msg)}",
        "                  - action: rest_command.earnie_push_hub_write_failed",
    ]


def _setpoint_guard_lines(ehal_id: str, entity: str, unit: str | None) -> list[str]:
    """Unknown-unit guard around the apply block (only for converted units)."""
    apply = _setpoint_apply_lines(ehal_id, entity)
    # Only these units are read from the target entity (see _jinja_from_ehal_vars); for
    # all others hub_value is none only for a non-numeric value, which the
    # ``nothing_published`` stop already handles, so no guard is generated.
    if unit not in _UNIT_CONVERTED:
        # ``apply`` is nested under ``else:`` (4 spaces deeper than the action list).
        return [line[4:] for line in apply]
    skip_msg = (
        f"Earnie setpoint skipped for {ehal_id}: unknown or incompatible "
        f"unit_of_measurement on {entity} (need {unit})"
    )
    return [
        "      - if:",
        "          - condition: template",
        f"            value_template: {_q('{{ hub_value is none }}')}",
        "        then:",
        "          - action: system_log.write",
        "            data:",
        "              level: warning",
        f"              logger: {_LOGGER}",
        f"              message: {_q(skip_msg)}",
        "        else:",
        *apply,
    ]


def _setpoint_automation(
    sig: Signal,
    *,
    skip_active_power: bool,
    repeat_s: float,
) -> list[str]:
    if skip_active_power and field_kind(sig.ehal_id) == "set_ess_active_power":
        return []
    entity = entity_placeholder(sig.ehal_id)
    unit = ehal_base_unit(sig.ehal_id)
    auto_id = f"earnie_setpoint_{_sanitize_id(sig.ehal_id)}"
    # Fields Earnie did not publish (e.g. active power in automatic mode) are not an error.
    nothing_published = [
        "      - if:",
        "          - condition: template",
        f"            value_template: {_q('{{ ehal_raw is none or not (ehal_raw | is_number) }}')}",
        "        then:",
        "          - stop: \"Earnie published no value for this field\"",
    ]
    return [
        f"  - id: {auto_id}",
        f"    alias: {_q(f'Earnie setpoint {sig.ehal_id}')}",
        "    mode: queued",
        "    max: 5",
        "    triggers:",
        "      - trigger: state",
        f"        entity_id: {STATUS_SENSOR_ENTITY}",
        f"        attribute: {sig.ehal_id}",
        "      - trigger: homeassistant",
        "        event: start",
        *_time_pattern_lines(repeat_s),
        "    actions:",
        *_jinja_from_ehal_vars(sig.ehal_id, entity, unit),
        *nothing_published,
        *_setpoint_guard_lines(sig.ehal_id, entity, unit),
    ]


def _ha_ess_force_automations(
    force: dict[str, Any],
    active_power_ids: list[str],
) -> list[str]:
    if not active_power_ids:
        # Plant-level force still needs a status attribute; use common house key hint.
        active_power_ids = ["ess.house.set_ess_active_power"]
    device_id = str(force.get("device_id") or "").strip()
    duration = int(force.get("duration_min") or 20)
    lines: list[str] = []
    for qid in active_power_ids:
        auto_id = f"earnie_ha_ess_force_{_sanitize_id(qid)}"
        power_expr = f"state_attr('{STATUS_SENSOR_ENTITY}', '{qid}') | float(0)"
        lines += [
            f"  - id: {auto_id}",
            f"    alias: {_q(f'Earnie Huawei force from {qid}')}",
            "    mode: queued",
            "    max: 5",
            "    triggers:",
            "      - trigger: state",
            f"        entity_id: {STATUS_SENSOR_ENTITY}",
            f"        attribute: {qid}",
            "    actions:",
            "      - variables:",
            f"          power_w: {_q('{{ ' + power_expr + ' }}')}",
            "      - if:",
            "          - condition: template",
            f"            value_template: {_q('{{ (power_w | abs) < 1 }}')}",
            "        then:",
            "          - action: huawei_solar.stop_forcible_charge",
            "            data:",
            f"              device_id: {_q(device_id)}",
            "        else:",
            "          - if:",
            "              - condition: template",
            f"                value_template: {_q('{{ power_w > 0 }}')}",
            "            then:",
            "              - action: huawei_solar.forcible_discharge",
            "                data:",
            f"                  device_id: {_q(device_id)}",
            f"                  power: {_q('{{ power_w | abs | int }}')}",
            f"                  duration: {duration}",
            "            else:",
            "              - action: huawei_solar.forcible_charge",
            "                data:",
            f"                  device_id: {_q(device_id)}",
            f"                  power: {_q('{{ power_w | abs | int }}')}",
            f"                  duration: {duration}",
        ]
    return lines


def _fail_safe_write(ehal_id: str, value: float) -> list[str]:
    """Write one fail-safe value, converted to the entity's unit at run time."""
    entity = entity_placeholder(ehal_id)
    unit = ehal_base_unit(ehal_id)
    skip_msg = (
        f"Earnie fail-safe value for {ehal_id} not written: unknown or incompatible "
        f"unit_of_measurement on {entity} (need {unit})"
    )
    return [
        "      - variables:",
        f"          ehal_raw: {json.dumps(value)}",
        f"          entity_unit: {_q(_entity_unit_template(entity))}",
        f"          hub_value: {_q(_hub_value_template(unit))}",
        "      - if:",
        "          - condition: template",
        f"            value_template: {_q('{{ hub_value is none }}')}",
        "        then:",
        "          - action: system_log.write",
        "            data:",
        "              level: warning",
        f"              logger: {_LOGGER}",
        f"              message: {_q(skip_msg)}",
        "        else:",
        f"          - action: {_q(set_value_action(entity))}",
        "            continue_on_error: true",
        "            target:",
        f"              entity_id: {entity}",
        "            data:",
        f"              value: {_q('{{ hub_value }}')}",
    ]


def _set_entity_value_lines(ehal_id: str, value: object) -> list[str]:
    """Watchdog action: write a fixed value to the signal's entity."""
    entity = entity_placeholder(ehal_id)
    return [
        f"      - action: {_q(set_value_action(entity))}",
        "        continue_on_error: true",
        "        target:",
        f"          entity_id: {entity}",
        "        data:",
        f"          value: {value}",
    ]


def _watchdog_release_lines(
    force: dict[str, Any] | None,
    active_ids: list[str],
    values: dict[str, float],
) -> list[str]:
    """Vendor stop service with a force, else active power 0 (unless it has a fail-safe)."""
    if force:
        device_id = str(force.get("device_id") or "").strip()
        return [
            "      - action: huawei_solar.stop_forcible_charge",
            "        continue_on_error: true",
            "        data:",
            f"          device_id: {_q(device_id)}",
        ]
    lines: list[str] = []
    for qid in active_ids:
        if qid not in values:
            lines += _set_entity_value_lines(qid, 0)
    return lines


def _watchdog_automation(
    writes: list[Signal],
    force: dict[str, Any] | None,
    *,
    timeout_s: float,
    fail_safe: dict[str, float] | None = None,
) -> list[str]:
    """Release a forced active power while Earnie is unreachable (issue #60 c).

    Caps stay as they are unless the user entered a fail-safe value for them; modes
    always do. A fail-safe value of the active power replaces the release to 0. The
    trigger is the REST status sensor going ``unavailable`` / ``unknown`` for
    ``timeout_s``; HA then has no attributes, so the periodic setpoint automations stop
    re-asserting Earnie's values. Mode signals with a fixed fail-safe state
    (``MODE_FAIL_SAFE_VALUES``, e.g. SG-Ready 2) are always set to it.
    """
    active_ids = _active_power_write_ids(writes)
    mode_ids = _mode_fail_safe_ids(writes)
    values = fail_safe or {}
    if timeout_s <= 0 or not (active_ids or force or values or mode_ids):
        return []
    alias = (
        "Earnie watchdog: write fail-safe values when Earnie is unreachable"
        if values or mode_ids
        else "Earnie watchdog: release forced power when Earnie is unreachable"
    )
    outcome = (
        "fail-safe values written" if values or mode_ids else "forced active power released"
    )
    lines = [
        f"  - id: {WATCHDOG_AUTOMATION_ID}",
        f"    alias: {_q(alias)}",
        "    mode: single",
        "    triggers:",
        "      - trigger: state",
        f"        entity_id: {STATUS_SENSOR_ENTITY}",
        "        to:",
        "          - unavailable",
        "          - unknown",
        "        for:",
        f"          seconds: {int(timeout_s)}",
        "    actions:",
    ]
    lines += _watchdog_release_lines(force, active_ids, values)
    for ehal_id, value in values.items():
        lines += _fail_safe_write(ehal_id, value)
    for qid in mode_ids:
        lines += _set_entity_value_lines(qid, MODE_FAIL_SAFE_VALUES[field_kind(qid)])
    lines += [
        "      - action: system_log.write",
        "        data:",
        "          level: warning",
        f"          logger: {_LOGGER}",
        f"          message: {_q(f'Earnie unreachable for {int(timeout_s)}s: {outcome}')}",
    ]
    return lines


def _automations(
    reads: list[Signal],
    writes: list[Signal],
    *,
    repeat_s: float,
    force: dict[str, Any] | None,
    watchdog_s: float = 0.0,
    fail_safe: dict[str, float] | None = None,
) -> list[str]:
    lines = ["automation:"]
    for sig in reads:
        if sig.digital:
            lines += _push_automation_digital(sig, repeat_s)
        else:
            lines += _push_automation_analog(sig, repeat_s)
    lines += _heartbeat_automation(repeat_s)
    active_ids = _active_power_write_ids(writes) if force else []
    skip_active = bool(force and active_ids)
    for sig in writes:
        lines += _setpoint_automation(
            sig, skip_active_power=skip_active, repeat_s=repeat_s
        )
    if force:
        lines += _ha_ess_force_automations(force, active_ids)
    lines += _watchdog_automation(writes, force, timeout_s=watchdog_s, fail_safe=fail_safe)
    lines.append("")
    return lines
