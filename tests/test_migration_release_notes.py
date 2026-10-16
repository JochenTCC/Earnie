"""Unit tests for scripts.migration_release_notes (ConfigMigration P4)."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from runtime_store.migration.types import MigrationStep, Question, StepResult
from scripts.migration_release_notes import (
    format_migration_section,
    new_steps,
    previous_step_ids,
    step_ids_from_source,
)


def _noop_detect(_docs: dict) -> bool:
    return False


def _noop_apply(docs: dict, _answers: dict) -> StepResult:
    return StepResult(docs=docs, changed_files=())


def _step(step_id: str, title: str, *, questions: tuple[Question, ...] = ()) -> MigrationStep:
    return MigrationStep(
        id=step_id,
        data_model=4,
        title_de=title,
        files=("components.json",),
        detect=_noop_detect,
        apply=_noop_apply,
        questions=questions,
    )


def test_step_ids_from_source_parses_step_id_and_id():
    source = '''
STEP_ID = "dm4.example"
STEP = MigrationStep(
    id="dm4.other",
    data_model=4,
)
'''
    assert step_ids_from_source(source) == frozenset({"dm4.example", "dm4.other"})


def test_new_steps_keeps_registry_order():
    a = _step("dm4.a", "A")
    b = _step("dm4.b", "B")
    c = _step("dm4.c", "C")
    current = (a, b, c)
    assert new_steps(current, frozenset({"dm4.a"})) == (b, c)


def test_format_migration_section_empty():
    text = format_migration_section(())
    assert text.startswith("## Migration")
    assert "Keine neuen Migrationsschritte" in text
    assert "backups/pre-migration-dm" in text
    assert "Kein Downgrade" in text


def test_format_migration_section_with_questions():
    step = _step(
        "dm4.grid_fee_profile",
        "Netznutzung-Profil",
        questions=(
            Question(
                id="dm4.grid_fee_profile.area_id",
                step_id="dm4.grid_fee_profile",
                prompt_de="Netzbereich wählen",
                kind="str",
                required=True,
            ),
        ),
    )
    text = format_migration_section((step,))
    assert "`dm4.grid_fee_profile`" in text
    assert "Netznutzung-Profil" in text
    assert "Netzbereich wählen" in text
    assert "`components.json`" in text
    assert "Manuelle To-dos" in text


def test_previous_step_ids_empty_when_registry_absent_at_rev():
    with patch(
        "scripts.migration_release_notes._git_rev_exists",
        return_value=True,
    ), patch(
        "scripts.migration_release_notes.git_show",
        return_value=None,
    ):
        assert previous_step_ids("v0.0.0") == frozenset()


def test_previous_step_ids_unknown_rev_fails_loud():
    with patch(
        "scripts.migration_release_notes._git_rev_exists",
        return_value=False,
    ):
        with pytest.raises(ValueError, match="unknown git revision"):
            previous_step_ids("not-a-real-tag-xyz")
