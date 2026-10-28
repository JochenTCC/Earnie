"""ConfigMigration P1 — registry, chain, planner, runner, goldens."""
from __future__ import annotations

import io
import json
import shutil
import zipfile
from pathlib import Path

import pytest

from runtime_store.config_pack import MANIFEST_NAME, PACK_JSON_FILES, import_config_pack_bytes
from runtime_store.data_model import CURRENT_DATA_MODEL, DATA_MODEL_KEY
from runtime_store.migration import (
    STEPS,
    MigrationError,
    MigrationStep,
    StepResult,
    apply_chain,
    plan_migration,
    run_migration,
)
from runtime_store.migration.io_util import load_pack_docs
from runtime_store.migration.steps.ha_sign import (
    CHOICE_KEEP as SIGN_KEEP,
    CHOICE_REMOVE as SIGN_REMOVE,
    Q_SIGN,
)
from runtime_store.migration.steps.loxone_binding_names import (
    CHOICE_CLEAR,
    CHOICE_KEEP,
    Q_NAMES,
)
from runtime_store.migration.validate import validate_migrated_docs

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "migration"
GOLDENS = FIXTURES / "goldens"

# Goldens keep the Loxone Merker names (dm4.loxone_binding_names "Behalten").
KEEP_NAMES = {Q_NAMES: CHOICE_KEEP}

HAPPY_SNAPSHOTS = (
    "v3_single_battery",
    "v3_pre_ehal",
    "v4_pre_quellenwahl",
    "v4_pre_inverter_gridfee",
    "v4_pre_conversion",
    "v4_pre_topology",
)


def _copy_snapshot(tmp_path: Path, name: str) -> Path:
    dest = tmp_path / name
    shutil.copytree(FIXTURES / name, dest)
    return dest


def _assert_matches_golden(config_dir: Path, name: str) -> None:
    golden_dir = GOLDENS / name
    assert golden_dir.is_dir(), f"missing golden for {name}"
    for path in sorted(golden_dir.iterdir()):
        if not path.is_file():
            continue
        actual = config_dir / path.name
        assert actual.is_file(), f"missing migrated {path.name}"
        assert json.loads(actual.read_text(encoding="utf-8")) == json.loads(
            path.read_text(encoding="utf-8")
        )


@pytest.mark.parametrize("name", HAPPY_SNAPSHOTS)
def test_chain_golden_and_idempotent(tmp_path, name):
    config_dir = _copy_snapshot(tmp_path, name)
    plan = plan_migration(config_dir)
    assert plan.can_run, plan.blockers
    assert plan.pending_step_ids
    report = run_migration(config_dir, KEEP_NAMES)
    assert report.applied_step_ids
    assert Path(report.backup_dir).is_dir()
    assert (Path(report.backup_dir) / "manifest.json").is_file()
    assert (Path(report.backup_dir) / "report.json").is_file()
    validate_migrated_docs(load_pack_docs(config_dir))
    _assert_matches_golden(config_dir, name)

    plan2 = plan_migration(config_dir)
    assert plan2.can_run
    assert plan2.pending_step_ids == ()
    before = {
        p.name: p.read_text(encoding="utf-8")
        for p in config_dir.iterdir()
        if p.is_file() and p.suffix == ".json"
    }
    # Second run is a no-op (no pending steps)
    assert run_migration(config_dir, {}).applied_step_ids == ()
    after = {
        p.name: p.read_text(encoding="utf-8")
        for p in config_dir.iterdir()
        if p.is_file() and p.suffix == ".json"
    }
    assert after == before


def test_v3_last_multi_battery_blocker(tmp_path):
    config_dir = _copy_snapshot(tmp_path, "v3_last")
    plan = plan_migration(config_dir)
    assert not plan.can_run
    assert any(b.step_id == "dm4.v3_to_v4" for b in plan.blockers)
    with pytest.raises(MigrationError, match="batteries"):
        run_migration(config_dir, {})
    # Originals untouched
    original = (FIXTURES / "v3_last" / "components.json").read_text(encoding="utf-8")
    assert (config_dir / "components.json").read_text(encoding="utf-8") == original


def test_meta_every_step_covered_by_fixture_detect(tmp_path):
    covered: set[str] = set()
    for name in (*HAPPY_SNAPSHOTS, "v3_last", "v3_ha_sign", "v4_pre_ha_pull", "v4_pre_se_conf_defaults"):
        docs = load_pack_docs(_copy_snapshot(tmp_path / "meta", name))
        for step in STEPS:
            if step.detect(docs):
                covered.add(step.id)
    assert covered == {step.id for step in STEPS}


def test_per_step_detect_apply_smoke(tmp_path):
    """Each step detect/apply on a fixture that needs it."""
    mapping = {
        "dm4.ehal_bindings": "v3_pre_ehal",
        "dm4.v3_to_v4": "v3_single_battery",
        "dm4.ess_bindings": "v4_pre_quellenwahl",
        "dm4.loxone_binding_names": "v3_single_battery",
        "dm4.inverters": "v4_pre_inverter_gridfee",
        "dm4.conversion_efficiency": "v4_pre_conversion",
        "dm4.topology": "v4_pre_topology",
        "dm4.pool_filter": "v3_single_battery",
        "dm4.grid_fee_profile": "v4_pre_inverter_gridfee",
        "dm4.required_signal_activation": "v4_pre_ha_pull",
        "dm4.ha_pull_removal": "v4_pre_ha_pull",
        "dm4.ha_sign": "v3_ha_sign",
        "dm4.ehal_http_port": "v4_pre_ha_pull",
        "dm4.consumer_flex_bindings": "v4_pre_quellenwahl",
        "dm4.retire_plant_pv_binding": "v4_pre_ha_pull",
        "dm4.se_conf_defaults": "v4_pre_se_conf_defaults",
    }
    for step in STEPS:
        docs = load_pack_docs(_copy_snapshot(tmp_path / step.id, mapping[step.id]))
        assert step.detect(docs), step.id
        result = step.apply(docs, {})
        assert not result.blockers, (step.id, result.blockers)
        assert isinstance(result.docs, dict)


def test_grid_fee_questions_declared():
    step = next(s for s in STEPS if s.id == "dm4.grid_fee_profile")
    assert step.questions
    assert all(not q.required for q in step.questions)


def test_topology_manual_todo(tmp_path):
    config_dir = _copy_snapshot(tmp_path, "v4_pre_topology")
    plan = plan_migration(config_dir)
    assert any(t.step_id == "dm4.topology" for t in plan.manual_todos)


def test_runner_failure_injection_leaves_originals(tmp_path, monkeypatch):
    config_dir = _copy_snapshot(tmp_path, "v4_pre_topology")
    before = {
        p.name: p.read_bytes()
        for p in config_dir.iterdir()
        if p.is_file() and p.suffix == ".json"
    }

    def boom(*_args, **_kwargs):
        raise OSError("injected write failure")

    monkeypatch.setattr(
        "runtime_store.migration.runner.replace_pack_docs", boom
    )
    with pytest.raises(OSError, match="injected"):
        run_migration(config_dir, {})
    after = {
        p.name: p.read_bytes()
        for p in config_dir.iterdir()
        if p.is_file() and p.suffix == ".json"
    }
    assert after == before


def test_dual_track_synthetic_step(tmp_path):
    """Framework can apply a step that writes Earnie + tariff-like files."""
    config_dir = tmp_path / "dual"
    config_dir.mkdir()
    (config_dir / "house_profiles.json").write_text(
        json.dumps(
            {
                DATA_MODEL_KEY: CURRENT_DATA_MODEL,
                "profiles": [
                    {
                        "id": "p",
                        "label": "P",
                        "annual_kwh": 1,
                        "latitude": 47.0,
                        "longitude": 10.0,
                        "consumers": [],
                        "netznutzung": {
                            "area_id": None,
                            "power_metering": "unmetered_power",
                            "quarter_hour_meter": False,
                            "base_cent_kwh": 1.0,
                            "include_status": ["verordnet"],
                        },
                    }
                ],
                "plant": {
                    "grid_meter": {
                        "at_house_connection": True,
                        "single_tariff": True,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    (config_dir / "components.json").write_text(
        json.dumps(
            {
                DATA_MODEL_KEY: CURRENT_DATA_MODEL,
                "inverters": [
                    {
                        "id": "wr_main",
                        "label": "WR",
                        "kind": "hybrid",
                        "efficiency": 0.97,
                    }
                ],
                "batteries": [
                    {
                        "id": "bat",
                        "type": "house",
                        "inverter_id": "wr_main",
                        "regulates_on": "grid",
                        "battery_capacity_kwh": 10,
                    }
                ],
                "pv_systems": [],
            }
        ),
        encoding="utf-8",
    )
    (config_dir / "grid_fees.json").write_text(
        json.dumps({"description": "t", "rule_sets": {}, "areas": []}),
        encoding="utf-8",
    )

    def detect(docs):
        house = docs.get("house_profiles.json") or {}
        profiles = house.get("profiles") or []
        if not profiles:
            return False
        nz = profiles[0].get("netznutzung") or {}
        return nz.get("area_id") is None and "user_area_id" not in (
            docs.get("grid_fees.json") or {}
        )

    def apply(docs, _answers):
        out = {k: dict(v) for k, v in docs.items()}
        house = dict(out["house_profiles.json"])
        profiles = [dict(p) for p in house["profiles"]]
        nz = dict(profiles[0]["netznutzung"])
        nz["area_id"] = "user_test"
        profiles[0]["netznutzung"] = nz
        house["profiles"] = profiles
        out["house_profiles.json"] = house
        fees = dict(out["grid_fees.json"])
        fees["user_area_id"] = "user_test"
        out["grid_fees.json"] = fees
        return StepResult(
            docs=out,
            changed_files=("house_profiles.json", "grid_fees.json"),
        )

    step = MigrationStep(
        id="test.dual_track",
        data_model=4,
        title_de="Synthetic dual-track",
        files=("house_profiles.json", "grid_fees.json"),
        detect=detect,
        apply=apply,
    )
    # Skip production steps that would also detect (pool_filter etc.)
    report = run_migration(config_dir, {}, steps=(step,))
    assert "test.dual_track" in report.applied_step_ids
    fees = json.loads((config_dir / "grid_fees.json").read_text(encoding="utf-8"))
    house = json.loads((config_dir / "house_profiles.json").read_text(encoding="utf-8"))
    assert fees["user_area_id"] == "user_test"
    assert house["profiles"][0]["netznutzung"]["area_id"] == "user_test"
    assert DATA_MODEL_KEY not in fees


def test_pack_import_runs_full_chain(tmp_path, monkeypatch):
    import runtime_store.config_pack as config_pack

    src = _copy_snapshot(tmp_path, "v3_single_battery")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        files = []
        for name, _ in PACK_JSON_FILES:
            path = src / name
            if path.is_file():
                archive.write(path, arcname=name)
                files.append(name)
        manifest = {DATA_MODEL_KEY: 3, "files": files, "created_at": "t"}
        archive.writestr(MANIFEST_NAME, json.dumps(manifest, indent=2) + "\n")
    payload = buf.getvalue()

    dest = tmp_path / "live_config"
    dest.mkdir()

    def _resolver(filename: str):
        return lambda: str(dest / filename)

    monkeypatch.setattr(
        config_pack,
        "PACK_JSON_FILES",
        tuple((name, _resolver(name)) for name, _ in PACK_JSON_FILES),
    )
    monkeypatch.setattr(
        config_pack, "resolve_uploads_dir", lambda: str(dest / "uploads")
    )

    written = import_config_pack_bytes(payload)
    assert "house_profiles.json" in written
    comps = json.loads((dest / "components.json").read_text(encoding="utf-8"))
    assert comps.get(DATA_MODEL_KEY) == CURRENT_DATA_MODEL
    assert comps["batteries"][0].get("regulates_on") == "grid"


def test_apply_chain_stop_on_blocker():
    docs = load_pack_docs(FIXTURES / "v3_last")
    result = apply_chain(docs, {}, STEPS, stop_on_blocker=True)
    assert result.blockers
    assert result.applied_step_ids == () or "dm4.v3_to_v4" not in result.applied_step_ids


def test_untagged_earnie_file_is_blocker(tmp_path):
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    (config_dir / "components.json").write_text(
        json.dumps({"batteries": [], "pv_systems": [], "inverters": []}),
        encoding="utf-8",
    )
    plan = plan_migration(config_dir)
    assert not plan.can_run
    assert any("Version unbekannt" in b.message_de for b in plan.blockers)


def test_cli_dry_run(tmp_path):
    from scripts.migrate_config import main

    config_dir = _copy_snapshot(tmp_path, "v3_last")
    code = main(["--config-dir", str(config_dir), "--dry-run"])
    assert code == 2


@pytest.mark.parametrize("name", (*HAPPY_SNAPSHOTS, "v3_last"))
def test_fixture_scenarios_reference_existing_house_profiles(name):
    """Scrubbed fixtures keep house_profile_id refs in sync with profile ids."""
    for folder in (FIXTURES / name, GOLDENS / name):
        if not folder.is_dir():
            continue
        house = json.loads((folder / "house_profiles.json").read_text(encoding="utf-8"))
        profiles = house["profiles"]
        ids = set(profiles) if isinstance(profiles, dict) else {p["id"] for p in profiles}
        scenarios = json.loads(
            (folder / "backtesting_scenarios.json").read_text(encoding="utf-8")
        )
        refs = {
            sc["settings"]["house_profile_id"]
            for sc in scenarios["scenarios"]
            if sc.get("settings", {}).get("house_profile_id")
        }
        assert refs <= ids, (folder, refs - ids)


def test_run_rejects_unknown_house_profile_ref_before_writing(tmp_path):
    config_dir = _copy_snapshot(tmp_path, "v3_single_battery")
    path = config_dir / "backtesting_scenarios.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["scenarios"][0]["settings"]["house_profile_id"] = "example_efh"
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    before = {p.name: p.read_text(encoding="utf-8") for p in config_dir.glob("*.json")}
    with pytest.raises(ValueError, match="example_efh"):
        run_migration(config_dir, KEEP_NAMES)
    after = {p.name: p.read_text(encoding="utf-8") for p in config_dir.glob("*.json")}
    assert after == before
    assert not (config_dir / "backups").exists()


def _binding_maps(config_dir: Path) -> list[dict]:
    house = json.loads((config_dir / "house_profiles.json").read_text(encoding="utf-8"))
    components = json.loads((config_dir / "components.json").read_text(encoding="utf-8"))
    maps = [(house.get("plant") or {}).get("ehal_bindings") or {}]
    profiles = house.get("profiles")
    for profile in profiles.values() if isinstance(profiles, dict) else profiles:
        for consumer in profile.get("consumers") or []:
            maps.append(consumer.get("ehal_bindings") or {})
    for section in ("batteries", "inverters", "pv_systems"):
        for entity in components.get(section) or []:
            maps.append(entity.get("ehal_bindings") or {})
    return maps


def test_v3_loxone_names_question_is_required(tmp_path):
    config_dir = _copy_snapshot(tmp_path, "v3_single_battery")
    plan = plan_migration(config_dir)
    assert "dm4.loxone_binding_names" in plan.pending_step_ids
    question = next(q for q in plan.questions if q.id == Q_NAMES)
    assert question.required
    assert question.choices == (CHOICE_KEEP, CHOICE_CLEAR)
    with pytest.raises(MigrationError, match=Q_NAMES):
        run_migration(config_dir, {})
    assert not (config_dir / "backups").exists()


def test_v3_loxone_names_clear_keeps_activation_keys(tmp_path):
    keep_dir = _copy_snapshot(tmp_path / "keep", "v3_single_battery")
    clear_dir = _copy_snapshot(tmp_path / "clear", "v3_single_battery")
    run_migration(keep_dir, KEEP_NAMES)
    report = run_migration(clear_dir, {Q_NAMES: CHOICE_CLEAR})
    assert "dm4.loxone_binding_names" in report.applied_step_ids
    assert any(t.step_id == "dm4.loxone_binding_names" for t in report.manual_todos)

    kept = _binding_maps(keep_dir)
    cleared = _binding_maps(clear_dir)
    # Same keys (ESS keys moved onto the battery first), all values empty.
    assert [sorted(m) for m in cleared] == [sorted(m) for m in kept]
    assert any(k.startswith("ess.") for m in cleared for k in m)
    assert all(v == "" for m in cleared for v in m.values())
    assert any(v for m in kept for v in m.values())
    validate_migrated_docs(load_pack_docs(clear_dir))

    plan2 = plan_migration(clear_dir)
    assert plan2.pending_step_ids == ()


def test_loxone_names_question_not_asked_on_v4(tmp_path):
    """Model-4 packs with names (pre-Q8 dev installs) are never asked again."""
    config_dir = _copy_snapshot(tmp_path, "v4_pre_quellenwahl")
    assert any(v for m in _binding_maps(config_dir) for v in m.values())
    plan = plan_migration(config_dir)
    assert "dm4.loxone_binding_names" not in plan.pending_step_ids
    assert all(q.id != Q_NAMES for q in plan.questions)


def test_loxone_names_question_not_asked_for_home_assistant(tmp_path):
    config_dir = _copy_snapshot(tmp_path, "v3_single_battery")
    path = config_dir / "config.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["ehal"] = {"backend": "ha", "adapter_id": "earnie-hems"}
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    plan = plan_migration(config_dir)
    assert "dm4.loxone_binding_names" not in plan.pending_step_ids
    report = run_migration(config_dir, {})
    assert "dm4.loxone_binding_names" not in report.applied_step_ids


def test_loxone_names_unknown_backend_surfaces_error(tmp_path):
    """Regression: typo like 'homeassistant' must not offer the Loxone names step."""
    config_dir = _copy_snapshot(tmp_path, "v3_single_battery")
    path = config_dir / "config.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["ehal"] = {"backend": "homeassistant", "adapter_id": "earnie-hems"}
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    with pytest.raises(ValueError, match="ehal.backend"):
        plan_migration(config_dir)


def test_loxone_names_unknown_answer_blocks(tmp_path):
    config_dir = _copy_snapshot(tmp_path, "v3_single_battery")
    with pytest.raises(MigrationError, match="Unbekannte Antwort"):
        run_migration(config_dir, {Q_NAMES: "vielleicht"})
    assert not (config_dir / "backups").exists()


# --- dm4.ha_sign (issue #56): leftover ehal.ha.sign after 2.6 -> 2.7 -------------------


def _read_config(config_dir: Path) -> dict:
    return json.loads((config_dir / "config.json").read_text(encoding="utf-8"))


def test_ha_sign_question_is_required(tmp_path):
    config_dir = _copy_snapshot(tmp_path, "v3_ha_sign")
    plan = plan_migration(config_dir)
    assert "dm4.ha_sign" in plan.pending_step_ids
    question = next(q for q in plan.questions if q.id == Q_SIGN)
    assert question.required
    assert question.choices == (SIGN_KEEP, SIGN_REMOVE)
    with pytest.raises(MigrationError, match=Q_SIGN):
        run_migration(config_dir, {})
    assert not (config_dir / "backups").exists()


def test_ha_sign_remove_clears_sign_and_leaves_a_todo(tmp_path):
    config_dir = _copy_snapshot(tmp_path, "v3_ha_sign")
    assert _read_config(config_dir)["ehal"]["ha"]["sign"]
    report = run_migration(config_dir, {Q_SIGN: SIGN_REMOVE})
    assert "dm4.ha_sign" in report.applied_step_ids
    assert any(t.step_id == "dm4.ha_sign" for t in report.manual_todos)
    assert _read_config(config_dir)["ehal"]["ha"]["sign"] == {}
    validate_migrated_docs(load_pack_docs(config_dir))
    assert plan_migration(config_dir).pending_step_ids == ()


def test_ha_sign_keep_leaves_the_entry_and_is_not_asked_again(tmp_path):
    config_dir = _copy_snapshot(tmp_path, "v3_ha_sign")
    before = _read_config(config_dir)["ehal"]["ha"]["sign"]
    report = run_migration(config_dir, {Q_SIGN: SIGN_KEEP})
    assert not any(t.step_id == "dm4.ha_sign" for t in report.manual_todos)
    assert _read_config(config_dir)["ehal"]["ha"]["sign"] == before
    plan = plan_migration(config_dir)
    assert plan.pending_step_ids == ()
    assert all(q.id != Q_SIGN for q in plan.questions)


def test_ha_sign_unknown_answer_blocks(tmp_path):
    config_dir = _copy_snapshot(tmp_path, "v3_ha_sign")
    with pytest.raises(MigrationError, match="Unbekannte Antwort"):
        run_migration(config_dir, {Q_SIGN: "vielleicht"})
    assert not (config_dir / "backups").exists()


def test_ha_sign_not_asked_on_v4_packs(tmp_path):
    """Packs already on model 4 (e.g. installs that migrated earlier) are never asked."""
    config_dir = _copy_snapshot(tmp_path, "v4_pre_ha_pull")
    path = config_dir / "config.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["ehal"] = {
        "backend": "ha",
        "adapter_id": "earnie-hems",
        "ha": {"sign": {"sens_ess_power": "negate"}},
    }
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    plan = plan_migration(config_dir)
    assert "dm4.ha_sign" not in plan.pending_step_ids
    assert all(q.id != Q_SIGN for q in plan.questions)


def test_ha_sign_not_asked_for_loxone_or_empty_sign(tmp_path):
    loxone_dir = _copy_snapshot(tmp_path / "lox", "v3_single_battery")
    assert "dm4.ha_sign" not in plan_migration(loxone_dir).pending_step_ids

    empty_dir = _copy_snapshot(tmp_path / "empty", "v3_ha_sign")
    path = empty_dir / "config.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["ehal"]["ha"]["sign"] = {}
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    assert "dm4.ha_sign" not in plan_migration(empty_dir).pending_step_ids


def test_inverters_step_lists_pv_systems_put_on_wr_main(tmp_path):
    """Issue #61: the migration cannot know the PV wiring; the report says what it assumed."""
    config_dir = _copy_snapshot(tmp_path, "v4_pre_inverter_gridfee")
    plan = plan_migration(config_dir)
    todo = next(t for t in plan.manual_todos if t.step_id == "dm4.inverters")
    assert "`dach_nord`" in todo.text_de and "`dach_sued`" in todo.text_de
    assert "wr_main" in todo.text_de and "PV-Felder" in todo.text_de


def test_inverters_todo_absent_when_every_pv_system_has_an_inverter(tmp_path):
    config_dir = _copy_snapshot(tmp_path, "v4_pre_inverter_gridfee")
    path = config_dir / "components.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    for pv in doc["pv_systems"]:
        pv["inverter_id"] = "wr_main"
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    plan = plan_migration(config_dir)
    assert not any(t.step_id == "dm4.inverters" for t in plan.manual_todos)


def test_v3_path_lists_pv_systems_put_on_wr_main(tmp_path):
    """The 2.6 path assigns the PV systems inside dm4.v3_to_v4, not in dm4.inverters."""
    config_dir = _copy_snapshot(tmp_path, "v3_single_battery")
    plan = plan_migration(config_dir)
    todo = next(t for t in plan.manual_todos if t.step_id == "dm4.v3_to_v4")
    assert "`dach_nord`" in todo.text_de and "`dach_sued`" in todo.text_de
    assert "wr_main" in todo.text_de
    report = run_migration(config_dir, KEEP_NAMES)
    assert any(t.step_id == "dm4.v3_to_v4" for t in report.manual_todos)


def test_v3_path_splits_lumped_battery_efficiency(tmp_path):
    """2.6 packs: η_inv was set while creating inverters[], so dm4.conversion_efficiency
    never ran and the storage path got η_inv twice (0.97 · 0.97 instead of 0.97)."""
    config_dir = _copy_snapshot(tmp_path, "v3_single_battery")
    plan = plan_migration(config_dir)
    assert "dm4.conversion_efficiency" in plan.pending_step_ids
    todo = next(t for t in plan.manual_todos if t.step_id == "dm4.conversion_efficiency")
    assert "`10_kwh_speicher`: 0,940 → η_inv 0,970 (`wr_main`) × η_batt 0,969" in todo.text_de
    assert "„Wechselrichter“" in todo.text_de
    run_migration(config_dir, KEEP_NAMES)
    components = json.loads((config_dir / "components.json").read_text(encoding="utf-8"))
    eta_inv = next(i["efficiency"] for i in components["inverters"] if i["id"] == "wr_main")
    eta_batt = components["batteries"][0]["battery_efficiency"]
    assert eta_inv * eta_batt == pytest.approx(0.94)


def test_conversion_todo_absent_when_nothing_was_split(tmp_path):
    config_dir = _copy_snapshot(tmp_path, "v4_pre_topology")
    plan = plan_migration(config_dir)
    assert not any(t.step_id == "dm4.conversion_efficiency" for t in plan.manual_todos)
