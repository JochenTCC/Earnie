"""Optional consumer keys that feed the Earnie-Points rule (``docs/spec/earnie-points.md``).

* ``bidirectional`` (bool) — only ``ev`` consumers: wallbox can discharge (V2G), 3 points.
* ``appliance_kind`` (str) — only ``generic`` / ``thermal_rc`` consumers; currently
  ``air_conditioner`` (1 heat point).

Both keys are additive and optional: absent means "not set". Invalid values raise.
"""
from __future__ import annotations

APPLIANCE_KIND_AIR_CONDITIONER = "air_conditioner"
APPLIANCE_KINDS = (APPLIANCE_KIND_AIR_CONDITIONER,)
APPLIANCE_KIND_CONSUMER_TYPES = frozenset({"generic", "thermal_rc"})


def _where(profile_id: str, index: int) -> str:
    return f"profiles '{profile_id}' consumers[{index}]"


def _normalize_bidirectional(raw: dict, spec: dict, *, consumer_type: str, where: str) -> None:
    if "bidirectional" not in raw:
        return
    if consumer_type != "ev":
        raise ValueError(f"{where}: bidirectional ist nur für type=ev erlaubt.")
    value = raw["bidirectional"]
    if not isinstance(value, bool):
        raise ValueError(f"{where}: bidirectional muss true oder false sein.")
    spec["bidirectional"] = value


def _normalize_appliance_kind(raw: dict, spec: dict, *, consumer_type: str, where: str) -> None:
    if "appliance_kind" not in raw:
        return
    if consumer_type not in APPLIANCE_KIND_CONSUMER_TYPES:
        raise ValueError(
            f"{where}: appliance_kind ist nur für type=generic oder thermal_rc erlaubt."
        )
    kind = str(raw["appliance_kind"] or "").strip().lower()
    if kind not in APPLIANCE_KINDS:
        raise ValueError(
            f"{where}: appliance_kind '{raw['appliance_kind']}' unbekannt "
            f"(erlaubt: {', '.join(APPLIANCE_KINDS)})."
        )
    spec["appliance_kind"] = kind


def normalize_points_fields(raw: dict, spec: dict, *, profile_id: str, index: int) -> None:
    """Copy and validate ``bidirectional`` / ``appliance_kind`` from ``raw`` into ``spec``."""
    where = _where(profile_id, index)
    consumer_type = str(spec["type"])
    _normalize_bidirectional(raw, spec, consumer_type=consumer_type, where=where)
    _normalize_appliance_kind(raw, spec, consumer_type=consumer_type, where=where)


def serialize_points_fields(consumer: dict, out: dict) -> None:
    """Write the optional keys back when present on the normalized consumer."""
    if "bidirectional" in consumer:
        out["bidirectional"] = bool(consumer["bidirectional"])
    if consumer.get("appliance_kind"):
        out["appliance_kind"] = str(consumer["appliance_kind"])
