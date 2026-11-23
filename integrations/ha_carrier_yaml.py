"""Home Assistant push carrier YAML package (Binding P5c).

From activated ``ehal_bindings`` keys: rest_command + periodic push automations
(``time_pattern`` = ``EARNIE_PUSH_REPEAT_S``), heartbeat, REST sensor on
``status.json``, setpoint automations with ``ENTITY_*`` placeholders, Jinja unit
conversion to canonical EHAL units, optional ``plant.ha_ess_force`` Huawei setpoint
automations, and a watchdog that also writes ``plant.ha_fail_safe_values``.

Import facade: shared helpers live in ``integrations.ha_carrier_common``, the Jinja unit
blocks in ``integrations.ha_carrier_jinja`` and the automations in
``integrations.ha_carrier_automations``; all are re-exported here.
"""
from __future__ import annotations

from typing import Any

from ehal.push_signals import (
    HUB_WRITE_FAILED_ID,
    Signal,
    heartbeat_signal,
    read_signals_from_docs,
    write_signals_from_docs,
)
from ehal.qualified_ids import field_kind
from house_config.ha_fail_safe import FAIL_SAFE_VALUES_KEY, normalize_ha_fail_safe_values
from integrations.ha_carrier_automations import (  # noqa: F401  (re-exports)
    _automations,
    _fail_safe_write,
    _ha_ess_force_automations,
    _heartbeat_automation,
    _push_automation_analog,
    _push_automation_digital,
    _setpoint_automation,
    _watchdog_automation,
)
from integrations.ha_carrier_common import (  # noqa: F401  (re-exports)
    _LOGGER,
    DEFAULT_WATCHDOG_TIMEOUT_S,
    MODE_FAIL_SAFE_VALUES,
    STATUS_SENSOR_ENTITY,
    STATUS_SENSOR_NAME,
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
from integrations.ha_carrier_jinja import (  # noqa: F401  (re-exports)
    _UNIT_CONVERTED,
    _entity_unit_template,
    _hub_value_template,
    _jinja_from_ehal_vars,
    _jinja_to_ehal_vars,
    _log_skip_unknown_unit,
)
from integrations.ha_units import QUANTITY_BASE_UNIT, field_quantity  # noqa: F401
from scripts.pilot_vo_template_gen import TOKEN_PLACEHOLDER


def _repeat_s(repeat_s: float | None) -> float:
    if repeat_s is not None and repeat_s > 0:
        return float(repeat_s)
    from runtime_store.ehal_push_inbox import expected_repeat_s

    return float(expected_repeat_s())


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


def fail_safe_signals(writes: list[Signal], force: dict[str, Any] | None) -> list[Signal]:
    """Written signals that can take a fail-safe value: numbers with a physical unit.

    Modes and flags have no unit. With a vendor force the active power has no entity to
    write to, the watchdog calls the vendor's stop service instead.
    """
    return [
        sig
        for sig in writes
        if ehal_base_unit(sig.ehal_id)
        and not (force and field_kind(sig.ehal_id) == "set_ess_active_power")
    ]


def fail_safe_signals_from_docs(house: dict, components: dict) -> list[Signal]:
    return fail_safe_signals(write_signals_from_docs(house, components), _ha_ess_force(house))


def _fail_safe_values(
    house: dict,
    writes: list[Signal],
    force: dict[str, Any] | None,
) -> dict[str, float]:
    """Saved values in signal order. A value the package cannot apply is an error."""
    plant = house.get("plant") if isinstance(house, dict) else None
    raw = plant.get(FAIL_SAFE_VALUES_KEY) if isinstance(plant, dict) else None
    values = normalize_ha_fail_safe_values(raw) or {}
    usable = [sig.ehal_id for sig in fail_safe_signals(writes, force)]
    unusable = sorted(set(values) - set(usable))
    if unusable:
        raise ValueError(
            f"Fail-safe-Wert ohne passendes Signal: {', '.join(unusable)}. Das Signal ist nicht "
            "aktiviert oder wird nicht als Zahl geschrieben. Die Fail-safe-Werte auf EHAL-Com "
            f"einmal speichern entfernt ihn (plant.{FAIL_SAFE_VALUES_KEY})."
        )
    return {ehal_id: values[ehal_id] for ehal_id in usable if ehal_id in values}


def _header(
    repeat_s: float,
    watchdog_s: float = 0.0,
    *,
    fail_safe_ids: list[str] | None = None,
) -> list[str]:
    fail_safe_list = ", ".join(fail_safe_ids or [])
    if watchdog_s > 0:
        watchdog = [
            f"# Watchdog: automation {WATCHDOG_AUTOMATION_ID} releases a forced ESS active "
            f"power when status.json is unreachable for {watchdog_s:g}s.",
            *([f"# It also writes the fail-safe values of: {fail_safe_list}."] if fail_safe_list else []),
            "# Disable: delete that automation or generate with --watchdog-s 0.",
        ]
    else:
        watchdog = (
            [f"# Fail-safe values are not applied, no watchdog: {fail_safe_list}."]
            if fail_safe_list
            else []
        )
    return [
        *watchdog,
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


def build_carrier_yaml(
    house: dict,
    components: dict,
    *,
    earnie_host: str,
    earnie_port: int,
    token: str = TOKEN_PLACEHOLDER,
    repeat_s: float | None = None,
    watchdog_s: float = DEFAULT_WATCHDOG_TIMEOUT_S,
) -> str:
    """Return a full HA YAML package for activated push signals.

    ``watchdog_s``: seconds of an unreachable ``status.json`` after which a forced ESS
    active power is released and ``plant.ha_fail_safe_values`` are written (0 = no
    watchdog automation). Raises ``ValueError`` for a saved value without a usable signal.
    """
    cadence = _repeat_s(repeat_s)
    base = f"http://{earnie_host}:{earnie_port}"
    token_q = f"?t={token}"
    reads = read_signals_from_docs(house, components)
    writes = write_signals_from_docs(house, components)
    force = _ha_ess_force(house)
    fail_safe = _fail_safe_values(house, writes, force)
    force_attrs = _active_power_write_ids(writes) if force else []
    if force and not force_attrs:
        force_attrs = ["ess.house.set_ess_active_power"]

    parts: list[str] = []
    has_watchdog = bool(
        _watchdog_automation(writes, force, timeout_s=watchdog_s, fail_safe=fail_safe)
    )
    parts.extend(
        _header(cadence, watchdog_s if has_watchdog else 0.0, fail_safe_ids=list(fail_safe))
    )
    parts.extend(_rest_commands(reads, base=base, token_q=token_q))
    parts.extend(
        _status_sensor(base, token_q, writes, cadence, extra_attrs=force_attrs)
    )
    parts.extend(
        _automations(
            reads,
            writes,
            repeat_s=cadence,
            force=force,
            watchdog_s=watchdog_s,
            fail_safe=fail_safe,
        )
    )
    return "\n".join(parts)
