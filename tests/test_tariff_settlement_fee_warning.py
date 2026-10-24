"""settlement_fee_cent_kwh only acts on spot import types; others warn once."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from house_config import tariffs_store
from house_config.tariffs_store import normalize_tariffs_document

_CATALOG = Path(__file__).resolve().parents[1] / "share" / "config" / "tariffs.json"

_FIXED = {
    "id": "fix1",
    "type": "fixed_cent",
    "fix_cent_kwh": 12.0,
    "supplier_id": "sup",
    "land": "AT",
}
_SPOT = {
    "id": "spot1",
    "type": "spot_hourly",
    "supplier_id": "sup",
    "land": "AT",
}


@pytest.fixture(autouse=True)
def _reset_warned() -> None:
    tariffs_store._warned_ignored_settlement_fee.clear()
    tariffs_store._warned_gross_without_vat.clear()


def _load(tariff: dict, caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    with caplog.at_level(logging.WARNING, logger=tariffs_store.logger.name):
        normalize_tariffs_document({"import_tariffs": [tariff]})
    return [r for r in caplog.records if "settlement_fee_cent_kwh" in r.getMessage()]


def test_fixed_tariff_with_fee_warns_and_points_to_netznutzung(caplog) -> None:
    records = _load({**_FIXED, "settlement_fee_cent_kwh": 9.08}, caplog)
    assert len(records) == 1
    assert "netznutzung" in records[0].getMessage()
    assert "fix1" in records[0].getMessage()


def test_monthly_table_with_fee_warns(caplog) -> None:
    tariff = {
        "id": "mt1",
        "type": "monthly_table",
        "monthly_rates": [{"year": 2026, "month": 8, "tariff_cent_kwh": 12.0}],
        "supplier_id": "sup",
        "land": "AT",
        "settlement_fee_cent_kwh": 1.0,
    }
    assert len(_load(tariff, caplog)) == 1


@pytest.mark.parametrize("fee", [None, 0.0])
def test_fixed_tariff_without_effective_fee_does_not_warn(caplog, fee) -> None:
    tariff = dict(_FIXED)
    if fee is not None:
        tariff["settlement_fee_cent_kwh"] = fee
    assert _load(tariff, caplog) == []


def test_spot_tariff_with_fee_does_not_warn(caplog) -> None:
    assert _load({**_SPOT, "settlement_fee_cent_kwh": 1.5}, caplog) == []


def test_warning_is_logged_once_per_tariff(caplog) -> None:
    tariff = {**_FIXED, "settlement_fee_cent_kwh": 2.0}
    assert len(_load(tariff, caplog)) == 1
    caplog.clear()
    assert _load(tariff, caplog) == []


def test_shipped_catalog_loads_without_warning(caplog) -> None:
    doc = json.loads(_CATALOG.read_text(encoding="utf-8-sig"))
    with caplog.at_level(logging.WARNING, logger=tariffs_store.logger.name):
        normalize_tariffs_document(doc)
    assert [r for r in caplog.records if "settlement_fee_cent_kwh" in r.getMessage()] == []


def _vat_records(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if "vat_percent fehlt" in r.getMessage()]


def test_gross_import_without_vat_percent_warns(caplog) -> None:
    with caplog.at_level(logging.WARNING, logger=tariffs_store.logger.name):
        normalize_tariffs_document({"import_tariffs": [{**_FIXED, "prices_include_vat": True}]})
    assert len(_vat_records(caplog)) == 1


@pytest.mark.parametrize(
    "extra",
    [
        {"prices_include_vat": True, "vat_percent": 20.0},
        {"prices_include_vat": False},
    ],
)
def test_import_with_vat_rate_or_net_prices_does_not_warn(caplog, extra) -> None:
    with caplog.at_level(logging.WARNING, logger=tariffs_store.logger.name):
        normalize_tariffs_document({"import_tariffs": [{**_FIXED, **extra}]})
    assert _vat_records(caplog) == []
