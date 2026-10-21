"""Home Assistant push carrier YAML package (Binding P5c).

From activated ``ehal_bindings`` keys: rest_command + periodic push automations
(``time_pattern`` = ``EARNIE_PUSH_REPEAT_S``), heartbeat, REST sensor on
``status.json``, setpoint automations with ``ENTITY_*`` placeholders, Jinja unit
conversion to canonical EHAL units, and optional ``plant.ha_ess_force`` Huawei
setpoint automations.
"""
from __future__ import annotations

import json
import re
from typing import Any

from ehal.push_signals import (
    HUB_WRITE_FAILED_ID,
    Signal,
    heartbeat_signal,
    read_signals_from_docs,
    write_signals_from_docs,
)
from ehal.qualified_ids import field_kind
from integrations.ha_units import QUANTITY_BASE_UNIT, field_quantity
from scripts.pilot_vo_template_gen import TOKEN_PLACEHOLDER

STATUS_SENSOR_ENTITY = "sensor.earnie_ehal_status"
STATUS_SENSOR_NAME = "earnie_ehal_status"
_LOGGER = "earnie_ha_carrier"


def entity_placeholder(ehal_id: str) -> str:
    """``ENTITY_*`` placeholder for a qualified EHAL ID (no real entity_ids)."""
    text = re.sub(r"[^A-Za-z0-9]+", "_", str(ehal_id).strip()).strip("_")
    return f"ENTITY_{text}" if text else "ENTITY_unknown"


def rest_command_name(sig: Signal) -> str:
    """HA ``rest_command`` key for a read / heartbeat signal."""
    return sig.title.replace("Push_", "earnie_push_").lower()


def ehal_base_unit(ehal_id: str) -> str | None:
    """Canonical EHAL unit for a field, or ``None`` when unconstrained."""
    qty = field_quantity(field_kind(ehal_id))
    return QUANTITY_BASE_UNIT.get(qty) if qty else None


def _q(text: str) -> str:
    return json.dumps(text, ensure_ascii=False)


def _repeat_s(repeat_s: float | None) -> float:
    if repeat_s is not None and repeat_s > 0:
        return float(repeat_s)
    from runtime_store.ehal_push_inbox import expected_repeat_s

    return float(expected_repeat_s())


def _time_pattern_lines(repeat_s: float) -> list[str]:
    sec = max(1, int(round(repeat_s)))
    if sec >= 60 and sec % 60 == 0:
        return ["      - trigger: time_pattern", f'        minutes: "/{sec // 60}"']
    if sec >= 60:
        return ["      - trigger: time_pattern", '        minutes: "/1"']
    return ["      - trigger: time_pattern", f'        seconds: "/{sec}"']


def _scan_interval_s(repeat_s: float) -> int:
    return max(1, int(round(repeat_s)))


def _ha_ess_force(house: dict) -> dict[str, Any] | None:
    from house_config.ha_ess_force import normalize_ha_ess_force

    plant = house.get("plant") if isinstance(house, dict) else None
    raw = plant.get("ha_ess_force") if isinstance(plant, dict) else None
    try:
        return normalize_ha_ess_force(raw)
    except ValueError:
        return None


def _active_power_write_ids(writes: list[Signal]) -> list[str]:
    return [s.ehal_id for s in writes if field_kind(s.ehal_id) == "set_ess_active_power"]


def _header(repeat_s: float) -> list[str]:
    return [
        "# Earnie HA push carrier package (Binding P5c)",
        "# Merge into configuration.yaml or an HA package.",
        "# Replace every ENTITY_* placeholder with the mapped HA entity_id in HA.",
        "# Earnie stores no entity_ids — placeholders only.",
        f"# Push cadence: time_pattern every {repeat_s:g}s "
        "(EARNIE_PUSH_REPEAT_S; not only on state change).",
        "# Wire values are canonical EHAL units (W, kWh, %, A).",
        "",
    ]


def _rest_commands(
    reads: list[Signal],
    *,
    base: str,
    token_q: str,
) -> list[str]:
    lines = ["rest_command:"]
    for sig in reads:
        cmd = rest_command_name(sig)
        if sig.digital:
            lines += [
                f"  {cmd}_on:",
                f'    url: "{base}/ehal/telemetry/{sig.ehal_id}/1{token_q}"',
                "    method: GET",
                f"  {cmd}_off:",
                f'    url: "{base}/ehal/telemetry/{sig.ehal_id}/0{token_q}"',
                "    method: GET",
            ]
        else:
            url = f"{base}/ehal/telemetry/{sig.ehal_id}/" + "{{ ehal_value }}" + token_q
            lines += [
                f"  {cmd}:",
                f'    url: "{url}"',
                "    method: GET",
                f"    # EHAL id: {sig.ehal_id}",
            ]
    hb = heartbeat_signal()
    lines += [
        "  earnie_push_heartbeat:",
        f'    url: "{base}/ehal/telemetry/{hb.ehal_id}/1{token_q}"',
        "    method: GET",
        # Reported while a setpoint automation still sees its target differ after the write.
        "  earnie_push_hub_write_failed:",
        f'    url: "{base}/ehal/telemetry/{HUB_WRITE_FAILED_ID}/1{token_q}"',
        "    method: GET",
        "",
    ]
    return lines


def _jinja_to_ehal_vars(entity: str, ehal_unit: str | None) -> list[str]:
    """Variables block: convert entity state → ``ehal_value`` (or none)."""
    raw = f"states('{entity}')"
    unit = f"state_attr('{entity}', 'unit_of_measurement') | default('', true) | lower"
    lines = [
        "      - variables:",
        f"          raw_state: {_q('{{ ' + raw + ' }}')}",
        f"          entity_unit: {_q('{{ ' + unit + ' }}')}",
    ]
    if ehal_unit is None:
        lines.append(
            "          ehal_value: "
            + _q(
                "{% if raw_state | is_number %}{{ raw_state | float }}"
                "{% else %}{{ none }}{% endif %}"
            )
        )
        return lines
    # Power / energy / percent / current factor tables (entity → EHAL).
    if ehal_unit == "W":
        conv = (
            "{% set u = entity_unit %}"
            "{% if not (raw_state | is_number) %}{{ none }}{% elif u in ['w', 'watt', 'watts'] %}{{ raw_state | float }}"
            "{% elif u in ['kw', 'kilowatt', 'kilowatts'] %}{{ (raw_state | float) * 1000 }}"
            "{% elif u in ['mw', 'megawatt', 'megawatts'] %}{{ (raw_state | float) * 1000000 }}"
            "{% else %}{{ none }}{% endif %}"
        )
    elif ehal_unit == "kWh":
        conv = (
            "{% set u = entity_unit %}"
            "{% if not (raw_state | is_number) %}{{ none }}{% elif u in ['kwh', 'kilowatt-hour', 'kilowatt-hours'] %}{{ raw_state | float }}"
            "{% elif u in ['wh', 'watt-hour', 'watt-hours', 'watthour', 'watthours'] %}"
            "{{ (raw_state | float) * 0.001 }}"
            "{% elif u in ['mwh', 'megawatt-hour', 'megawatt-hours'] %}"
            "{{ (raw_state | float) * 1000 }}"
            "{% else %}{{ none }}{% endif %}"
        )
    elif ehal_unit == "%":
        conv = (
            "{% set u = entity_unit %}"
            "{% if not (raw_state | is_number) %}{{ none }}{% elif u in ['%', 'percent'] %}{{ raw_state | float }}"
            "{% else %}{{ none }}{% endif %}"
        )
    elif ehal_unit == "A":
        conv = (
            "{% set u = entity_unit %}"
            "{% if not (raw_state | is_number) %}{{ none }}{% elif u in ['a', 'amp', 'amps', 'ampere'] %}{{ raw_state | float }}"
            "{% elif u in ['ma', 'milliampere'] %}{{ (raw_state | float) * 0.001 }}"
            "{% else %}{{ none }}{% endif %}"
        )
    else:
        conv = (
            "{% if raw_state | is_number %}{{ raw_state | float }}"
            "{% else %}{{ none }}{% endif %}"
        )
    lines.append(f"          ehal_value: {_q(conv)}")
    return lines


def _jinja_from_ehal_vars(attr: str, entity: str, ehal_unit: str | None) -> list[str]:
    """Variables: status attribute (EHAL) → ``hub_value`` for the target entity."""
    ehal_expr = f"state_attr('{STATUS_SENSOR_ENTITY}', '{attr}')"
    unit = f"state_attr('{entity}', 'unit_of_measurement') | default('', true) | lower"
    lines = [
        "      - variables:",
        f"          ehal_raw: {_q('{{ ' + ehal_expr + ' }}')}",
        f"          entity_unit: {_q('{{ ' + unit + ' }}')}",
    ]
    if ehal_unit is None:
        lines.append(
            "          hub_value: "
            + _q(
                "{% if ehal_raw is not none and ehal_raw | is_number %}"
                "{{ ehal_raw | float }}{% else %}{{ none }}{% endif %}"
            )
        )
        return lines
    if ehal_unit == "W":
        conv = (
            "{% set u = entity_unit %}"
            "{% if ehal_raw is none or not (ehal_raw | is_number) %}{{ none }}"
            "{% elif u in ['w', 'watt', 'watts'] %}{{ ehal_raw | float }}"
            "{% elif u in ['kw', 'kilowatt', 'kilowatts'] %}{{ (ehal_raw | float) / 1000 }}"
            "{% elif u in ['mw', 'megawatt', 'megawatts'] %}{{ (ehal_raw | float) / 1000000 }}"
            "{% else %}{{ none }}{% endif %}"
        )
    elif ehal_unit == "kWh":
        conv = (
            "{% set u = entity_unit %}"
            "{% if ehal_raw is none or not (ehal_raw | is_number) %}{{ none }}"
            "{% elif u in ['kwh', 'kilowatt-hour', 'kilowatt-hours'] %}{{ ehal_raw | float }}"
            "{% elif u in ['wh', 'watt-hour', 'watt-hours', 'watthour', 'watthours'] %}"
            "{{ (ehal_raw | float) * 1000 }}"
            "{% elif u in ['mwh', 'megawatt-hour', 'megawatt-hours'] %}"
            "{{ (ehal_raw | float) / 1000 }}"
            "{% else %}{{ none }}{% endif %}"
        )
    elif ehal_unit == "%":
        conv = (
            "{% set u = entity_unit %}"
            "{% if ehal_raw is none or not (ehal_raw | is_number) %}{{ none }}"
            "{% elif u in ['%', 'percent'] %}{{ ehal_raw | float }}"
            "{% else %}{{ none }}{% endif %}"
        )
    elif ehal_unit == "A":
        conv = (
            "{% set u = entity_unit %}"
            "{% if ehal_raw is none or not (ehal_raw | is_number) %}{{ none }}"
            "{% elif u in ['a', 'amp', 'amps', 'ampere'] %}{{ ehal_raw | float }}"
            "{% elif u in ['ma', 'milliampere'] %}{{ (ehal_raw | float) * 1000 }}"
            "{% else %}{{ none }}{% endif %}"
        )
    else:
        conv = (
            "{% if ehal_raw is not none and ehal_raw | is_number %}"
            "{{ ehal_raw | float }}{% else %}{{ none }}{% endif %}"
        )
    lines.append(f"          hub_value: {_q(conv)}")
    return lines


def _log_skip_unknown_unit(message: str) -> list[str]:
    return [
        "      - if:",
        "          - condition: template",
        f"            value_template: {_q('{{ ehal_value is none }}')}",
        "        then:",
        "          - action: system_log.write",
        "            data:",
        "              level: warning",
        f"              logger: {_LOGGER}",
        f"              message: {_q(message)}",
        "        else:",
    ]


def _push_automation_analog(sig: Signal, repeat_s: float) -> list[str]:
    entity = entity_placeholder(sig.ehal_id)
    cmd = rest_command_name(sig)
    unit = ehal_base_unit(sig.ehal_id)
    auto_id = f"earnie_push_{_sanitize_id(sig.ehal_id)}"
    skip_msg = (
        f"Earnie push skipped for {sig.ehal_id}: unknown or incompatible "
        f"unit_of_measurement on {entity} (need {unit or 'numeric'})"
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


def _sanitize_id(ehal_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", str(ehal_id).strip()).strip("_").lower()


def _status_sensor(
    base: str,
    token_q: str,
    writes: list[Signal],
    repeat_s: float,
    *,
    extra_attrs: list[str] | None = None,
) -> list[str]:
    from ehal.push_signals import HEARTBEAT_WRITE_ID

    attrs = [HEARTBEAT_WRITE_ID] + [s.ehal_id for s in writes]
    for extra in extra_attrs or []:
        if extra not in attrs:
            attrs.append(extra)
    lines = [
        "sensor:",
        "  - platform: rest",
        f"    name: {STATUS_SENSOR_NAME}",
        f'    resource: "{base}/ehal/status.json{token_q}"',
        f"    scan_interval: {_scan_interval_s(repeat_s)}",
        f'    value_template: {_q("{{ value_json." + HEARTBEAT_WRITE_ID + " | default(0) }}")}',
        # No ``json_attributes_path``: HA's jsonpath("$") returns False for a dict,
        # which leaves the sensor without attributes (no setpoint automation fires).
        "    json_attributes:",
    ]
    for attr in attrs:
        lines.append(f"      - {_q(attr) if '.' in attr else attr}")
    lines.append("")
    return lines


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
    skip_msg = (
        f"Earnie setpoint skipped for {sig.ehal_id}: unknown or incompatible "
        f"unit_of_measurement on {entity} (need {unit or 'numeric'})"
    )
    # Re-assert on every tick, but only write when the target drifted (≈1 %), so
    # a restart or a manual change is corrected without a write every interval.
    drift = (
        f"{{% set cur = states('{entity}') | float(none) %}}"
        "{{ cur is none or (cur - (hub_value | float)) | abs "
        "> 0.01 * (hub_value | float | abs) + 0.01 }}"
    )
    # Indent under else: of the unknown-unit guard (10 spaces before - if).
    not_applied_msg = (
        f"Earnie setpoint {sig.ehal_id} not applied: {entity} still differs after the write"
    )
    # ``continue_on_error`` keeps a refusing target from aborting the script (4 nested
    # ERROR lines per attempt); the check after the delay then reports it to Earnie.
    apply = [
        "          - if:",
        "              - condition: template",
        f"                value_template: {_q(drift)}",
        "            then:",
        "              - action: number.set_value",
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
    guard = [
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
        *guard,
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


def _automations(
    reads: list[Signal],
    writes: list[Signal],
    *,
    repeat_s: float,
    force: dict[str, Any] | None,
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
    lines.append("")
    return lines


def build_carrier_yaml(
    house: dict,
    components: dict,
    *,
    earnie_host: str,
    earnie_port: int,
    token: str = TOKEN_PLACEHOLDER,
    repeat_s: float | None = None,
) -> str:
    """Return a full HA YAML package for activated push signals."""
    cadence = _repeat_s(repeat_s)
    base = f"http://{earnie_host}:{earnie_port}"
    token_q = f"?t={token}"
    reads = read_signals_from_docs(house, components)
    writes = write_signals_from_docs(house, components)
    force = _ha_ess_force(house)
    force_attrs = _active_power_write_ids(writes) if force else []
    if force and not force_attrs:
        force_attrs = ["ess.house.set_ess_active_power"]

    parts: list[str] = []
    parts.extend(_header(cadence))
    parts.extend(_rest_commands(reads, base=base, token_q=token_q))
    parts.extend(
        _status_sensor(base, token_q, writes, cadence, extra_attrs=force_attrs)
    )
    parts.extend(
        _automations(reads, writes, repeat_s=cadence, force=force)
    )
    return "\n".join(parts)
