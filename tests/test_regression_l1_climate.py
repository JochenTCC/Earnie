"""L1 climate source: shared fixture or the case's own folder (private cases)."""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.regression.climate_fixture import L1_CLIMATE_FIXTURE_DIR, RECORD_ENV
from tests.regression.l1_runner import l1_climate_dir
from tests.regression.loader import RegressionCase
from tests.regression.schema import validate_case_meta


def _meta(**extra) -> dict:
    return {
        "id": "REG-O-c", "title": "t", "level": "L1", "source": "own", "anonymized": False,
        "recorder": {"root": "recorder", "cycle_index": 0}, **extra,
    }


def test_default_is_the_shared_fixture(tmp_path: Path) -> None:
    case = RegressionCase(case_dir=tmp_path, meta=_meta(), expected=None)
    assert l1_climate_dir(case) == L1_CLIMATE_FIXTURE_DIR


def test_case_climate_reads_only_the_case_folder(tmp_path: Path) -> None:
    folder = tmp_path / "climate" / "open_meteo"
    folder.mkdir(parents=True)
    case = RegressionCase(case_dir=tmp_path, meta=_meta(climate="case"), expected=None)
    assert l1_climate_dir(case) == folder


def test_case_climate_missing_fails_loud(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv(RECORD_ENV, raising=False)
    case = RegressionCase(case_dir=tmp_path, meta=_meta(climate="case"), expected=None)
    with pytest.raises(FileNotFoundError, match="climate: case needs"):
        l1_climate_dir(case)


def test_case_climate_folder_created_when_recording(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv(RECORD_ENV, "1")
    case = RegressionCase(case_dir=tmp_path, meta=_meta(climate="case"), expected=None)
    assert l1_climate_dir(case).is_dir()


def test_schema_rejects_an_unknown_climate_source() -> None:
    validate_case_meta(_meta(climate="case"), case_dir_name="REG-O-c")
    with pytest.raises(ValueError, match="climate 'public' invalid"):
        validate_case_meta(_meta(climate="public"), case_dir_name="REG-O-c")
