"""Jinja unit conversion blocks of the HA push carrier YAML package (Binding P5c).

Entity → canonical EHAL unit for pushes, EHAL → entity unit for setpoints. Split from
``integrations.ha_carrier_yaml`` (2.8 quality gate); that module re-exports these names.
"""
from __future__ import annotations

from integrations.ha_carrier_common import _LOGGER, STATUS_SENSOR_ENTITY, _q


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


_UNIT_CONVERTED = ("W", "kWh", "%", "A")


def _entity_unit_template(entity: str) -> str:
    return "{{ " + f"state_attr('{entity}', 'unit_of_measurement') | default('', true) | lower" + " }}"


def _hub_value_template(ehal_unit: str | None) -> str:
    """Jinja: variable ``ehal_raw`` (EHAL unit) → value for the target entity's unit."""
    if ehal_unit == "W":
        return (
            "{% set u = entity_unit %}"
            "{% if ehal_raw is none or not (ehal_raw | is_number) %}{{ none }}"
            "{% elif u in ['w', 'watt', 'watts'] %}{{ ehal_raw | float }}"
            "{% elif u in ['kw', 'kilowatt', 'kilowatts'] %}{{ (ehal_raw | float) / 1000 }}"
            "{% elif u in ['mw', 'megawatt', 'megawatts'] %}{{ (ehal_raw | float) / 1000000 }}"
            "{% else %}{{ none }}{% endif %}"
        )
    if ehal_unit == "kWh":
        return (
            "{% set u = entity_unit %}"
            "{% if ehal_raw is none or not (ehal_raw | is_number) %}{{ none }}"
            "{% elif u in ['kwh', 'kilowatt-hour', 'kilowatt-hours'] %}{{ ehal_raw | float }}"
            "{% elif u in ['wh', 'watt-hour', 'watt-hours', 'watthour', 'watthours'] %}"
            "{{ (ehal_raw | float) * 1000 }}"
            "{% elif u in ['mwh', 'megawatt-hour', 'megawatt-hours'] %}"
            "{{ (ehal_raw | float) / 1000 }}"
            "{% else %}{{ none }}{% endif %}"
        )
    if ehal_unit == "%":
        return (
            "{% set u = entity_unit %}"
            "{% if ehal_raw is none or not (ehal_raw | is_number) %}{{ none }}"
            "{% elif u in ['%', 'percent'] %}{{ ehal_raw | float }}"
            "{% else %}{{ none }}{% endif %}"
        )
    if ehal_unit == "A":
        return (
            "{% set u = entity_unit %}"
            "{% if ehal_raw is none or not (ehal_raw | is_number) %}{{ none }}"
            "{% elif u in ['a', 'amp', 'amps', 'ampere'] %}{{ ehal_raw | float }}"
            "{% elif u in ['ma', 'milliampere'] %}{{ (ehal_raw | float) * 1000 }}"
            "{% else %}{{ none }}{% endif %}"
        )
    return (
        "{% if ehal_raw is not none and ehal_raw | is_number %}"
        "{{ ehal_raw | float }}{% else %}{{ none }}{% endif %}"
    )


def _jinja_from_ehal_vars(attr: str, entity: str, ehal_unit: str | None) -> list[str]:
    """Variables: status attribute (EHAL) → ``hub_value`` for the target entity."""
    ehal_expr = f"state_attr('{STATUS_SENSOR_ENTITY}', '{attr}')"
    return [
        "      - variables:",
        f"          ehal_raw: {_q('{{ ' + ehal_expr + ' }}')}",
        f"          entity_unit: {_q(_entity_unit_template(entity))}",
        f"          hub_value: {_q(_hub_value_template(ehal_unit))}",
    ]


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
