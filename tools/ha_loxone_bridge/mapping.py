"""Mapping file (JSON) -> validated dataclasses. Fails loud on any inconsistency."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PLACEHOLDER_MARK = "CHANGE_ME"

HA_TO_LOXONE = "ha_to_loxone"
LOXONE_TO_HA = "loxone_to_ha"

# HA domain -> set_value service (numeric) / domain for turn_on|turn_off (switch-like)
NUMBER_DOMAINS = {"number": "number.set_value", "input_number": "input_number.set_value"}
SWITCH_DOMAINS = ("switch", "input_boolean")

_ENTITY_RE = re.compile(r"^[a-z_]+\.[a-z0-9_]+$")
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_LOX_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_HOST_RE = re.compile(r"^[A-Za-z0-9.-]+$")


class MappingError(ValueError):
    """The mapping file is invalid."""


@dataclass(frozen=True)
class Point:
    name: str
    direction: str
    ha_entity: str
    # ha_to_loxone: Virtual Input name; loxone_to_ha: Virtual Output command title
    loxone_name: str
    refresh_minutes: int | None = None  # ha_to_loxone only
    webhook_id: str | None = None  # loxone_to_ha only
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    repeat_seconds: int = 30  # loxone_to_ha only (VO Repeat; 0 = off)

    @property
    def domain(self) -> str:
        return self.ha_entity.split(".", 1)[0]

    @property
    def is_switch(self) -> bool:
        return self.domain in SWITCH_DOMAINS


@dataclass(frozen=True)
class DerivedSensor:
    entity_id: str
    name: str
    unit: str
    plus: tuple[str, ...]
    minus: tuple[str, ...]
    device_class: str | None = None
    state_class: str | None = None


@dataclass(frozen=True)
class BridgeMapping:
    title: str
    loxone_host: str
    loxone_port: int
    loxone_user_secret: str
    loxone_pass_secret: str
    ha_host: str
    ha_port: int
    webhook_local_only: bool
    derived: tuple[DerivedSensor, ...]
    points: tuple[Point, ...]


def slugify(text: str) -> str:
    """HA's default entity id suffix for a friendly name."""
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _only_keys(obj: Any, allowed: set[str], ctx: str) -> dict[str, Any]:
    if not isinstance(obj, dict):
        raise MappingError(f"{ctx}: expected an object")
    unknown = sorted(set(obj) - allowed)
    if unknown:
        raise MappingError(f"{ctx}: unknown keys {unknown}")
    return obj


def _req(obj: dict[str, Any], key: str, ctx: str) -> Any:
    if key not in obj or obj[key] in (None, ""):
        raise MappingError(f"{ctx}: missing '{key}'")
    return obj[key]


def _host(value: Any, ctx: str) -> str:
    text = str(value)
    if not _HOST_RE.match(text):
        raise MappingError(f"{ctx}: host must be a bare IP/hostname without scheme or port, got {text!r}")
    return text


def _entity(value: Any, ctx: str) -> str:
    text = str(value)
    if not _ENTITY_RE.match(text):
        raise MappingError(f"{ctx}: not an entity id (domain.object_id): {text!r}")
    return text


def _int(value: Any, ctx: str, *, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise MappingError(f"{ctx}: expected integer {low}..{high}, got {value!r}")
    return value


def _number(value: Any, ctx: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MappingError(f"{ctx}: expected a number, got {value!r}")
    return float(value)


def _parse_derived(raw: Any, ctx: str) -> DerivedSensor:
    obj = _only_keys(raw, {"entity_id", "name", "unit", "plus", "minus", "device_class", "state_class"}, ctx)
    entity_id = _entity(_req(obj, "entity_id", ctx), f"{ctx}.entity_id")
    name = str(_req(obj, "name", ctx))
    if not entity_id.startswith("sensor."):
        raise MappingError(f"{ctx}: derived entity must be a sensor, got {entity_id!r}")
    if entity_id != f"sensor.{slugify(name)}":
        raise MappingError(
            f"{ctx}: HA derives the entity id from the name — name {name!r} gives "
            f"'sensor.{slugify(name)}', not {entity_id!r}"
        )
    plus = tuple(_entity(e, f"{ctx}.plus") for e in obj.get("plus", []))
    minus = tuple(_entity(e, f"{ctx}.minus") for e in obj.get("minus", []))
    if not plus:
        raise MappingError(f"{ctx}: 'plus' needs at least one entity")
    return DerivedSensor(
        entity_id=entity_id,
        name=name,
        unit=str(_req(obj, "unit", ctx)),
        plus=plus,
        minus=minus,
        device_class=obj.get("device_class"),
        state_class=obj.get("state_class"),
    )


def _parse_point(raw: Any, ctx: str) -> Point:
    obj = _only_keys(
        raw,
        {"name", "direction", "ha_entity", "loxone_input", "loxone_cmd_title", "refresh_minutes",
         "webhook_id", "min", "max", "step", "repeat_seconds"},
        ctx,
    )
    name = str(_req(obj, "name", ctx))
    if not _NAME_RE.match(name):
        raise MappingError(f"{ctx}: name must be snake_case (a-z, 0-9, _), got {name!r}")
    direction = _req(obj, "direction", ctx)
    entity = _entity(_req(obj, "ha_entity", ctx), f"{ctx}.ha_entity")
    domain = entity.split(".", 1)[0]

    if direction == HA_TO_LOXONE:
        for key in ("webhook_id", "min", "max", "step", "repeat_seconds", "loxone_cmd_title"):
            if key in obj:
                raise MappingError(f"{ctx}: '{key}' only applies to {LOXONE_TO_HA}")
        lox_name = str(_req(obj, "loxone_input", ctx))
        refresh = obj.get("refresh_minutes")
        if refresh is not None:
            refresh = _int(refresh, f"{ctx}.refresh_minutes", low=1, high=59)
        if domain in SWITCH_DOMAINS:
            raise MappingError(f"{ctx}: switch-like entities are only supported for {LOXONE_TO_HA}")
        point = Point(name, direction, entity, lox_name, refresh_minutes=refresh)
    elif direction == LOXONE_TO_HA:
        for key in ("loxone_input", "refresh_minutes"):
            if key in obj:
                raise MappingError(f"{ctx}: '{key}' only applies to {HA_TO_LOXONE}")
        if domain not in NUMBER_DOMAINS and domain not in SWITCH_DOMAINS:
            raise MappingError(
                f"{ctx}: unsupported target domain {domain!r} "
                f"(supported: {sorted([*NUMBER_DOMAINS, *SWITCH_DOMAINS])})"
            )
        webhook = str(_req(obj, "webhook_id", ctx))
        lox_name = str(obj.get("loxone_cmd_title") or f"HA_{name}")
        low = _number(obj["min"], f"{ctx}.min") if "min" in obj else None
        high = _number(obj["max"], f"{ctx}.max") if "max" in obj else None
        step = _number(obj["step"], f"{ctx}.step") if "step" in obj else None
        if domain in SWITCH_DOMAINS and (low, high, step) != (None, None, None):
            raise MappingError(f"{ctx}: min/max/step do not apply to a switch")
        if low is not None and high is not None and low > high:
            raise MappingError(f"{ctx}: min {low} > max {high}")
        if step is not None and step <= 0:
            raise MappingError(f"{ctx}: step must be > 0")
        repeat = _int(obj.get("repeat_seconds", 30), f"{ctx}.repeat_seconds", low=0, high=3600)
        point = Point(name, direction, entity, lox_name, webhook_id=webhook, minimum=low,
                      maximum=high, step=step, repeat_seconds=repeat)
    else:
        raise MappingError(f"{ctx}: direction must be '{HA_TO_LOXONE}' or '{LOXONE_TO_HA}', got {direction!r}")

    if not _LOX_NAME_RE.match(point.loxone_name):
        raise MappingError(f"{ctx}: Loxone name must match [A-Za-z0-9_-]+, got {point.loxone_name!r}")
    if point.webhook_id is not None and not _ID_RE.match(point.webhook_id):
        raise MappingError(f"{ctx}: webhook_id must match [A-Za-z0-9_-]+")
    return point


def _check_unique(values: list[str], what: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise MappingError(f"duplicate {what}: {value!r}")
        seen.add(value)


def parse_mapping(raw: Any, *, allow_placeholder: bool = False) -> BridgeMapping:
    top = _only_keys(raw, {"title", "loxone", "ha", "derived_sensors", "points"}, "mapping")
    lox = _only_keys(_req(top, "loxone", "mapping"),
                     {"host", "port", "user_secret", "pass_secret"}, "loxone")
    ha = _only_keys(_req(top, "ha", "mapping"), {"host", "port", "webhook_local_only"}, "ha")
    derived = tuple(_parse_derived(d, f"derived_sensors[{i}]") for i, d in enumerate(top.get("derived_sensors", [])))
    points = tuple(_parse_point(p, f"points[{i}]") for i, p in enumerate(_req(top, "points", "mapping")))

    local_only = ha.get("webhook_local_only", True)
    if not isinstance(local_only, bool):
        raise MappingError("ha.webhook_local_only: expected true/false")
    mapping = BridgeMapping(
        title=str(_req(top, "title", "mapping")),
        loxone_host=_host(_req(lox, "host", "loxone"), "loxone.host"),
        loxone_port=_int(lox.get("port", 80), "loxone.port", low=1, high=65535),
        loxone_user_secret=str(lox.get("user_secret", "loxone_user")),
        loxone_pass_secret=str(lox.get("pass_secret", "loxone_pass")),
        ha_host=_host(_req(ha, "host", "ha"), "ha.host"),
        ha_port=_int(ha.get("port", 8123), "ha.port", low=1, high=65535),
        webhook_local_only=local_only,
        derived=derived,
        points=points,
    )

    _check_unique([p.name for p in points], "point name")
    _check_unique([p.webhook_id for p in points if p.webhook_id], "webhook_id")
    _check_unique([p.loxone_name for p in points if p.direction == LOXONE_TO_HA], "Loxone command title")
    _check_unique([p.loxone_name for p in points if p.direction == HA_TO_LOXONE], "Loxone input name")
    _check_unique([d.entity_id for d in derived], "derived sensor")
    if not allow_placeholder:
        for p in points:
            if p.webhook_id and PLACEHOLDER_MARK in p.webhook_id:
                raise MappingError(
                    f"point {p.name!r}: webhook_id still contains {PLACEHOLDER_MARK!r} — the id is the only "
                    f"access protection of the webhook; set a random one (e.g. "
                    f"python -c \"import secrets; print(secrets.token_urlsafe(18))\")"
                )
    return mapping


def load_mapping(path: Path, *, allow_placeholder: bool = False) -> BridgeMapping:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MappingError(f"{path}: invalid JSON: {exc}") from exc
    return parse_mapping(raw, allow_placeholder=allow_placeholder)
