"""Edibert P2: Netznutzung split (dm5.netznutzung_split) and tariff format (tf1.tariff_format)."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from house_config.edibert_tariffs import (
    EDIBERT_TARIFF_FORMAT,
    EDIBERT_TARIFF_TRACK_FILES,
)
from runtime_store.data_model import (
    CURRENT_DATA_MODEL,
    CURRENT_TARIFF_FORMAT,
    TARIFF_TRACK_FILES,
    DataModelError,
)
from runtime_store.migration import MigrationError, plan_migration, run_migration
from runtime_store.migration.io_util import load_pack_docs
from runtime_store.migration.runner import migrate_docs_unattended
from runtime_store.migration.types import HANDOFF_USER_GRID_AREAS
from runtime_store.migration.validate import validate_migrated_docs

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "migration"
NAME = "v4_pre_tariff_track"
Q_B = "dm5.netznutzung_split.area_id:profile_b"
Q_C = "dm5.netznutzung_split.area_id:profile_c"
Q_VAT_IMPORT = "vat_percent:import:user_my_fixed"
Q_VAT_EXPORT = "vat_percent:export:user_my_feed_in"
ANSWERS = {Q_B: "AT-VBG", Q_C: "user_profile_c", Q_VAT_IMPORT: 20, Q_VAT_EXPORT: 0}


def _copy(tmp_path: Path) -> Path:
    dest = tmp_path / NAME
    shutil.copytree(FIXTURES / NAME, dest)
    return dest


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_tracks_match_edibert() -> None:
    assert CURRENT_TARIFF_FORMAT == EDIBERT_TARIFF_FORMAT
    assert TARIFF_TRACK_FILES == frozenset(EDIBERT_TARIFF_TRACK_FILES)
    assert CURRENT_DATA_MODEL == 5


def test_plan_lists_both_steps_and_all_questions(tmp_path: Path) -> None:
    plan = plan_migration(_copy(tmp_path))
    assert plan.can_run, plan.blockers
    assert plan.pending_step_ids == ("dm5.netznutzung_split", "tf1.tariff_format")
    by_id = {q.id: q for q in plan.questions}
    assert set(by_id) == set(ANSWERS)
    assert all(q.required for q in by_id.values())
    # profile_a has an own price > 0: no question, it becomes user_profile_a
    assert "dm5.netznutzung_split.area_id:profile_a" not in by_id
    assert by_id[Q_B].kind == "choice" and "AT-VBG" in by_id[Q_B].choices
    assert by_id[Q_B].choices[-1] == "user_profile_b"
    vat = by_id[Q_VAT_IMPORT]
    assert (vat.kind, vat.default) == ("number", 20.0)
    # Diffs never show the in-memory hand-over
    assert all(d.filename != HANDOFF_USER_GRID_AREAS for d in plan.file_diffs)


def test_one_run_one_backup_matches_golden_and_is_idempotent(tmp_path: Path) -> None:
    config_dir = _copy(tmp_path)
    report = run_migration(config_dir, ANSWERS)
    assert report.applied_step_ids == ("dm5.netznutzung_split", "tf1.tariff_format")
    backups = list((config_dir / "backups").iterdir())
    assert len(backups) == 1 and backups[0].name.startswith("pre-migration-dm4-dm5-")
    golden = FIXTURES / "goldens" / NAME
    for path in sorted(golden.glob("*.json")):
        assert _json(config_dir / path.name) == _json(path), path.name
    validate_migrated_docs(load_pack_docs(config_dir))
    assert plan_migration(config_dir).pending_step_ids == ()


def test_migrated_files_carry_the_right_tracks(tmp_path: Path) -> None:
    config_dir = _copy(tmp_path)
    run_migration(config_dir, ANSWERS)
    for name in ("tariffs.json", "user_tariffs.json", "grid_fees.json", "user_grid_fees.json"):
        doc = _json(config_dir / name)
        assert doc["tariff_format"] == 1 and "earnie_data_model" not in doc, name
    house = _json(config_dir / "house_profiles.json")
    assert house["earnie_data_model"] == 5
    netz = {p["id"]: p["netznutzung"] for p in house["profiles"]}
    assert netz["profile_a"]["area_id"] == "user_profile_a"
    assert netz["profile_b"]["area_id"] == "AT-VBG"
    assert netz["profile_c"]["area_id"] == "user_profile_c"
    assert all("base_cent_kwh" not in n for n in netz.values())
    areas = {a["id"]: a for a in _json(config_dir / "user_grid_fees.json")["areas"]}
    assert areas["user_profile_a"]["base_cent_kwh"] == {"unmetered_power": 5.353, "metered_power": 5.353}
    assert areas["user_profile_c"]["base_cent_kwh"]["unmetered_power"] == 0.0
    assert "user_profile_b" not in areas
    vat = _json(config_dir / "user_tariffs.json")
    assert vat["import_tariffs"][0]["vat_percent"] == 20.0
    assert vat["export_tariffs"][0]["vat_percent"] == 0.0


def test_missing_answers_write_nothing(tmp_path: Path) -> None:
    config_dir = _copy(tmp_path)
    before = {p.name: p.read_bytes() for p in config_dir.glob("*.json")}
    with pytest.raises(MigrationError, match="Fehlende Antworten"):
        run_migration(config_dir, {Q_B: "AT-VBG", Q_C: "user_profile_c"})
    assert {p.name: p.read_bytes() for p in config_dir.glob("*.json")} == before
    assert not (config_dir / "backups").exists()


def test_vat_suggestion_is_never_written_unasked(tmp_path: Path) -> None:
    """The dry-run preview leaves user_tariffs.json alone while its VAT questions are open."""
    plan = plan_migration(_copy(tmp_path))
    assert all(d.filename != "user_tariffs.json" for d in plan.file_diffs)


@pytest.mark.parametrize(
    "answers, message",
    [
        ({**ANSWERS, Q_B: "AT-XX"}, "Unbekannte Antwort"),
        ({**ANSWERS, Q_VAT_IMPORT: -1}, "USt-Satz"),
    ],
)
def test_invalid_answers_block(tmp_path: Path, answers: dict, message: str) -> None:
    with pytest.raises(MigrationError, match=message):
        run_migration(_copy(tmp_path), answers)


def test_existing_user_area_with_other_price_blocks(tmp_path: Path) -> None:
    config_dir = _copy(tmp_path)
    (config_dir / "user_grid_fees.json").write_text(
        json.dumps(
            {
                "tariff_format": 1,
                "rule_sets": {},
                "areas": [
                    {
                        "id": "user_profile_a",
                        "base_cent_kwh": {"unmetered_power": 9.0, "metered_power": 9.0},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    plan = plan_migration(config_dir)
    assert not plan.can_run
    assert any("GRID_ID_COLLISION" in b.message_de for b in plan.blockers)


def test_unattended_migration_needs_answers() -> None:
    docs = load_pack_docs(FIXTURES / NAME)
    with pytest.raises(MigrationError, match="braucht Antworten"):
        migrate_docs_unattended(docs, label="snapshot")


def test_unattended_migration_of_an_own_price_only() -> None:
    """Archived dm4 config with an own price migrates in memory without questions."""
    docs = load_pack_docs(FIXTURES / "goldens" / "v4_pre_topology")
    golden = load_pack_docs(FIXTURES / "goldens" / "v4_pre_topology")
    assert migrate_docs_unattended(docs, label="snapshot") == golden


@pytest.mark.parametrize(
    "netznutzung, message",
    [
        (None, "netznutzung fehlt"),
        ({"area_id": None}, "area_id fehlt"),
        ({"area_id": None, "base_cent_kwh": 5.0}, "base_cent_kwh"),
    ],
)
def test_profile_loader_fails_fast_with_migrate_hint(netznutzung, message) -> None:
    from house_config.profiles_store import normalize_house_profiles_document

    profile = {"id": "h", "label": "H", "land": "AT", "consumers": []}
    if netznutzung is not None:
        profile["netznutzung"] = netznutzung
    with pytest.raises(ValueError, match=f"{message}.*migrate_config"):
        normalize_house_profiles_document({"profiles": [profile]})


def test_tariff_loader_fails_fast_on_untagged_file() -> None:
    from house_config.tariffs_store import load_tariffs_document

    with pytest.raises(DataModelError, match="tariff_format fehlt.*migrate_config"):
        load_tariffs_document(str(FIXTURES / NAME / "tariffs.json"))


def test_own_grid_fee_writes_user_area(tmp_path: Path) -> None:
    from house_config.edibert_tariffs import load_grid_fees, profile_grid_fee
    from house_config.own_grid_fee import OWN_AREA, OWN_BASE_KEY, persist_own_grid_fee

    shutil.copy(Path("share/config/grid_fees.json"), tmp_path / "grid_fees.json")
    netznutzung = {
        "area_id": OWN_AREA,
        OWN_BASE_KEY: 4.2,
        "power_metering": "unmetered_power",
        "quarter_hour_meter": True,
        "include_status": ["verordnet"],
    }
    out = persist_own_grid_fee(
        netznutzung,
        profile_id="home",
        profile_label="Haus",
        land="AT",
        grid_fees_path=str(tmp_path / "grid_fees.json"),
    )
    assert out["area_id"] == "user_home" and OWN_BASE_KEY not in out
    catalog = load_grid_fees(str(tmp_path / "grid_fees.json"), str(tmp_path / "user_grid_fees.json"))
    fee = profile_grid_fee("home", {"netznutzung": out}, catalog)
    assert fee.base_cent_kwh == pytest.approx(4.2)
    # Saving again replaces the same area
    persist_own_grid_fee(
        {**netznutzung, OWN_BASE_KEY: 0.0},
        profile_id="home",
        profile_label="Haus",
        land="AT",
        grid_fees_path=str(tmp_path / "grid_fees.json"),
    )
    areas = _json(tmp_path / "user_grid_fees.json")["areas"]
    assert [a["id"] for a in areas] == ["user_home"]
    assert areas[0]["base_cent_kwh"]["unmetered_power"] == 0.0


def test_catalog_area_is_passed_through_unchanged(tmp_path: Path) -> None:
    from house_config.own_grid_fee import persist_own_grid_fee

    netznutzung = {"area_id": "AT-VBG", "include_status": ["verordnet"]}
    assert persist_own_grid_fee(
        netznutzung, profile_id="home", profile_label="Haus", land="AT",
        grid_fees_path=str(tmp_path / "grid_fees.json"),
    ) == netznutzung  # fmt: skip
    assert not (tmp_path / "user_grid_fees.json").exists()


def _migrated_with_monthly_fee(tmp_path: Path, area_ids: dict[str, str]) -> Path:
    """Migrated golden config, one user tariff with the pre-v0.1.12 ``grid_monthly_fee_eur``."""
    config_dir = tmp_path / NAME
    shutil.copytree(FIXTURES / "goldens" / NAME, config_dir)
    house_path = config_dir / "house_profiles.json"
    house = _json(house_path)
    for profile in house["profiles"]:
        profile["netznutzung"]["area_id"] = area_ids[profile["id"]]
    house_path.write_text(json.dumps(house), encoding="utf-8")
    user_path = config_dir / "user_tariffs.json"
    user = _json(user_path)
    user["import_tariffs"][0]["grid_monthly_fee_eur"] = 3.0
    user_path.write_text(json.dumps(user), encoding="utf-8")
    return config_dir


def test_monthly_grid_fee_moves_into_the_shared_user_area(tmp_path: Path) -> None:
    """Edibert v0.1.12 pin: the fee becomes the fixed amount of the area all profiles use."""
    same = {"profile_a": "user_profile_a", "profile_b": "user_profile_a", "profile_c": "user_profile_a"}
    config_dir = _migrated_with_monthly_fee(tmp_path, same)
    plan = plan_migration(config_dir)
    assert plan.pending_step_ids == ("tf1.tariff_format",) and plan.can_run, plan.blockers
    run_migration(config_dir, {})
    tariff = _json(config_dir / "user_tariffs.json")["import_tariffs"][0]
    assert "grid_monthly_fee_eur" not in tariff
    areas = {a["id"]: a for a in _json(config_dir / "user_grid_fees.json")["areas"]}
    assert "grid_base_fee" in json.dumps(areas["user_profile_a"])
    assert plan_migration(config_dir).pending_step_ids == ()


def test_monthly_grid_fee_without_one_shared_area_blocks(tmp_path: Path) -> None:
    """Profiles on different areas: no target is guessed, the gate shows the blocker."""
    mixed = {"profile_a": "user_profile_a", "profile_b": "AT-VBG", "profile_c": "user_profile_c"}
    config_dir = _migrated_with_monthly_fee(tmp_path, mixed)
    plan = plan_migration(config_dir)
    assert not plan.can_run
    assert any("GRID_MONTHLY_FEE_NO_TARGET" in b.message_de for b in plan.blockers)
    assert any("kein eigener Netzbereich" in b.message_de for b in plan.blockers)
