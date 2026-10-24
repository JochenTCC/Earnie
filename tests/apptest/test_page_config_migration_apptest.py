"""AppTest coverage for ConfigMigration P3 wizard (German)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from streamlit.testing.v1 import AppTest

from runtime_store.migration.types import (
    Blocker,
    FileDiff,
    ManualTodo,
    MigrationPlan,
    MigrationReport,
    Question,
)

_SCRIPT = Path(__file__).parent / "scripts" / "run_page_config_migration.py"
_TIMEOUT = 10


def _plan(**overrides) -> MigrationPlan:
    base = dict(
        config_dir="/tmp/earnie-mig-test",
        from_model=3,
        to_model=4,
        pending_step_ids=("dm4.topology",),
        questions=(),
        blockers=(),
        manual_todos=(),
        file_diffs=(),
        can_run=True,
    )
    base.update(overrides)
    return MigrationPlan(**base)


@pytest.fixture
def _mock_pending_plan(monkeypatch):
    plan = _plan(
        pending_step_ids=("dm4.topology",),
        file_diffs=(
            FileDiff(
                filename="house_profiles.json",
                unified_diff="--- a/house_profiles.json\n+++ b/house_profiles.json\n",
            ),
        ),
        manual_todos=(
            ManualTodo(
                step_id="dm4.topology",
                text_de="Bitte grid_meter in der Topologie bestätigen.",
            ),
        ),
        questions=(
            Question(
                id="dm4.grid_fee_profile.area_id",
                step_id="dm4.grid_fee_profile",
                prompt_de="Netzbereich-ID aus grid_fees.json",
                kind="str",
                required=False,
            ),
        ),
    )
    monkeypatch.setattr(
        "ui.pages.page_config_migration.plan_for_active_config",
        lambda: plan,
    )
    return plan


def test_renders_without_exception():
    at = AppTest.from_file(str(_SCRIPT), default_timeout=_TIMEOUT).run()
    assert not at.exception


def test_title_present():
    at = AppTest.from_file(str(_SCRIPT), default_timeout=_TIMEOUT).run()
    assert at.title[0].value == "Konfigurations-Migration"


def test_pending_plan_shows_step_and_hint(monkeypatch, _mock_pending_plan):
    at = AppTest.from_file(str(_SCRIPT), default_timeout=_TIMEOUT).run()
    assert not at.exception
    assert any("Datenmodell 3 → 4" in w.value for w in at.warning)
    assert any("dm4.topology" in md.value for md in at.markdown)
    assert any(b.label == "Backup anlegen und migrieren" for b in at.button)


def test_same_model_hint_avoids_arrow(monkeypatch):
    """In-model detect steps must not show confusing „Datenmodell 4 → 4“."""
    plan = _plan(
        from_model=4,
        to_model=4,
        pending_step_ids=("dm4.topology",),
    )
    monkeypatch.setattr(
        "ui.pages.page_config_migration.plan_for_active_config",
        lambda: plan,
    )
    at = AppTest.from_file(str(_SCRIPT), default_timeout=_TIMEOUT).run()
    assert not at.exception
    assert any(
        "strukturelle Schritte innerhalb Datenmodell 4" in w.value for w in at.warning
    )
    assert not any("Datenmodell 4 → 4" in w.value for w in at.warning)


def test_blockers_disable_migrate(monkeypatch):
    plan = _plan(
        can_run=False,
        blockers=(
            Blocker(
                step_id="dm4.v3_to_v4",
                message_de="Mehrere Batterien — bitte Support kontaktieren.",
            ),
        ),
        pending_step_ids=("dm4.v3_to_v4",),
    )
    monkeypatch.setattr(
        "ui.pages.page_config_migration.plan_for_active_config",
        lambda: plan,
    )
    at = AppTest.from_file(str(_SCRIPT), default_timeout=_TIMEOUT).run()
    assert not at.exception
    assert any(
        "Mehrere Batterien" in e.value for e in at.error
    )
    migrate = [b for b in at.button if b.label == "Backup anlegen und migrieren"]
    assert len(migrate) == 1
    assert migrate[0].disabled is True


def test_question_prompt_visible(monkeypatch, _mock_pending_plan):
    at = AppTest.from_file(str(_SCRIPT), default_timeout=_TIMEOUT).run()
    assert not at.exception
    labels = [t.label for t in at.text_input]
    assert any("Netzbereich-ID" in label for label in labels)


def test_mocked_migrate_shows_report(monkeypatch, _mock_pending_plan):
    report = MigrationReport(
        backup_dir="/tmp/backups/pre-migration-dm3-dm4-test",
        applied_step_ids=("dm4.topology",),
        manual_todos=(
            ManualTodo(
                step_id="dm4.topology",
                text_de="Bitte grid_meter in der Topologie bestätigen.",
            ),
        ),
        written_files=("house_profiles.json",),
    )
    monkeypatch.setattr(
        "ui.pages.page_config_migration.run_migration",
        MagicMock(return_value=report),
    )
    monkeypatch.setattr(
        "ui.pages.page_config_migration.continue_after_migration",
        MagicMock(),
    )
    at = AppTest.from_file(str(_SCRIPT), default_timeout=_TIMEOUT).run()
    assert not at.exception
    migrate = [b for b in at.button if b.label == "Backup anlegen und migrieren"]
    assert migrate
    at = migrate[0].click().run()
    assert not at.exception
    assert any("Migration abgeschlossen" in s.value for s in at.success)
    assert any(
        "pre-migration-dm3-dm4-test" in md.value for md in at.markdown
    )
    assert any(b.label == "Weiter zur App" for b in at.button)


def test_required_choice_starts_empty_and_is_passed_on(monkeypatch):
    question = Question(
        id="loxone_binding_names.keep",
        step_id="dm4.loxone_binding_names",
        prompt_de="Alte Loxone-Merkernamen behalten?",
        kind="choice",
        required=True,
        choices=("Behalten", "Leeren"),
    )
    plan = _plan(
        pending_step_ids=("dm4.loxone_binding_names",),
        questions=(question,),
    )
    monkeypatch.setattr(
        "ui.pages.page_config_migration.plan_for_active_config",
        lambda: plan,
    )
    run = MagicMock(
        return_value=MigrationReport(
            backup_dir="/tmp/backups/x",
            applied_step_ids=("dm4.loxone_binding_names",),
            manual_todos=(),
            written_files=("components.json",),
        )
    )
    monkeypatch.setattr("ui.pages.page_config_migration.run_migration", run)
    monkeypatch.setattr(
        "ui.pages.page_config_migration.continue_after_migration",
        MagicMock(),
    )
    at = AppTest.from_file(str(_SCRIPT), default_timeout=_TIMEOUT).run()
    assert not at.exception
    box = next(b for b in at.selectbox if "Merkernamen" in b.label)
    assert box.value is None
    at = box.select("Leeren").run()
    migrate = [b for b in at.button if b.label == "Backup anlegen und migrieren"]
    at = migrate[0].click().run()
    assert not at.exception
    call = run.call_args
    answers = call.args[1] if len(call.args) > 1 else call.kwargs["answers"]
    assert answers["loxone_binding_names.keep"] == "Leeren"


def _open_report(monkeypatch, continue_mock):
    """Run the mocked migration up to the report view."""
    report = MigrationReport(
        backup_dir="/tmp/backups/pre-migration-dm3-dm4-test",
        applied_step_ids=("dm4.topology",),
        manual_todos=(),
        written_files=("house_profiles.json",),
    )
    monkeypatch.setattr(
        "ui.pages.page_config_migration.run_migration",
        MagicMock(return_value=report),
    )
    monkeypatch.setattr(
        "ui.pages.page_config_migration.continue_after_migration", continue_mock
    )
    at = AppTest.from_file(str(_SCRIPT), default_timeout=_TIMEOUT).run()
    migrate = [b for b in at.button if b.label == "Backup anlegen und migrieren"]
    return migrate[0].click().run()


def _info_texts(at) -> str:
    return " ".join(i.value for i in at.info)


def test_report_tells_that_main_is_not_running_yet_with_auto_start(
    monkeypatch, _mock_pending_plan
):
    """Issue #61: the daemon starts only via "Weiter zur App"; say so on the report."""
    monkeypatch.setenv("EARNIE_AUTO_START_MAIN", "1")
    at = _open_report(monkeypatch, MagicMock())
    assert not at.exception
    text = _info_texts(at)
    assert "läuft noch nicht" in text and "Weiter zur App" in text
    assert "Container neu starten" in text


def test_report_tells_to_start_main_manually_without_auto_start(
    monkeypatch, _mock_pending_plan
):
    monkeypatch.setenv("EARNIE_AUTO_START_MAIN", "0")
    at = _open_report(monkeypatch, MagicMock())
    assert not at.exception
    assert "Auto-Start ist aus" in _info_texts(at)


def test_continue_failure_shows_error_and_keeps_the_report(monkeypatch, _mock_pending_plan):
    from runtime_store.main_daemon import DaemonError

    at = _open_report(monkeypatch, MagicMock(side_effect=DaemonError("Lock belegt")))
    at = next(b for b in at.button if b.label == "Weiter zur App").click().run()
    assert not at.exception
    assert any("main.py konnte nicht gestartet werden: Lock belegt" in e.value for e in at.error)
    assert any("Migration abgeschlossen" in s.value for s in at.success)
    assert any(b.label == "Weiter zur App" for b in at.button)
