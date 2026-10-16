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
    for name in (*HAPPY_SNAPSHOTS, "v3_last"):
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


def test_loxone_names_unknown_answer_blocks(tmp_path):
    config_dir = _copy_snapshot(tmp_path, "v3_single_battery")
    with pytest.raises(MigrationError, match="Unbekannte Antwort"):
        run_migration(config_dir, {Q_NAMES: "vielleicht"})
    assert not (config_dir / "backups").exists()
