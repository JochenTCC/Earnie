"""Zeitabhängiges Netznutzungsentgelt (SNAP/WiNAP): Katalog, Regeln, Preisintegration."""
from __future__ import annotations

import copy
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from data.grid_fees import (
    flat_grid_fee_spec,
    grid_fee_work_cent,
    load_grid_fee_catalog,
    matching_rule,
    normalize_grid_fee_catalog,
    normalize_netznutzung_config,
    resolve_grid_fee_spec,
)
from data.tariff_pricing import import_cent_kwh

VIENNA = ZoneInfo("Europe/Vienna")
CATALOG_PATH = Path(__file__).resolve().parents[1] / "share" / "config" / "grid_fees.json"


def _catalog() -> dict:
    return load_grid_fee_catalog(str(CATALOG_PATH))


def _spec(**overrides) -> dict:
    cfg = {"area_id": "AT-VBG", "quarter_hour_meter": True}
    cfg.update(overrides)
    return resolve_grid_fee_spec(cfg, _catalog(), timezone_name="Europe/Vienna")


def test_bundled_catalog_is_valid_and_complete():
    catalog = _catalog()
    assert len(catalog["areas"]) == 14
    vbg = catalog["areas"]["AT-VBG"]
    assert vbg["base_cent_kwh"] == {"unmetered_power": 4.96, "metered_power": 2.84}
    ids = [rule["id"] for rule in catalog["rule_sets"]["AT_NE7"]]
    assert ids == ["SNAP", "WiNAP"]


def test_snap_reduces_base_by_20_percent_in_window_only():
    spec = _spec()
    assert grid_fee_work_cent(spec, datetime(2026, 7, 1, 10, 0, tzinfo=VIENNA)) == pytest.approx(3.968)
    assert grid_fee_work_cent(spec, datetime(2026, 7, 1, 15, 45, tzinfo=VIENNA)) == pytest.approx(3.968)
    assert grid_fee_work_cent(spec, datetime(2026, 7, 1, 16, 0, tzinfo=VIENNA)) == pytest.approx(4.96)
    assert grid_fee_work_cent(spec, datetime(2026, 7, 1, 9, 45, tzinfo=VIENNA)) == pytest.approx(4.96)
    # Winter, same hour: no SNAP
    assert grid_fee_work_cent(spec, datetime(2026, 12, 1, 12, 0, tzinfo=VIENNA)) == pytest.approx(4.96)
    # Before the rule becomes valid
    assert grid_fee_work_cent(spec, datetime(2026, 3, 31, 12, 0, tzinfo=VIENNA)) == pytest.approx(4.96)


def test_snap_skipped_without_quarter_hour_meter_and_reported():
    spec = _spec(quarter_hour_meter=False)
    assert spec["rules"] == []
    reasons = {item["id"]: item["reason"] for item in spec["skipped"]}
    assert reasons["SNAP"] == "kein Viertelstundenzähler"
    assert grid_fee_work_cent(spec, None) == pytest.approx(4.96)


def test_metered_power_uses_other_base():
    spec = _spec(power_metering="metered_power")
    assert spec["base_cent_kwh"] == pytest.approx(2.84)


def test_draft_rule_without_value_is_skipped_by_default_and_fails_loud_when_included():
    spec = _spec()
    assert {"id": "WiNAP", "reason": "status=entwurf"} in spec["skipped"]
    with pytest.raises(ValueError, match="WiNAP"):
        _spec(include_status=["verordnet", "entwurf"])


def test_winap_window_wraps_midnight(monkeypatch):
    catalog = copy.deepcopy(_catalog())
    for rule in catalog["rule_sets"]["AT_NE7"]:
        if rule["id"] == "WiNAP":
            rule["effect"]["value"] = 20.0
    spec = resolve_grid_fee_spec(
        {"area_id": "AT-VBG", "quarter_hour_meter": True, "include_status": ["verordnet", "entwurf"]},
        catalog,
        timezone_name="Europe/Vienna",
    )
    for hour, minute, expected in [(22, 0, 3.968), (23, 45, 3.968), (0, 0, 3.968), (3, 45, 3.968), (4, 0, 4.96), (21, 45, 4.96)]:
        value = grid_fee_work_cent(spec, datetime(2027, 1, 15, hour, minute, tzinfo=VIENNA))
        assert value == pytest.approx(expected), (hour, minute)
    assert matching_rule(spec, datetime(2027, 1, 15, 23, 0, tzinfo=VIENNA))["id"] == "WiNAP"


def test_slot_in_other_timezone_is_converted_to_local_time():
    spec = _spec()
    # 08:00 UTC in July = 10:00 Vienna (CEST)
    utc_slot = datetime(2026, 7, 1, 8, 0, tzinfo=ZoneInfo("UTC"))
    assert grid_fee_work_cent(spec, utc_slot) == pytest.approx(3.968)


def test_time_rules_require_slot_datetime():
    with pytest.raises(ValueError, match="slot_datetime"):
        grid_fee_work_cent(_spec(), None)


def test_manual_base_without_area_has_no_rules():
    spec = resolve_grid_fee_spec(
        {"base_cent_kwh": 5.0}, None, timezone_name="Europe/Vienna"
    )
    assert spec["rules"] == []
    assert grid_fee_work_cent(spec, None) == pytest.approx(5.0)


def test_unknown_area_fails_loud():
    with pytest.raises(ValueError, match="Unbekannter Netzbereich"):
        resolve_grid_fee_spec({"area_id": "AT-XX"}, _catalog(), timezone_name="Europe/Vienna")
    with pytest.raises(ValueError, match="kein Netzentgelt-Katalog"):
        resolve_grid_fee_spec({"area_id": "AT-VBG"}, None, timezone_name="Europe/Vienna")


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda d: d["rule_sets"]["AT_NE7"][0].update(status="foo"), "status"),
        (lambda d: d["rule_sets"]["AT_NE7"][0].update(requires=["x"]), "requires"),
        (lambda d: d["rule_sets"]["AT_NE7"][0]["time"].update({"to": "10:00"}), "nicht gleich"),
        (lambda d: d["rule_sets"]["AT_NE7"][0]["effect"].update(mode="bad"), "effect.mode"),
        (lambda d: d["rule_sets"]["AT_NE7"][0]["effect"].update(value=150), "0–100"),
        (lambda d: d["areas"][0].update(rule_set="nope"), "unbekannten rule_set"),
    ],
)
def test_catalog_validation_rejects_bad_input(mutate, message):
    doc = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    mutate(doc)
    with pytest.raises(ValueError, match=message):
        normalize_grid_fee_catalog(doc)


def test_netznutzung_config_validation():
    assert normalize_netznutzung_config(None)["include_status"] == ["verordnet"]
    with pytest.raises(ValueError):
        normalize_netznutzung_config({"power_metering": "x"})
    with pytest.raises(ValueError):
        normalize_netznutzung_config({"base_cent_kwh": -1})
    with pytest.raises(ValueError):
        normalize_netznutzung_config({"include_status": ["foo"]})


def test_import_price_follows_time_window_and_vat_applies_after():
    spec = _spec()
    tariff = {
        "type": "spot_hourly",
        "settlement_fee_cent_kwh": 0.0,
        "markup_percent": 0.0,
        "prices_include_vat": False,
        "vat_percent": 20.0,
    }
    midday = import_cent_kwh(10.0, tariff, grid_fee=spec, slot_datetime=datetime(2026, 7, 1, 12, 0, tzinfo=VIENNA))
    evening = import_cent_kwh(10.0, tariff, grid_fee=spec, slot_datetime=datetime(2026, 7, 1, 18, 0, tzinfo=VIENNA))
    assert midday == pytest.approx((10.0 + 3.968) * 1.2)
    assert evening == pytest.approx((10.0 + 4.96) * 1.2)
    with pytest.raises(ValueError, match="slot_datetime"):
        import_cent_kwh(10.0, tariff, grid_fee=spec)


def test_flat_spec_needs_no_slot():
    tariff = {"type": "fixed_cent", "fix_cent_kwh": 20.0, "prices_include_vat": True}
    assert import_cent_kwh(0.0, tariff, grid_fee=flat_grid_fee_spec(5.0)) == pytest.approx(25.0)


def test_legacy_profile_scalar_is_rejected_and_migrated():
    from house_config.profiles_store import _normalize_profile
    from scripts.migrate_grid_fee_profile import migrate_document

    legacy = {
        "id": "home",
        "label": "Home",
        "annual_kwh": 4000,
        "latitude": 48.2,
        "longitude": 16.3,
        "netznutzung_arbeitspreis_cent_kwh": 5.353,
        "consumers": [],
    }
    with pytest.raises(ValueError, match="migrate_grid_fee_profile"):
        _normalize_profile(copy.deepcopy(legacy), 0)
    doc = {"profiles": [copy.deepcopy(legacy)]}
    assert migrate_document(doc, area_id="AT-VBG", quarter_hour_meter=True) == 1
    profile = _normalize_profile(doc["profiles"][0], 0)
    assert profile["netznutzung"]["area_id"] == "AT-VBG"
    assert profile["netznutzung"]["base_cent_kwh"] == pytest.approx(5.353)
    assert "netznutzung_arbeitspreis_cent_kwh" not in profile


def test_invoice_splits_arbeitspreis_by_time_window():
    from simulation.monthly_fees import ScenarioFeeBreakdown
    from simulation.se_invoice_markdown import render_scenario_invoice_markdown

    idx = pd.DatetimeIndex(
        [datetime(2026, 7, 1, 12, 0), datetime(2026, 7, 1, 18, 0)], tz="Europe/Vienna"
    )
    df = pd.DataFrame(
        {
            "import_cost_eur": [10.0, 10.0],
            "export_earn_eur": [0.0, 0.0],
            "import_kwh": [100.0, 100.0],
            "export_kwh": [0.0, 0.0],
            "consumption_kw": [1.0, 1.0],
            "k_act": [12.0, 12.0],
            "k_push_act": [0.0, 0.0],
        },
        index=idx,
    )
    body = render_scenario_invoice_markdown(
        scenario_id="s",
        label="S",
        df=df,
        fees=ScenarioFeeBreakdown(),
        import_spec={"id": "fix", "label": "Fix", "type": "fixed_cent", "prices_include_vat": True},
        export_spec=None,
        grid_fee=_spec(),
    )
    assert "SNAP (Sommer-Nieder-Arbeitspreis)" in body
    # 100 kWh * 3.968 ct + 100 kWh * 4.96 ct = 8.93 EUR
    assert "| Arbeitspreis (Jahr) | 8.93 € |" in body
    assert "WiNAP (status=entwurf)" in body
