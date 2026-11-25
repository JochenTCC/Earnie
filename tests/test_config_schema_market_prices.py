"""Every `market_prices` field documented in preise.md is in config.schema.json."""
from __future__ import annotations

import json
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def _documented_fields() -> set[str]:
    text = (_ROOT / "docs" / "konfiguration" / "preise.md").read_text(encoding="utf-8")
    section = text.split("Block `market_prices` in `config.json`:", 1)[1].split("\n\n", 2)[1]
    return set(re.findall(r"^\| `([a-z_]+)` \|", section, flags=re.MULTILINE))


def test_documented_market_prices_fields_are_in_the_schema():
    # Docs review 2026-11-23: live_bias_* were documented and read, but missing in the schema.
    schema = json.loads((_ROOT / "share" / "config" / "config.schema.json").read_text(encoding="utf-8"))
    properties = set(schema["definitions"]["market_prices"]["properties"])
    documented = _documented_fields()
    assert documented, "preise.md market_prices table not found"
    assert documented <= properties, sorted(documented - properties)
