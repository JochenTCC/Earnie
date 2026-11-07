"""tf1.grid_area_levies: existing installs get the corrected grid catalog through the wizard."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from house_config.edibert_tariffs import load_grid_fees, profile_grid_fee
from house_config.netznutzung import default_netznutzung_config
from runtime_store.migration import MigrationError, plan_migration, run_migration
from runtime_store.migration.io_util import load_pack_docs
from runtime_store.migration.runner import migrate_docs_unattended
from runtime_store.migration.steps.grid_area_levies import (
    CHOICE_ADD,
    CHOICE_SKIP,
    LEVY_SET_ID,
    Q_PREFIX,
    STEP,
    STEP_ID,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "migration"
SNAPSHOT = "v5_pre_grid_levies"
SHARE_SEED = REPO_ROOT / "share" / "config" / "grid_fees.json"


@pytest.fixture
def config_dir(tmp_path) -> Path:
    dest = tmp_path / SNAPSHOT
    shutil.copytree(FIXTURES / SNAPSHOT, dest)
    return dest


def _read(config_dir: Path) -> dict:
    return json.loads((config_dir / "grid_fees.json").read_text(encoding="utf-8"))


def _write(config_dir: Path, doc: dict) -> None:
    (config_dir / "grid_fees.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


def _area(doc: dict, area_id: str) -> dict:
    return next(area for area in doc["areas"] if area["id"] == area_id)


def _edit_work_price(config_dir: Path, area_id: str = "AT-WIEN", cent: float = 8.1) -> None:
    doc = _read(config_dir)
    _area(doc, area_id)["base_cent_kwh"]["unmetered_power"] = cent
    _write(config_dir, doc)


def _fee(config_dir: Path, area_id: str):
    return profile_grid_fee(
        area_id,
        {"netznutzung": {**default_netznutzung_config(), "area_id": area_id}},
        load_grid_fees(str(config_dir / "grid_fees.json")),
    )


def test_old_seed_becomes_the_corrected_seed_and_stays_done(config_dir):
    plan = plan_migration(config_dir)
    assert plan.pending_step_ids == (STEP_ID,)
    assert plan.questions == ()
    report = run_migration(config_dir, {})
    assert report.applied_step_ids == (STEP_ID,)
    golden = FIXTURES / "goldens" / SNAPSHOT / "grid_fees.json"
    assert _read(config_dir) == json.loads(golden.read_text(encoding="utf-8"))
    assert any(todo.step_id == STEP_ID for todo in report.manual_todos)
    assert plan_migration(config_dir).pending_step_ids == ()
    fee = _fee(config_dir, "AT-VBG")
    assert sum(part.value for part in fee.components) == pytest.approx(1.113)
    assert fee.fixed_eur_year == pytest.approx(76.816)


def test_the_step_writes_what_the_seed_holds_today():
    """Drop this when the seed moves past the 2026 regulations; the golden stays the step's record."""
    golden = FIXTURES / "goldens" / SNAPSHOT / "grid_fees.json"
    assert json.loads(golden.read_text(encoding="utf-8")) == json.loads(SHARE_SEED.read_text(encoding="utf-8"))


def test_a_new_install_never_meets_the_step():
    assert not STEP.detect({"grid_fees.json": json.loads(SHARE_SEED.read_text(encoding="utf-8"))})


def test_edited_work_price_asks_and_blocks_without_an_answer(config_dir):
    _edit_work_price(config_dir)
    plan = plan_migration(config_dir)
    question = next(q for q in plan.questions if q.step_id == STEP_ID)
    assert question.id == f"{Q_PREFIX}AT-WIEN"
    assert question.required
    assert question.choices == (CHOICE_ADD, CHOICE_SKIP)
    assert "8.1" in question.prompt_de and "6.98" in question.prompt_de
    with pytest.raises(MigrationError, match="AT-WIEN"):
        run_migration(config_dir, {})
    assert not (config_dir / "backups").exists()


def test_add_keeps_the_edited_work_price(config_dir):
    _edit_work_price(config_dir)
    run_migration(config_dir, {f"{Q_PREFIX}AT-WIEN": CHOICE_ADD})
    area = _area(_read(config_dir), "AT-WIEN")
    assert area["base_cent_kwh"]["unmetered_power"] == 8.1
    assert area["levy_set"] == LEVY_SET_ID
    assert "check" not in area  # the edited price is not what was checked
    assert plan_migration(config_dir).pending_step_ids == ()


def test_skip_is_recorded_and_not_asked_again(config_dir):
    _edit_work_price(config_dir)
    run_migration(config_dir, {f"{Q_PREFIX}AT-WIEN": CHOICE_SKIP})
    area = _area(_read(config_dir), "AT-WIEN")
    assert area["components"] == []
    assert "levy_set" not in area and "fixed_eur_year" not in area
    plan = plan_migration(config_dir)
    assert plan.pending_step_ids == ()
    assert plan.questions == ()
    fee = _fee(config_dir, "AT-WIEN")
    assert fee.base_cent_kwh == 8.1
    assert fee.components == ()
    assert _fee(config_dir, "AT-VBG").components  # the other areas got theirs


def test_unknown_answer_blocks(config_dir):
    _edit_work_price(config_dir)
    with pytest.raises(MigrationError, match="Unbekannte Antwort"):
        run_migration(config_dir, {f"{Q_PREFIX}AT-WIEN": "vielleicht"})
    assert not (config_dir / "backups").exists()


def test_other_levy_set_of_the_same_id_blocks(config_dir):
    doc = _read(config_dir)
    doc["levy_sets"] = {LEVY_SET_ID: {"label": "x", "components": [{"id": "a", "label": "a", "cent_kwh": 1.0}]}}
    _write(config_dir, doc)
    plan = plan_migration(config_dir)
    assert not plan.can_run
    assert any(LEVY_SET_ID in blocker.message_de for blocker in plan.blockers)


def test_area_outside_the_regulation_and_done_area_stay_untouched(config_dir):
    doc = _read(config_dir)
    other = {**_area(doc, "AT-VBG"), "id": "AT-EIGEN", "label": "Eigen"}
    done = _area(doc, "AT-WIEN")
    done["components"] = [{"id": "own", "label": "Eigen", "cent_kwh": 0.5}]
    doc["areas"].append(other)
    _write(config_dir, doc)
    run_migration(config_dir, {})
    after = _read(config_dir)
    assert _area(after, "AT-EIGEN") == other
    assert _area(after, "AT-WIEN") == done


def test_archived_configs_keep_their_prices(config_dir):
    """Recorder replay and pack import: the prices of a recorded plan do not change afterwards."""
    docs = load_pack_docs(config_dir)
    assert STEP.detect(docs)
    assert migrate_docs_unattended(docs, label="snapshot") == docs
    _edit_work_price(config_dir)  # and an open question does not stop them either
    edited = load_pack_docs(config_dir)
    assert migrate_docs_unattended(edited, label="snapshot") == edited
