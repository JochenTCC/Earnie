"""Optional consumer keys that feed the Earnie-Points rule (``docs/workflow/earnie-points.md``).

* ``bidirectional`` (bool) — only ``ev`` consumers: wallbox can discharge (V2G), 3 points.

The key is optional: absent means "not set". Invalid values raise. The former
``appliance_kind: air_conditioner`` is gone: the air conditioning is the ``cooling`` block of
the house's heating consumer (``house_config.house_cooling``, migration dm5.house_cooling).
"""
from __future__ import annotations

LEGACY_APPLIANCE_KIND_KEY = "appliance_kind"
_MIGRATE_HINT = (
    "Konfiguration migrieren (Streamlit-Seite „Konfigurations-Migration“ oder "
    "python -m scripts.migrate_config --config-dir <config>)"
)


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


def _reject_appliance_kind(raw: dict, *, where: str) -> None:
    if LEGACY_APPLIANCE_KIND_KEY in raw:
        raise ValueError(
            f"{where}: appliance_kind gibt es nicht mehr. Eine Klimaanlage wird im "
            "Hauskonfigurator beim Haus-Wärme-Verbraucher eingetragen (Kühlung) — "
            f"{_MIGRATE_HINT}."
        )


def normalize_points_fields(raw: dict, spec: dict, *, profile_id: str, index: int) -> None:
    """Copy and validate ``bidirectional`` from ``raw`` into ``spec``."""
    where = _where(profile_id, index)
    _reject_appliance_kind(raw, where=where)
    _normalize_bidirectional(raw, spec, consumer_type=str(spec["type"]), where=where)


def serialize_points_fields(consumer: dict, out: dict) -> None:
    """Write the optional key back when present on the normalized consumer."""
    if "bidirectional" in consumer:
        out["bidirectional"] = bool(consumer["bidirectional"])
