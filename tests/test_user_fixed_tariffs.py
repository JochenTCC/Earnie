"""User-fixed import/export tariffs (scenario-local, not tariffs.json)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from data.tariff_pricing import export_cent_kwh, import_cent_kwh
from house_config.tariff_plausibility import collect_scenario_tariff_ref_errors
from house_config.tariffs_store import (
    USER_EXPORT_CENT_KEY,
    USER_FIXED_TARIFF_ID,
    USER_IMPORT_CENT_KEY,
    resolve_export_tariff_into_settings,
    resolve_import_tariff_into_settings,
)
from ui.scenario_form_helpers import build_scenario_settings
from ui.setup_readiness import missing_runtime_scenario_items_for


def _minimal_tariffs() -> dict:
    return {
        "import_tariffs": {
            "catalog_imp": {
                "id": "catalog_imp",
                "label": "Katalog",
                "type": "fixed_cent",
                "fix_cent_kwh": 15.0,
                "prices_include_vat": True,
                "supplier_id": "catalog",
            }
        },
        "export_tariffs": {
            "catalog_exp": {
                "id": "catalog_exp",
                "label": "Katalog",
                "type": "fixed",
                "k_push_cent": 4.0,
                "prices_include_vat": True,
                "supplier_id": "catalog",
            }
        },
    }


def test_resolve_user_fixed_import_adds_netznutzung_no_extra_vat():
    settings = {
        "import_tariff_id": USER_FIXED_TARIFF_ID,
        USER_IMPORT_CENT_KEY: 11.4,
    }
    resolved = resolve_import_tariff_into_settings(settings, _minimal_tariffs())
    assert resolved["import_tariff_type"] == "fixed_cent"
    assert resolved["import_fixed_cent_kwh"] == pytest.approx(11.4)
    assert USER_IMPORT_CENT_KEY not in resolved
    tariff = resolved["_import_tariff_spec"]
    assert tariff["prices_include_vat"] is True
    # Gross supplier price + Netznutzung; no second VAT.
    assert import_cent_kwh(0.0, tariff, netzentgelt_override=5.0) == pytest.approx(16.4)


def test_resolve_user_fixed_export_sets_k_push():
    settings = {
        "export_tariff_id": USER_FIXED_TARIFF_ID,
        USER_EXPORT_CENT_KEY: 7.5,
    }
    resolved = resolve_export_tariff_into_settings(settings, _minimal_tariffs())
    assert resolved["feed_in_mode"] == "fixed"
    assert resolved["k_push_cent"] == pytest.approx(7.5)
    assert USER_EXPORT_CENT_KEY not in resolved
    assert export_cent_kwh(None, resolved["_export_tariff_spec"]) == pytest.approx(7.5)


def test_resolve_user_fixed_import_requires_cent():
    with pytest.raises(ValueError, match=USER_IMPORT_CENT_KEY):
        resolve_import_tariff_into_settings(
            {"import_tariff_id": USER_FIXED_TARIFF_ID},
            _minimal_tariffs(),
        )


def test_build_scenario_settings_keeps_user_cents_only_for_sentinel():
    with_user = build_scenario_settings(
        battery_id="",
        import_tariff_id=USER_FIXED_TARIFF_ID,
        export_tariff_id=USER_FIXED_TARIFF_ID,
        house_profile_id="home",
        user_import_cent_kwh=22.0,
        user_export_cent_kwh=3.0,
    )
    assert with_user[USER_IMPORT_CENT_KEY] == 22.0
    assert with_user[USER_EXPORT_CENT_KEY] == 3.0

    catalog = build_scenario_settings(
        battery_id="",
        import_tariff_id="catalog_imp",
        export_tariff_id="catalog_exp",
        house_profile_id="home",
        user_import_cent_kwh=22.0,
        user_export_cent_kwh=3.0,
    )
    assert USER_IMPORT_CENT_KEY not in catalog
    assert USER_EXPORT_CENT_KEY not in catalog


def _write_tariffs(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "import_tariffs": [
                    {
                        "id": "imp1",
                        "label": "Import",
                        "type": "fixed_cent",
                        "fix_cent_kwh": 20.0,
                        "supplier_id": "x",
                    }
                ],
                "export_tariffs": [
                    {
                        "id": "exp1",
                        "label": "Export",
                        "type": "fixed",
                        "k_push_cent": 5.0,
                        "supplier_id": "x",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_plausibility_accepts_user_fixed_with_cents(tmp_path: Path):
    tariffs = tmp_path / "tariffs.json"
    scenarios = tmp_path / "scenarios.json"
    _write_tariffs(tariffs)
    scenarios.write_text(
        json.dumps(
            {
                "scenarios": [
                    {
                        "id": "live",
                        "settings": {
                            "import_tariff_id": USER_FIXED_TARIFF_ID,
                            USER_IMPORT_CENT_KEY: 18.0,
                            "export_tariff_id": USER_FIXED_TARIFF_ID,
                            USER_EXPORT_CENT_KEY: 0.0,
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    assert collect_scenario_tariff_ref_errors(str(scenarios), str(tariffs)) == []


def test_plausibility_rejects_user_fixed_without_cents(tmp_path: Path):
    tariffs = tmp_path / "tariffs.json"
    scenarios = tmp_path / "scenarios.json"
    _write_tariffs(tariffs)
    scenarios.write_text(
        json.dumps(
            {
                "scenarios": [
                    {
                        "id": "live",
                        "settings": {
                            "import_tariff_id": USER_FIXED_TARIFF_ID,
                            "export_tariff_id": "exp1",
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    errors = collect_scenario_tariff_ref_errors(str(scenarios), str(tariffs))
    assert any(USER_IMPORT_CENT_KEY in err for err in errors)


def test_setup_readiness_accepts_user_fixed(tmp_path: Path):
    tariffs = tmp_path / "tariffs.json"
    components = tmp_path / "components.json"
    profiles = tmp_path / "house_profiles.json"
    scenarios = tmp_path / "scenarios.json"
    _write_tariffs(tariffs)
    components.write_text(
        json.dumps({"batteries": [{"id": "bat1", "label": "B"}]}),
        encoding="utf-8",
    )
    profiles.write_text(
        json.dumps({"profiles": {"home": {"id": "home", "label": "Home"}}}),
        encoding="utf-8",
    )
    scenarios.write_text(
        json.dumps(
            {
                "scenarios": [
                    {
                        "id": "live",
                        "settings": {
                            "battery_ids": ["bat1"],
                            "house_profile_id": "home",
                            "import_tariff_id": USER_FIXED_TARIFF_ID,
                            USER_IMPORT_CENT_KEY: 19.0,
                            "export_tariff_id": USER_FIXED_TARIFF_ID,
                            USER_EXPORT_CENT_KEY: 1.0,
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    raw = {"live_scenario_id": "live"}
    missing = missing_runtime_scenario_items_for(
        raw,
        components_path=str(components),
        tariffs_path=str(tariffs),
        house_profiles_path=str(profiles),
        backtesting_scenarios_path=str(scenarios),
    )
    assert missing == []


def test_setup_readiness_rejects_user_fixed_without_import_cent(tmp_path: Path):
    tariffs = tmp_path / "tariffs.json"
    components = tmp_path / "components.json"
    profiles = tmp_path / "house_profiles.json"
    scenarios = tmp_path / "scenarios.json"
    _write_tariffs(tariffs)
    components.write_text(
        json.dumps({"batteries": [{"id": "bat1", "label": "B"}]}),
        encoding="utf-8",
    )
    profiles.write_text(
        json.dumps({"profiles": {"home": {"id": "home", "label": "Home"}}}),
        encoding="utf-8",
    )
    scenarios.write_text(
        json.dumps(
            {
                "scenarios": [
                    {
                        "id": "live",
                        "settings": {
                            "battery_ids": ["bat1"],
                            "house_profile_id": "home",
                            "import_tariff_id": USER_FIXED_TARIFF_ID,
                            "export_tariff_id": "exp1",
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    missing = missing_runtime_scenario_items_for(
        {"live_scenario_id": "live"},
        components_path=str(components),
        tariffs_path=str(tariffs),
        house_profiles_path=str(profiles),
        backtesting_scenarios_path=str(scenarios),
    )
    assert any("Bezugspreis" in item for item in missing)
