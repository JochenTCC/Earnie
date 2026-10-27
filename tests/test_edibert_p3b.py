"""Edibert P3b: engine switch — partial hours (D1), required tariffs (D2), invoice, fingerprint."""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

import config
from data.backtesting_prices import import_brutto_cent_for_slots, pricing_kwargs_from_resolved
from data.edibert_slot_prices import EDIBERT_PRICING_KEY, price_points, pricing_digest
from data.feed_in_prices import enrich_matrix_feed_in_prices, feed_in_settings_from_dict
from house_config.netznutzung import default_netznutzung_config, normalize_netznutzung_config
from house_config.scenario_resolution import resolve_scenario_settings

REPO_ROOT = Path(__file__).resolve().parents[1]
CATALOG = str(REPO_ROOT / "share" / "config" / "tariffs.json")
GRID_FEES = str(REPO_ROOT / "share" / "config" / "grid_fees.json")


@pytest.fixture
def profiles_path(tmp_path) -> Path:
    path = tmp_path / "house_profiles.json"
    path.write_text(
        json.dumps({
            "profiles": [{
                "id": "home",
                "annual_kwh": 4000,
                "land": "AT",
                "latitude": 47.4,
                "longitude": 9.74,
                "timezone_name": "Europe/Vienna",
                "netznutzung": {"area_id": "AT-VBG", "quarter_hour_meter": True},
                "consumers": [],
            }]
        }),
        encoding="utf-8",
    )
    return path


def _resolve(settings: dict, profiles_path: Path, *, tariffs_path: str = CATALOG,
             grid_fees_path: str = GRID_FEES) -> dict:
    return resolve_scenario_settings(
        {"house_profile_id": "home", **settings},
        raw_config=config.CONFIG._raw_config,
        components_path=config.CONFIG.components_path,
        tariffs_path=tariffs_path,
        house_profiles_path=str(profiles_path),
        grid_fees_path=grid_fees_path,
    )


def _quarter_epex(slot: datetime) -> float:
    return round(10.0 + slot.hour + slot.minute / 15 * 0.8, 4)


# --- D1: hourly settled tariffs, horizon starting / ending mid-hour ---------------------


@pytest.mark.parametrize(("import_id", "export_id"), [("awattar_at", "dynamic_epex")])
def test_partial_hours_priced_with_full_hour_mean(profiles_path, import_id, export_id):
    """Horizon 10:30–12:15: the 10:00 and 12:00 hours get their full-hour mean via market_for."""
    resolved = _resolve({"import_tariff_id": import_id, "export_tariff_id": export_id}, profiles_path)
    full = [datetime(2026, 7, 1, 10) + timedelta(minutes=15 * i) for i in range(12)]
    horizon = full[2:9]  # 10:30 … 12:00
    requested: list[datetime] = []

    def market_for(slots: list[datetime]) -> list[float]:
        requested.extend(slots)
        return [_quarter_epex(slot.replace(tzinfo=None)) for slot in slots]

    kwargs = pricing_kwargs_from_resolved(resolved)
    k_act = import_brutto_cent_for_slots(
        [_quarter_epex(s) for s in horizon], horizon, market_for=market_for, **kwargs
    )
    reference = import_brutto_cent_for_slots([_quarter_epex(s) for s in full], full, **kwargs)
    assert k_act == reference[2:9]
    # Only the missing quarter-hours of the partial hours are asked for, as local time.
    assert [slot.replace(tzinfo=None) for slot in requested] == [
        full[0], full[1], full[9], full[10], full[11]
    ]

    matrix = [{"slot_datetime": s, "price_buy": _quarter_epex(s)} for s in horizon]
    enrich_matrix_feed_in_prices(matrix, feed_in_settings_from_dict(resolved), market_for=market_for)
    full_matrix = [{"slot_datetime": s, "price_buy": _quarter_epex(s)} for s in full]
    enrich_matrix_feed_in_prices(full_matrix, feed_in_settings_from_dict(resolved))
    assert [r["k_push_act"] for r in matrix] == [r["k_push_act"] for r in full_matrix[2:9]]


def test_quarter_hour_tariff_asks_for_no_extra_market(profiles_path):
    resolved = _resolve(
        {"import_tariff_id": "at_vkw_strom_dynamisch", "export_tariff_id": "at_vkw_pv_dynamisch"},
        profiles_path,
    )
    slots = [datetime(2026, 7, 1, 10, 30), datetime(2026, 7, 1, 10, 45)]

    def market_for(_slots):
        raise AssertionError("quarter-hour settled tariffs need no extra market prices")

    prices = import_brutto_cent_for_slots(
        [5.0, 6.0], slots, market_for=market_for, **pricing_kwargs_from_resolved(resolved)
    )
    assert len(prices) == 2


def test_live_matrix_passes_market_source(monkeypatch):
    """Live: the matrix asks resolve_market_slots for the quarter-hours outside the horizon."""
    from data import profile_manager

    calls: list[list] = []
    real_resolve = profile_manager.market_prices.resolve_market_slots

    def spy(market_data, target_hours, **kwargs):
        calls.append(list(target_hours))
        return real_resolve(market_data, target_hours, **kwargs)

    captured: dict = {}

    def fake_enrich(slots, slot_datetimes, *, market_for=None, **_kwargs):
        captured["market_for"] = market_for
        for slot in slots:
            slot["k_act"] = 0.0

    monkeypatch.setattr(profile_manager.market_prices, "resolve_market_slots", spy)
    monkeypatch.setattr("data.backtesting_prices.enrich_slots_import_prices", fake_enrich)
    monkeypatch.setattr(profile_manager.feed_in_prices, "enrich_matrix_feed_in_prices",
                        lambda matrix, settings, *, market_for=None: captured.setdefault("export", market_for))
    monkeypatch.setattr(profile_manager, "resolve_market_slots_kwargs", lambda _hours: {})
    start = datetime(2026, 7, 1, 10, 30)
    hours = [start + timedelta(minutes=15 * i) for i in range(4)]
    market = [{"timestamp": datetime(2026, 7, 1, 10) + timedelta(minutes=15 * i), "price_buy": 5.0 + i}
              for i in range(12)]
    profile_manager._build_optimization_matrix(market, [0.1] * 4, [0.0] * 4, target_hours=hours)
    extra = [datetime(2026, 7, 1, 10, 0), datetime(2026, 7, 1, 10, 15)]
    assert captured["market_for"](extra) == [5.0, 6.0]
    assert captured["export"] is captured["market_for"]
    assert calls[-1] == extra


# --- D2: tariffs are required for pricing --------------------------------------------


def test_scenario_without_import_tariff_cannot_be_priced(profiles_path):
    resolved = _resolve({"export_tariff_id": "dynamic_epex"}, profiles_path)
    assert "_import_tariff_spec" not in resolved
    with pytest.raises(ValueError, match="import_tariff_id fehlt"):
        import_brutto_cent_for_slots([5.0], [datetime(2026, 7, 1, 10)], **pricing_kwargs_from_resolved(resolved))


def test_scenario_without_export_tariff_cannot_be_priced(profiles_path):
    resolved = _resolve({"import_tariff_id": "awattar_at"}, profiles_path)
    matrix = [{"slot_datetime": datetime(2026, 7, 1, 10), "price_buy": 5.0}]
    with pytest.raises(KeyError, match="k_push_cent"):
        feed_in_settings_from_dict(resolved)
    settings = feed_in_settings_from_dict({**resolved, "k_push_cent": 0.0})
    with pytest.raises(ValueError, match="export_tariff_id fehlt"):
        enrich_matrix_feed_in_prices(matrix, settings)


@pytest.mark.parametrize("key", ["k_push_cent", "feed_in_mode", "monthly_fixed_feed_in_rates"])
def test_legacy_flat_feed_in_keys_fail_loud(profiles_path, key):
    with pytest.raises(ValueError, match="export_tariff_id"):
        _resolve({"import_tariff_id": "awattar_at", "export_tariff_id": "dynamic_epex", key: 3.5},
                 profiles_path)


def test_tariff_info_carries_catalog_parameters(profiles_path):
    resolved = _resolve(
        {"import_tariff_id": "at_vkw_strom_duo", "export_tariff_id": "at_tiwag_tiwag_einspeisung_fix"},
        profiles_path,
    )
    imp = resolved["_import_tariff_spec"]
    assert imp["type"] == "monthly_table"
    assert imp["monthly_fee_eur"] == pytest.approx(3.0)
    assert imp["monthly_rates"][0] == (2024, 12, 9.4)
    assert resolved["market_zone"] == "AT"
    exp = resolved["_export_tariff_spec"]
    assert resolved["k_push_cent"] == pytest.approx(exp["k_push_cent"])


# --- SE invoice: grid-fee line from Edibert -------------------------------------------


def test_invoice_splits_arbeitspreis_by_time_window(profiles_path):
    from simulation.monthly_fees import ScenarioFeeBreakdown
    from simulation.se_invoice_markdown import render_scenario_invoice_markdown
    from simulation.se_invoice_netznutzung import _grid_fee_from_params

    resolved = _resolve({"import_tariff_id": "awattar_at", "export_tariff_id": "dynamic_epex"},
                        profiles_path)
    idx = pd.DatetimeIndex([datetime(2026, 7, 1, 12, 0), datetime(2026, 7, 1, 18, 0)])
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
        import_spec=resolved["_import_tariff_spec"],
        export_spec=None,
        booked_consumption={"consumption_kwh": 0.5, "standby_kwh": 0.0},
        grid_fee=_grid_fee_from_params(resolved),
    )
    assert "SNAP (Sommer-Nieder-Arbeitspreis)" in body
    # (100 kWh * 3.968 ct + 100 kWh * 4.96 ct) * 1.2 (awattar_at is net: VAT on top) = 10.71 EUR
    assert "| Arbeitspreis (Jahr) | 10.71 € |" in body
    assert "WiNAP (status=entwurf)" in body


def test_invoice_has_no_grid_line_without_reference():
    from simulation.se_invoice_netznutzung import _grid_fee_from_params

    assert _grid_fee_from_params({}) is None
    assert _grid_fee_from_params(None) is None


# --- Fingerprint: catalog content, not only IDs (D4) ----------------------------------


def test_pricing_digest_follows_catalog_content(tmp_path, profiles_path):
    tariffs = tmp_path / "tariffs.json"
    grid = tmp_path / "grid_fees.json"
    shutil.copy(CATALOG, tariffs)
    shutil.copy(GRID_FEES, grid)
    settings = {"import_tariff_id": "at_vkw_strom_duo", "export_tariff_id": "dynamic_epex"}
    ref = _resolve(settings, profiles_path, tariffs_path=str(tariffs),
                   grid_fees_path=str(grid))[EDIBERT_PRICING_KEY]
    before = pricing_digest(ref)

    doc = json.loads(tariffs.read_text(encoding="utf-8"))
    duo = next(t for t in doc["import_tariffs"] if t["id"] == "at_vkw_strom_duo")
    duo["monthly_rates"][0]["tariff_cent_kwh"] += 1.0
    tariffs.write_text(json.dumps(doc), encoding="utf-8")
    assert pricing_digest(ref) != before

    # Same content in another directory: same digest (paths are not part of it).
    other = tmp_path / "other"
    other.mkdir()
    shutil.copy(tariffs, other / "tariffs.json")
    shutil.copy(grid, other / "grid_fees.json")
    moved = {**ref, "tariffs_path": str(other / "tariffs.json"),
             "grid_fees_path": str(other / "grid_fees.json")}
    assert pricing_digest(moved) == pricing_digest(ref)


def test_pricing_digest_follows_grid_rule_set(tmp_path, profiles_path):
    tariffs = tmp_path / "tariffs.json"
    grid = tmp_path / "grid_fees.json"
    shutil.copy(CATALOG, tariffs)
    shutil.copy(GRID_FEES, grid)
    ref = _resolve({"import_tariff_id": "awattar_at", "export_tariff_id": "dynamic_epex"},
                   profiles_path, tariffs_path=str(tariffs),
                   grid_fees_path=str(grid))[EDIBERT_PRICING_KEY]
    before = pricing_digest(ref)
    doc = json.loads(grid.read_text(encoding="utf-8"))
    doc["rule_sets"]["AT_NE7"][0]["effect"]["value"] = 25.0
    grid.write_text(json.dumps(doc), encoding="utf-8")
    assert pricing_digest(ref) != before


# --- Profile field ``netznutzung`` (moved from data/grid_fees.py) ---------------------


def test_netznutzung_config_validation():
    assert normalize_netznutzung_config({"area_id": "AT-VBG"})["include_status"] == ["verordnet"]
    assert default_netznutzung_config()["area_id"] is None
    with pytest.raises(ValueError, match="netznutzung fehlt"):
        normalize_netznutzung_config(None)
    with pytest.raises(ValueError):
        normalize_netznutzung_config({"area_id": "AT-VBG", "include_status": "not-a-list"})
    with pytest.raises(ValueError, match="base_cent_kwh.*migrate_config"):
        normalize_netznutzung_config({"area_id": "AT-VBG", "base_cent_kwh": 1.0})
    with pytest.raises(ValueError, match="area_id fehlt.*migrate_config"):
        normalize_netznutzung_config({"area_id": None})
    with pytest.raises(ValueError):
        normalize_netznutzung_config({"area_id": "AT-VBG", "include_status": ["foo"]})


def test_metered_power_and_missing_meter_flag_are_normalized_away():
    cfg = normalize_netznutzung_config(
        {"area_id": "AT-VBG", "power_metering": "metered_power", "quarter_hour_meter": False}
    )
    assert cfg["power_metering"] == "unmetered_power"
    assert cfg["quarter_hour_meter"] is True


# --- Catalog: Duo covers the day before a run from 2025-01-01 -------------------------


@pytest.mark.parametrize("tariff_id", ["at_vkw_strom_duo", "at_vkw_strom_duo_normalpreis"])
def test_catalog_duo_covers_day_before_2025_run_start(profiles_path, tariff_id):
    """The sunrise window of a run from 2025-01-01 books 2024-12-31 (exact month, no fallback)."""
    resolved = _resolve({"import_tariff_id": tariff_id, "export_tariff_id": "dynamic_epex"},
                        profiles_path)
    warnings: list[str] = []
    points = price_points(
        "import", [datetime(2024, 12, 31, 20)], [None], resolved[EDIBERT_PRICING_KEY],
        warnings_out=warnings,
    )
    assert not any(w.startswith("MONTH_RATE_FALLBACK") for w in warnings)
    assert points[0].supplier_cent == pytest.approx(resolved["_import_tariff_spec"]["monthly_rates"][1][2])


# --- Migration dm5.scenario_feed_in (D2) ----------------------------------------------

MIGRATION_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "migration" / "v5_pre_scenario_feed_in"
Q_EXPORT_FIXED = "dm5.scenario_feed_in.export_tariff_id:flat_fixed"
Q_EXPORT_DYNAMIC = "dm5.scenario_feed_in.export_tariff_id:flat_dynamic"
Q_IMPORT_FIXED = "dm5.scenario_feed_in.import_tariff_id:flat_fixed"
Q_IMPORT_DYNAMIC = "dm5.scenario_feed_in.import_tariff_id:flat_dynamic"
FEED_IN_ANSWERS = {
    Q_EXPORT_FIXED: "__user_fixed__",
    Q_EXPORT_DYNAMIC: "dynamic_epex",
    Q_IMPORT_FIXED: "at_tiwag_flex_privat",
    Q_IMPORT_DYNAMIC: "user_my_fixed",
}


def _migration_copy(tmp_path: Path) -> Path:
    dest = tmp_path / "pack"
    shutil.copytree(MIGRATION_FIXTURE, dest)
    return dest


def test_feed_in_migration_asks_per_flat_scenario(tmp_path):
    from runtime_store.migration import plan_migration

    plan = plan_migration(_migration_copy(tmp_path))
    assert plan.pending_step_ids == ("dm5.scenario_feed_in",)
    by_id = {q.id: q for q in plan.questions}
    assert set(by_id) == set(FEED_IN_ANSWERS)  # tariff_with_leftover needs no answer
    assert all(q.required and q.kind == "choice" for q in by_id.values())
    assert by_id[Q_EXPORT_FIXED].default == "__user_fixed__"
    assert by_id[Q_EXPORT_DYNAMIC].default is None  # dynamic feed-in: no lossless suggestion
    assert by_id[Q_EXPORT_FIXED].choices[0] == "__user_fixed__"
    assert by_id[Q_IMPORT_FIXED].default == "at_tiwag_flex_privat"  # the live import tariff
    assert "user_my_fixed" in by_id[Q_IMPORT_FIXED].choices  # user tariffs count too


def test_feed_in_migration_writes_tariffs_and_drops_flat_keys(tmp_path):
    from runtime_store.migration import plan_migration, run_migration
    from runtime_store.migration.io_util import load_pack_docs
    from runtime_store.migration.validate import validate_migrated_docs

    config_dir = _migration_copy(tmp_path)
    report = run_migration(config_dir, FEED_IN_ANSWERS)
    assert report.applied_step_ids == ("dm5.scenario_feed_in",)
    doc = json.loads((config_dir / "backtesting_scenarios.json").read_text(encoding="utf-8"))
    settings = {s["id"]: s["settings"] for s in doc["scenarios"]}
    assert settings["flat_fixed"]["export_tariff_id"] == "__user_fixed__"
    assert settings["flat_fixed"]["user_export_cent_kwh"] == pytest.approx(3.7)
    assert settings["flat_dynamic"]["export_tariff_id"] == "dynamic_epex"
    assert "user_export_cent_kwh" not in settings["flat_dynamic"]
    for sid in ("flat_fixed", "flat_dynamic", "tariff_with_leftover"):
        assert not {"k_push_cent", "feed_in_mode", "monthly_fixed_feed_in_rates"} & set(settings[sid])
    assert settings["flat_dynamic"]["import_tariff_id"] == "user_my_fixed"
    assert settings["tariff_with_leftover"]["export_tariff_id"] == "dynamic_epex"
    validate_migrated_docs(load_pack_docs(config_dir))
    assert plan_migration(config_dir).pending_step_ids == ()


def test_feed_in_migration_rejects_unknown_tariff(tmp_path):
    from runtime_store.migration import MigrationError, run_migration

    config_dir = _migration_copy(tmp_path)
    with pytest.raises(MigrationError, match="no_such_tariff"):
        run_migration(config_dir, {**FEED_IN_ANSWERS, Q_EXPORT_DYNAMIC: "no_such_tariff"})
