"""Import cap settings of a scenario: validation, what the grid area means for it, no migration."""
from __future__ import annotations

import json
import shutil
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from edibert.capacity import parse_capacity_charges

import config
from house_config.entity_resolution import strip_assets_for_reference
from house_config.import_cap import (
    IMPORT_CAP_KEY,
    IMPORT_CAP_MARGIN_KEY,
    ImportCap,
    check_import_cap,
    parse_import_cap,
)
from house_config.scenario_resolution import resolve_scenario_settings
from runtime_store.migration.planner import plan_migration

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "backtesting"
TODAY = date(2027, 3, 15)


@pytest.mark.parametrize("settings", [None, {}, {IMPORT_CAP_KEY: None, IMPORT_CAP_MARGIN_KEY: None}])
def test_absent_means_no_cap(settings):
    assert parse_import_cap(settings) is None


def test_cap_and_planned_power():
    cap = parse_import_cap({IMPORT_CAP_KEY: 5, IMPORT_CAP_MARGIN_KEY: 0.3})
    assert cap == ImportCap(5.0, 0.3)
    assert cap.planned_kw == pytest.approx(4.7)


@pytest.mark.parametrize(
    ("settings", "message"),
    [
        ({IMPORT_CAP_KEY: 5.0}, "gehören zusammen"),
        ({IMPORT_CAP_MARGIN_KEY: 0.3}, "gehören zusammen"),
        ({IMPORT_CAP_KEY: 0, IMPORT_CAP_MARGIN_KEY: 0.0}, "muss > 0"),
        ({IMPORT_CAP_KEY: -1.0, IMPORT_CAP_MARGIN_KEY: 0.0}, "muss > 0"),
        ({IMPORT_CAP_KEY: 5.0, IMPORT_CAP_MARGIN_KEY: -0.1}, "muss >= 0"),
        ({IMPORT_CAP_KEY: 5.0, IMPORT_CAP_MARGIN_KEY: 5.0}, "kleiner als"),
        ({IMPORT_CAP_KEY: "5", IMPORT_CAP_MARGIN_KEY: 0.3}, "ungültig"),
        ({IMPORT_CAP_KEY: True, IMPORT_CAP_MARGIN_KEY: 0.3}, "ungültig"),
    ],
)
def test_invalid_values_fail_loud(settings, message):
    with pytest.raises(ValueError, match=message):
        parse_import_cap(settings)


def _charge(**overrides) -> dict:
    return {
        "id": "lp",
        "basis": "monthly_peak_15min",
        "min_kw": 2.0,
        "bands": [{"up_to_kw": None, "cent_per_kw_month": 150}],
        **overrides,
    }


def _fee(*charges: dict, skipped: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        capacity=parse_capacity_charges(list(charges), "test", require_status=False),
        capacity_skipped=skipped or {},
    )


CAP = ImportCap(5.0, 0.3)


def test_cap_without_grid_area_is_refused():
    assert "Netzbereich" in check_import_cap(CAP, None, TODAY).errors[0]


def test_area_without_charge_leaves_the_cap_inactive():
    check = check_import_cap(CAP, _fee(), TODAY)
    assert not check.errors
    assert "inaktiv" in check.notes[0]


def test_note_names_an_entry_that_is_not_released():
    check = check_import_cap(CAP, _fee(skipped={"lp": "entwurf"}), TODAY)
    assert "lp (Status entwurf)" in check.notes[0]


def test_note_names_the_start_month():
    check = check_import_cap(CAP, _fee(_charge(valid_from="2027-12-01")), TODAY)
    assert check.notes == ("Die Grenze bleibt inaktiv bis 12/2027: Dann beginnt der Leistungspreis.",)


def test_running_charge_needs_no_note():
    assert check_import_cap(CAP, _fee(_charge(valid_from="2027-01-01")), TODAY).notes == ()


def test_cap_below_the_minimum_is_refused():
    check = check_import_cap(ImportCap(1.5, 0.0), _fee(_charge()), TODAY)
    assert "Mindestleistung des Netzbereichs (2 kW)" in check.errors[0]


def test_cap_at_the_minimum_is_allowed():
    assert check_import_cap(ImportCap(2.0, 0.0), _fee(_charge()), TODAY).errors == ()


def test_ended_entry_does_not_set_the_minimum():
    fee = _fee(_charge(min_kw=9.0, valid_to="2026-12-31"), _charge(id="neu", valid_from="2027-01-01"))
    assert check_import_cap(CAP, fee, TODAY).errors == ()


def _resolve(tmp_path: Path, settings: dict, *, with_profile: bool = True) -> dict:
    """A profile always has a grid area, so a scenario has none only without a profile."""
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
    return resolve_scenario_settings(
        {
            **({"house_profile_id": "home"} if with_profile else {}),
            "import_tariff_id": "awattar_at",
            "export_tariff_id": "dynamic_epex",
            **settings,
        },
        raw_config=config.CONFIG._raw_config,
        components_path=config.CONFIG.components_path,
        tariffs_path=str(REPO_ROOT / "share" / "config" / "tariffs.json"),
        house_profiles_path=str(path),
        grid_fees_path=str(REPO_ROOT / "share" / "config" / "grid_fees.json"),
    )


CAP_SETTINGS = {IMPORT_CAP_KEY: 5.0, IMPORT_CAP_MARGIN_KEY: 0.3}


def test_resolution_keeps_the_cap(tmp_path):
    assert parse_import_cap(_resolve(tmp_path, CAP_SETTINGS)) == ImportCap(5.0, 0.3)


def test_resolution_refuses_a_cap_without_grid_area(tmp_path):
    with pytest.raises(ValueError, match="import_cap_kw braucht ein Hausprofil"):
        _resolve(tmp_path, CAP_SETTINGS, with_profile=False)


def test_resolution_refuses_an_invalid_cap(tmp_path):
    with pytest.raises(ValueError, match="gehören zusammen"):
        _resolve(tmp_path, {IMPORT_CAP_KEY: 5.0})


def test_resolution_without_profile_or_cap_still_works(tmp_path):
    assert IMPORT_CAP_KEY not in _resolve(tmp_path, {}, with_profile=False)


def test_reference_has_no_cap(tmp_path):
    stripped = strip_assets_for_reference(_resolve(tmp_path, CAP_SETTINGS))
    assert IMPORT_CAP_KEY not in stripped
    assert IMPORT_CAP_MARGIN_KEY not in stripped


def test_scenarios_differing_only_in_the_cap_share_a_reference(tmp_path):
    from house_config.planning_flex_bridge import reference_fingerprint

    with_cap = _resolve(tmp_path, CAP_SETTINGS)
    without = _resolve(tmp_path, {})
    assert reference_fingerprint(strip_assets_for_reference(with_cap)) == reference_fingerprint(
        strip_assets_for_reference(without)
    )


def test_a_changed_cap_makes_se_results_stale(tmp_path):
    from simulation.backtesting_fingerprint import _canonical_scenario_settings

    without = _canonical_scenario_settings(_resolve(tmp_path, {}))
    five = _canonical_scenario_settings(_resolve(tmp_path, CAP_SETTINGS))
    six = _canonical_scenario_settings(_resolve(tmp_path, {**CAP_SETTINGS, IMPORT_CAP_KEY: 6.0}))
    assert without != five != six


def test_the_fields_need_no_migration(tmp_path):
    pack = tmp_path / "config"
    shutil.copytree(FIXTURES, pack)
    before = plan_migration(pack)
    path = pack / "backtesting_scenarios.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["scenarios"][0]["settings"].update(CAP_SETTINGS)
    path.write_text(json.dumps(doc), encoding="utf-8")
    after = plan_migration(pack)
    assert after.pending_step_ids == before.pending_step_ids
    assert after.blockers == before.blockers
    assert after.from_model == before.from_model
    assert not [diff for diff in after.file_diffs if diff not in before.file_diffs]
