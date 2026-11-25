"""Loxone recipes suggest the same Merker names the Loxone import binds."""
from __future__ import annotations

import json
from pathlib import Path

from ehal.profiles import list_loxone_recipes, load_loxone_recipe

_MAP = Path(__file__).resolve().parents[1] / "share" / "loxone" / "greenfield_device_map.json"


def test_fixed_recipe_names_match_the_import_map():
    # Docs review 2026-11-25: recipe "Earnie_WR_Leistung_PV" vs. import map "Earnie_PV_Leistung".
    names_by_field: dict[str, set[str]] = {}
    for marker in json.loads(_MAP.read_text(encoding="utf-8"))["markers"]:
        names_by_field.setdefault(marker["ehal_field"], set()).add(marker["name"])
    mismatches = []
    for role_id in list_loxone_recipes():
        for entry in load_loxone_recipe(role_id).get("recommended_markers", []):
            name = entry.get("suggested_name", "")
            field = entry.get("ehal_field")
            if "{" in name or field not in names_by_field:
                continue
            if name not in names_by_field[field]:
                mismatches.append((role_id, field, name, sorted(names_by_field[field])))
    assert not mismatches
