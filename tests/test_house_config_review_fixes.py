"""Fixes from the code review of house_config/ and runtime_store/migration/ (2026-11-21)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime_store import persist_paths
from runtime_store.data_model import CURRENT_DATA_MODEL
from runtime_store.migration.chain import apply_chain
from runtime_store.migration.io_util import load_pack_docs, pack_file_paths, replace_pack_docs
from runtime_store.migration.planner import plan_migration
from runtime_store.migration.registry import STEP_BY_ID
from runtime_store.migration.types import MigrationStep, StepResult


def _write(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")


def _clear_earnie_path_env(monkeypatch) -> None:
    """No path override of the test session may leak in: the tests write pack files."""
    import os

    for key in list(os.environ):
        if key.startswith("EARNIE_") and (key.endswith("_PATH") or key == "EARNIE_INSTALL_CONTEXT"):
            monkeypatch.delenv(key)


@pytest.fixture
def sidecar_env(tmp_path, monkeypatch):
    """Active config dir ``cfg`` with the house profile behind ``EARNIE_HOUSE_PROFILES_PATH``."""
    cfg = tmp_path / "cfg"
    side = tmp_path / "side"
    cfg.mkdir()
    side.mkdir()
    _clear_earnie_path_env(monkeypatch)
    monkeypatch.setenv("EARNIE_CONFIG_PATH", str(cfg))
    monkeypatch.setenv("EARNIE_HOUSE_PROFILES_PATH", str(side / "house_profiles.json"))
    persist_paths.clear_sidecar_path_cache()
    yield cfg, side
    persist_paths.clear_sidecar_path_cache()


def test_pack_file_paths_follow_the_sidecar_env_of_the_active_config(sidecar_env):
    cfg, side = sidecar_env
    paths = pack_file_paths(cfg)
    assert paths["house_profiles.json"] == side / "house_profiles.json"
    assert paths["config.json"] == cfg / "config.json"


def test_pack_file_paths_of_another_directory_stay_inside_it(sidecar_env, tmp_path):
    other = tmp_path / "other"
    assert pack_file_paths(other)["house_profiles.json"] == other / "house_profiles.json"


def test_load_and_replace_use_the_sidecar_of_the_active_config(sidecar_env):
    cfg, side = sidecar_env
    _write(cfg / "config.json", {"earnie_data_model": CURRENT_DATA_MODEL})
    _write(side / "house_profiles.json", {"earnie_data_model": 4, "profiles": []})
    docs = load_pack_docs(cfg)
    assert docs["house_profiles.json"]["earnie_data_model"] == 4
    docs["house_profiles.json"]["earnie_data_model"] = CURRENT_DATA_MODEL
    replace_pack_docs(cfg, docs)
    stored = json.loads((side / "house_profiles.json").read_text(encoding="utf-8"))
    assert stored["earnie_data_model"] == CURRENT_DATA_MODEL
    assert not (cfg / "house_profiles.json").exists()


def test_plan_sees_house_profile_steps_behind_the_sidecar_env(sidecar_env):
    cfg, side = sidecar_env
    _write(cfg / "config.json", {"earnie_data_model": 4})
    _write(
        side / "house_profiles.json",
        {"earnie_data_model": 4, "profiles": [{"id": "h", "consumers": []}]},
    )
    plan = plan_migration(cfg)
    assert "dm5.house_thermal" in plan.pending_step_ids


def _openems_pack(model: int) -> dict:
    ev = {
        "id": "e_auto",
        "type": "ev",
        "label": "E-Auto",
        "nominal_power_kw": 11,
        "min_power_kw": 4.1,
        "charging_schedule": {"nominal_power_voltage_v": 230, "nominal_power_phases": 3},
    }
    return {
        "config.json": {
            "earnie_data_model": model,
            "ehal": {"backend": "openems", "openems": {}},
        },
        "components.json": {"earnie_data_model": model},
        "house_profiles.json": {
            "earnie_data_model": model,
            "profiles": [{"id": "h", "consumers": [ev]}],
        },
    }


def test_wallbox_step_keeps_the_openems_evcs0_default_coming_from_data_model_4():
    steps = [STEP_BY_ID["dm5.netznutzung_split"], STEP_BY_ID["dm6.wallboxes"]]
    result = apply_chain(_openems_pack(4), {}, steps)
    assert result.blockers == ()
    wallbox = result.docs["components.json"]["wallboxes"][0]
    assert wallbox["ehal_bindings"]["evcs.e_auto.set_evcs_max_current"] == (
        "evcs0/SetChargePowerLimit"
    )


def _raising_step(where: str) -> MigrationStep:
    def detect(docs):
        if where == "detect":
            raise ValueError("kaputt in detect")
        return True

    def questions_for(docs):
        if where == "questions":
            raise ValueError("kaputt in questions")
        return ()

    def apply(docs, answers):
        if where == "apply":
            raise ValueError("kaputt in apply")
        return StepResult(docs=docs, changed_files=())

    return MigrationStep(
        id="test.raising",
        data_model=CURRENT_DATA_MODEL,
        title_de="Test",
        files=("config.json",),
        detect=detect,
        apply=apply,
        questions_for=questions_for,
    )


@pytest.mark.parametrize("where", ["detect", "questions", "apply"])
def test_step_error_becomes_a_blocker_in_chain_and_plan(tmp_path, where):
    step = _raising_step(where)
    docs = {"config.json": {"earnie_data_model": CURRENT_DATA_MODEL}}
    chain = apply_chain(docs, {}, [step])
    assert [b.step_id for b in chain.blockers] == ["test.raising"]
    assert f"kaputt in {where}" in chain.blockers[0].message_de

    _write(tmp_path / "config.json", docs["config.json"])
    plan = plan_migration(tmp_path, steps=[step])
    assert plan.pending_step_ids == ("test.raising",)
    assert plan.can_run is False
    assert f"kaputt in {where}" in plan.blockers[0].message_de


def test_components_path_for_house_uses_the_active_components_file(tmp_path, monkeypatch):
    from house_config.heating_systems import components_path_for_house

    cfg = tmp_path / "cfg"
    cfg.mkdir()
    components = tmp_path / "data" / "components.json"
    _clear_earnie_path_env(monkeypatch)
    monkeypatch.setenv("EARNIE_CONFIG_PATH", str(cfg))
    monkeypatch.setenv("EARNIE_COMPONENTS_PATH", str(components))
    _write(cfg / "house_profiles.json", {"profiles": []})
    persist_paths.clear_sidecar_path_cache()
    try:
        assert components_path_for_house(str(cfg / "house_profiles.json")) == str(components)
        other = tmp_path / "other" / "house_profiles.json"
        assert components_path_for_house(str(other)) == str(other.parent / "components.json")
    finally:
        persist_paths.clear_sidecar_path_cache()


@pytest.mark.parametrize(
    ("key", "value"), [("land", "IT"), ("land", "D"), ("historical_csv_source", "monitor")]
)
def test_unknown_land_or_csv_source_is_rejected(key, value):
    from house_config.profiles_store import _profile_geo_and_csv_fields

    raw = {"id": "haus", "netznutzung": {"area_id": "AT-NOE"}, key: value}
    with pytest.raises(ValueError, match=key):
        _profile_geo_and_csv_fields(raw)


def test_missing_land_and_csv_source_keep_the_schema_default():
    from house_config.profiles_store import _profile_geo_and_csv_fields

    fields = _profile_geo_and_csv_fields({"id": "haus", "netznutzung": {"area_id": "AT-NOE"}})
    assert fields["land"] == "AT"
    assert fields["historical_csv_source"] == "separate"


def test_shadow_overlay_error_on_components_is_raised(tmp_path, monkeypatch):
    from house_config import components_store
    from runtime_store.shadow import hooks, mode

    path = tmp_path / "components.json"
    _write(path, {"inverters": [], "batteries": [], "pv_systems": []})

    def broken(_doc):
        raise ValueError("overlay kaputt")

    monkeypatch.setattr(mode, "is_shadow_config_readonly", lambda: True)
    monkeypatch.setattr(hooks, "apply_overlay_to_components", broken)
    components_store.clear_components_doc_cache()
    try:
        with pytest.raises(ValueError, match="overlay kaputt"):
            components_store.load_components_document(str(path))
    finally:
        components_store.clear_components_doc_cache()


def _marker_docs(*, hint: str, warning: str, category: str) -> dict:
    return {
        "deviation_rules.json": {
            "earnie_data_model": CURRENT_DATA_MODEL,
            "categories": {"hint": {"color": hint}, "warning": {"color": warning}},
            "rules": [{"id": "battery_forced_charge_target_missed", "category": category}],
        }
    }


def test_marker_colour_step_leaves_own_values_alone():
    from runtime_store.migration.steps import deviation_marker_colors as step

    own = _marker_docs(hint="#123456", warning="#ff8800", category="error")
    assert step.detect(own) is False


def test_marker_colour_step_replaces_only_the_old_shipped_values():
    from runtime_store.migration.steps import deviation_marker_colors as step

    docs = _marker_docs(hint="#123456", warning=step.OLD_WARNING_COLOR, category="error")
    assert step.detect(docs) is True
    doc = step.apply(docs, {}).docs["deviation_rules.json"]
    assert doc["categories"]["hint"]["color"] == "#123456"
    assert doc["categories"]["warning"]["color"] == step.WARNING_COLOR
    assert doc["rules"][0]["category"] == "error"


def test_run_requires_only_the_questions_left_open_by_the_answers(tmp_path):
    """dm4 area answered: the dm5 grid-area question of the dry run no longer applies."""
    import shutil

    from runtime_store.migration.runner import run_migration

    repo = Path(__file__).resolve().parents[1]
    config_dir = tmp_path / "cfg"
    shutil.copytree(repo / "tests/fixtures/migration/v4_pre_inverter_gridfee", config_dir)
    shutil.copy(repo / "share/config/grid_fees.json", config_dir / "grid_fees.json")
    house_path = config_dir / "house_profiles.json"
    house = json.loads(house_path.read_text(encoding="utf-8"))
    for profile in house["profiles"]:
        profile["netznutzung_arbeitspreis_cent_kwh"] = 0
        profile.pop("netznutzung", None)
    _write(house_path, house)

    plan = plan_migration(config_dir)
    dm5 = [q.id for q in plan.questions if q.id.startswith("dm5.netznutzung_split")]
    assert dm5, "the dry run without answers asks for the grid area"
    answers = {
        q.id: (q.default if q.default is not None else q.choices[0])
        for q in plan.questions
        if q.required and q.id not in dm5
    }
    answers["dm4.grid_fee_profile.area_id"] = "AT-NOE"
    run_migration(config_dir, answers)
    stored = json.loads(house_path.read_text(encoding="utf-8"))
    assert [p["netznutzung"]["area_id"] for p in stored["profiles"]] == ["AT-NOE"]


def test_shadow_write_guard_covers_the_house_profile_outside_the_config_dir(sidecar_env):
    from house_config.profiles_store import _refuse_shadow_config_write
    from runtime_store.shadow.errors import ConfigReadOnlyError

    cfg, side = sidecar_env
    with pytest.raises(ConfigReadOnlyError):
        _refuse_shadow_config_write(str(side / "house_profiles.json"))
    with pytest.raises(ConfigReadOnlyError):
        _refuse_shadow_config_write(str(cfg / "house_profiles.json"))
    _refuse_shadow_config_write(str(side / "other_export.json"))
