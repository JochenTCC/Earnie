"""Tests: charge_immediate_name bleibt in der normalisierten Config erhalten."""
from __future__ import annotations

import config


def test_charge_immediate_name_loaded_from_json():
    eauto = next(c for c in config.get_flexible_consumers() if c["id"] == "eauto")
    lox = (eauto.get("charging_schedule") or {}).get("loxone") or {}
    assert lox.get("charge_immediate_name") == "E-Auto_SOFORT_LADEN"
