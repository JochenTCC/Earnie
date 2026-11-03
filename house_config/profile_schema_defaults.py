"""Soft defaults of house profile fields, read from ``house_profiles.schema.json``.

The bundled schema (``share/config``) is the single home of HK defaults: UI widgets
seed empty fields from it and normalizers fill missing keys from it. A getter for a
field without ``"default"`` raises instead of guessing.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache

_SCHEMA_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "share",
    "config",
    "house_profiles.schema.json",
)
_TYPE_DEFAULTS_KEY = "x-earnie-type-defaults"


@lru_cache(maxsize=1)
def _definitions() -> dict:
    with open(_SCHEMA_PATH, "r", encoding="utf-8") as handle:
        return json.load(handle)["definitions"]


def _property(definition: str, key: str) -> dict:
    props = _definitions()[definition].get("properties") or {}
    prop = props.get(key)
    if not isinstance(prop, dict):
        raise KeyError(f"house_profiles.schema.json: {definition}.{key} fehlt.")
    return prop


def schema_default(definition: str, key: str, *, consumer_type: str | None = None):
    """``"default"`` of ``definitions.<definition>.properties.<key>``.

    ``consumer_type`` picks a per-type value from ``x-earnie-type-defaults`` first.
    """
    prop = _property(definition, key)
    if consumer_type is not None:
        typed = prop.get(_TYPE_DEFAULTS_KEY) or {}
        if consumer_type in typed:
            return typed[consumer_type]
    if "default" not in prop:
        raise KeyError(
            f"house_profiles.schema.json: {definition}.{key} hat keinen \"default\"."
        )
    return prop["default"]


def profile_default(key: str):
    return schema_default("profile", key)


def consumer_default(key: str, *, consumer_type: str | None = None):
    return schema_default("consumer", key, consumer_type=consumer_type)


def house_thermal_default(key: str):
    return schema_default("house_thermal", key)


def thermal_rc_default(key: str):
    return schema_default("thermal_rc_params", key)


def heat_storage_default(key: str):
    return schema_default("heat_storage", key)


def ev_schedule_default(key: str):
    return schema_default("ev_charging_schedule", key)
