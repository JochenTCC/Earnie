"""User-fixed import/export tariffs (scenario-local, not tariffs.json)."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from data.edibert_slot_prices import export_cents, import_cents, pricing_reference
from house_config.edibert_tariffs import EDIBERT_TARIFF_FORMAT, flat_user_grid_area
from house_config.scenario_resolution import _pop_user_fixed_cents, _user_fixed_vat
from house_config.tariff_plausibility import collect_scenario_tariff_ref_errors
from house_config.tariffs_store import (
    USER_EXPORT_CENT_KEY,
    USER_FIXED_TARIFF_ID,
    USER_IMPORT_CENT_KEY,
)
from ui.scenario_form_helpers import build_scenario_settings
from ui.setup_readiness import missing_runtime_scenario_items_for

SLOT = datetime(2026, 1, 15, 12)  # no time rules in a flat user area


def _minimal_tariffs() -> dict:
    return {
        "tariff_format": 1,
        "import_tariffs": {
            "catalog_imp": {
                "id": "catalog_imp",
                "land": "AT",
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
                "land": "AT",
                "label": "Katalog",
                "type": "fixed",
                "k_push_cent": 4.0,
                "prices_include_vat": True,
                "supplier_id": "catalog",
            }
        },
    }


def _user_fixed_ref(tmp_path, land: str, *, import_cent=None, export_cent=None) -> dict:
    """Pricing reference with Eigener Festpreis and a flat 5 ct user grid area."""
    (tmp_path / "tariffs.json").write_text(
        json.dumps({"tariff_format": EDIBERT_TARIFF_FORMAT, "import_tariffs": [], "export_tariffs": []}),
        encoding="utf-8",
    )
    (tmp_path / "grid_fees.json").write_text(
        json.dumps({"tariff_format": EDIBERT_TARIFF_FORMAT, "rule_sets": {}, "areas": []}),
        encoding="utf-8",
    )
    area = flat_user_grid_area("user_home", 5.0, label="Home", land=land)
    (tmp_path / "user_grid_fees.json").write_text(
        json.dumps({"tariff_format": EDIBERT_TARIFF_FORMAT, "rule_sets": {}, "areas": [area]}),
        encoding="utf-8",
    )
    profile = {"land": land, "netznutzung": {"area_id": "user_home", "quarter_hour_meter": True}}
    user_fixed = {}
    if import_cent is not None:
        user_fixed["import"] = {"cent": import_cent, "vat_percent": _user_fixed_vat(profile)}
    if export_cent is not None:
        user_fixed["export"] = {"cent": export_cent, "vat_percent": 0.0}
    return pricing_reference(
        tariffs_path=str(tmp_path / "tariffs.json"),
        grid_fees_path=str(tmp_path / "grid_fees.json"),
        import_tariff_id=USER_FIXED_TARIFF_ID if import_cent is not None else None,
        export_tariff_id=USER_FIXED_TARIFF_ID if export_cent is not None else None,
        timezone_name="Europe/Vienna",
        profile=profile,
        user_fixed=user_fixed,
    )


@pytest.mark.parametrize(
    ("land", "vat", "expected"),
    [("AT", 20.0, 11.4 + 5.0 * 1.2), ("DE", 19.0, 11.4 + 5.0 * 1.19), ("CH", 8.1, 11.4 + 5.0 * 1.081)],
)
def test_user_fixed_import_gets_land_vat_on_netznutzung(tmp_path, land, vat, expected):
    ref = _user_fixed_ref(tmp_path, land, import_cent=11.4)
    assert ref["user_fixed"]["import"]["vat_percent"] == vat
    assert import_cents([SLOT], [None], ref) == [pytest.approx(expected)]


def test_user_fixed_import_without_profile_has_no_vat_rate():
    """No house profile → no grid fee, so the gross price needs no VAT rate."""
    assert _user_fixed_vat(None) == 0.0


def test_user_fixed_vat_rejects_unknown_land():
    with pytest.raises(ValueError, match="USt"):
        _user_fixed_vat({"land": "FR"})


def test_user_fixed_export_price(tmp_path):
    ref = _user_fixed_ref(tmp_path, "AT", export_cent=7.5)
    assert export_cents([SLOT], [None], ref) == [pytest.approx(7.5)]


def test_user_fixed_cents_leave_settings():
    settings = {USER_IMPORT_CENT_KEY: 11.4, USER_EXPORT_CENT_KEY: 7.5}
    cents = _pop_user_fixed_cents(settings, USER_FIXED_TARIFF_ID, USER_FIXED_TARIFF_ID)
    assert cents == {"import": 11.4, "export": 7.5}
    assert settings == {}
    catalog = {USER_IMPORT_CENT_KEY: 11.4}
    assert _pop_user_fixed_cents(catalog, "catalog_imp", None) == {}
    assert catalog == {}


def test_resolve_user_fixed_import_requires_cent():
    with pytest.raises(ValueError, match=USER_IMPORT_CENT_KEY):
        _pop_user_fixed_cents({}, USER_FIXED_TARIFF_ID, None)


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
                "tariff_format": 1,
                "import_tariffs": [
                    {
                        "id": "imp1",
                        "land": "AT",
                        "label": "Import",
                        "type": "fixed_cent",
                        "fix_cent_kwh": 20.0,
                        "supplier_id": "x",
                    }
                ],
                "export_tariffs": [
                    {
                        "id": "exp1",
                        "land": "AT",
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
        json.dumps(
            {"profiles": {"home": {"id": "home", "label": "Home", "netznutzung": {"area_id": "AT-VBG"}}}}
        ),
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
        json.dumps(
            {"profiles": {"home": {"id": "home", "label": "Home", "netznutzung": {"area_id": "AT-VBG"}}}}
        ),
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
