"""Every catalog tariff carries a ``land``; the shipped / fixture catalogs comply."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from house_config.tariffs_store import normalize_tariffs_document

_ROOT = Path(__file__).resolve().parents[1]
_CATALOGS = [
    _ROOT / "share" / "config" / "tariffs.json",
    _ROOT / "share" / "config" / "tariffs.example.json",
    _ROOT / "share" / "config" / "tariffs.minimal.json",
    _ROOT / "tests" / "fixtures" / "backtesting" / "tariffs.json",
]

_IMPORT_FIXED = {
    "id": "t1",
    "type": "fixed_cent",
    "fix_cent_kwh": 25.0,
    "supplier_id": "sup",
    "land": "AT",
}
_EXPORT_FIXED = {
    "id": "t2",
    "type": "fixed",
    "k_push_cent": 3.0,
    "supplier_id": "sup",
    "land": "AT",
}


def _without_land(tariff: dict) -> dict:
    return {k: v for k, v in tariff.items() if k != "land"}


def test_tariffs_with_land_are_accepted() -> None:
    doc = normalize_tariffs_document(
        {"import_tariffs": [_IMPORT_FIXED], "export_tariffs": [_EXPORT_FIXED]}
    )
    assert doc["import_tariffs"]["t1"]["land"] == "AT"


@pytest.mark.parametrize("kind", ["import_tariffs", "export_tariffs"])
def test_fixed_tariff_without_land_is_rejected(kind: str) -> None:
    tariff = _IMPORT_FIXED if kind == "import_tariffs" else _EXPORT_FIXED
    with pytest.raises(ValueError, match=rf"{kind}\[0\] .*land fehlt"):
        normalize_tariffs_document({kind: [_without_land(tariff)]})


@pytest.mark.parametrize("path", _CATALOGS, ids=lambda p: p.name)
def test_shipped_and_fixture_catalogs_give_every_tariff_a_land(path: Path) -> None:
    doc = json.loads(path.read_text(encoding="utf-8-sig"))
    missing = [
        t["id"]
        for key in ("import_tariffs", "export_tariffs")
        for t in doc.get(key, [])
        if not t.get("land")
    ]
    assert missing == []
    normalize_tariffs_document(doc)
