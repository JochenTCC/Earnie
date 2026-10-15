"""Regression P2: private-root discovery, intake, case-local recorder."""
from __future__ import annotations

import gzip
import json
import os
import subprocess
import zipfile
from pathlib import Path

import pytest
import yaml

from tests.regression.intake import IntakeError, intake_debug_dump
from tests.regression.loader import (
    ENV_PRIVATE_CASES_DIR,
    SKIP_PRIVATE_ROOT_MISSING,
    load_case,
    resolve_private_cases_dir,
    resolve_recorder_root,
)
from tests.regression.report import git_sha, write_markdown_report


SEED = "2026-07-16T10:00:00"


def _minimal_cycle(*, seed_anchor: str = SEED) -> dict:
    return {
        "schema": 1,
        "timestamp": "2026-07-16T10:00:00",
        "app_version": "2.7.0-dev",
        "config_hash": "abc123",
        "optimization_matrix": {"n_slots": 1},
        "planning_window": {
            "start": "2026-07-16T10:00:00",
            "end": "2026-07-17T10:00:00",
            "seed_anchor": seed_anchor,
        },
        "start_state": {"soc_percent": 50.0},
        "outputs": {
            "setpoints": {},
            "plan_hash": "deadbeef",
            "flags": {},
        },
    }


def _write_recorder_segment(recorder_dir: Path, entry: dict) -> None:
    recorder_dir.mkdir(parents=True, exist_ok=True)
    segment = recorder_dir / "cycles_2026-07-16.jsonl.gz"
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    with gzip.open(segment, "wb") as handle:
        handle.write(line.encode("utf-8"))
    (recorder_dir / "configs").mkdir(exist_ok=True)
    (recorder_dir / "configs" / "abc123.json").write_text("{}", encoding="utf-8")


def _make_dump_zip(
    tmp_path: Path,
    *,
    with_recorder: bool = True,
    seed_anchor: str = SEED,
) -> Path:
    root = tmp_path / "dump_src"
    (root / "runtime").mkdir(parents=True)
    (root / "runtime" / "optimization_history.jsonl").write_text(
        '{"written_at":"2026-07-16T10:00:00"}\n',
        encoding="utf-8",
    )
    manifest = {
        "schema_version": 3,
        "dump_type": "debug",
        "app_version": "2.7.0-dev",
        "meta": {"title": "Intake test", "symptom": "x", "case_id": ""},
    }
    if with_recorder:
        _write_recorder_segment(root / "recorder", _minimal_cycle(seed_anchor=seed_anchor))
        manifest["recorder"] = {
            "from": "2026-07-16T10:00:00",
            "to": "2026-07-16T10:00:00",
            "cycle_count": 1,
            "config_hashes": ["abc123"],
        }
    (root / "manifest.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )
    zip_path = tmp_path / "debug_dump.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        for path in root.rglob("*"):
            if path.is_file():
                archive.write(path, arcname=path.relative_to(root).as_posix())
    return zip_path


def test_resolve_private_cases_dir_env(tmp_path, monkeypatch):
    cases = tmp_path / "cases"
    cases.mkdir()
    monkeypatch.setenv(ENV_PRIVATE_CASES_DIR, str(cases))
    assert resolve_private_cases_dir() == cases.resolve()


def test_resolve_private_cases_dir_missing(monkeypatch, tmp_path):
    monkeypatch.setenv(ENV_PRIVATE_CASES_DIR, str(tmp_path / "nope"))
    assert resolve_private_cases_dir() is None


def test_report_private_sha_and_skipped(tmp_path, monkeypatch):
    # Inside a git hook GIT_DIR / GIT_INDEX_FILE point at the real repo; without
    # this the git calls below would act on it instead of the tmp repo.
    for key in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(key)
    repo = tmp_path / "priv"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    (repo / "README").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "README"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "i"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    sha = git_sha(repo)
    assert sha != "unknown"
    report = write_markdown_report(
        tmp_path / "report.md",
        results=[],
        public_sha="pub",
        private_sha=sha,
        skipped=[SKIP_PRIVATE_ROOT_MISSING],
    )
    text = report.read_text(encoding="utf-8")
    assert f"Private SHA: `{sha}`" in text
    assert SKIP_PRIVATE_ROOT_MISSING in text


def test_resolve_recorder_root_prefers_case_local(tmp_path):
    from tests.regression.loader import RegressionCase

    case_dir = tmp_path / "REG-1-x"
    local = case_dir / "recorder"
    local.mkdir(parents=True)
    meta = {
        "id": "REG-1-x",
        "title": "t",
        "level": "L1",
        "source": "customer",
        "anonymized": False,
        "recorder": {"root": "recorder", "cycle_index": 0},
    }
    case = RegressionCase(case_dir=case_dir, meta=meta, expected=None)
    assert resolve_recorder_root(case) == local.resolve()


def test_intake_writes_private_case(tmp_path, monkeypatch):
    private_cases = tmp_path / "cases"
    private_cases.mkdir()
    monkeypatch.setenv(ENV_PRIVATE_CASES_DIR, str(private_cases))
    zip_path = _make_dump_zip(tmp_path)
    case_dir = intake_debug_dump(
        zip_path,
        case_id="REG-99-intake-smoke",
        seed_anchor=SEED,
        cycle_index=None,
        private=True,
        issue="JochenTCC/Earnie#99",
    )
    assert case_dir == private_cases / "REG-99-intake-smoke"
    assert (case_dir / "recorder" / "cycles_2026-07-16.jsonl.gz").is_file()
    assert not (case_dir / "expected.json").exists()
    with (case_dir / "case.yaml").open(encoding="utf-8") as handle:
        meta = yaml.safe_load(handle)
    assert meta["source"] == "customer"
    assert meta["anonymized"] is False
    assert meta["recorder"]["root"] == "recorder"
    assert meta["recorder"]["seed_anchor"] == SEED
    assert meta["issue"] == "JochenTCC/Earnie#99"
    case = load_case(case_dir, require_expected=False)
    assert resolve_recorder_root(case) == (case_dir / "recorder").resolve()


def test_intake_requires_private(tmp_path):
    zip_path = _make_dump_zip(tmp_path)
    with pytest.raises(IntakeError, match="--private"):
        intake_debug_dump(
            zip_path,
            case_id="REG-1-x",
            seed_anchor=SEED,
            cycle_index=None,
            private=False,
            private_cases_dir=tmp_path / "cases",
        )


def test_intake_requires_selector(tmp_path):
    zip_path = _make_dump_zip(tmp_path)
    cases = tmp_path / "cases"
    cases.mkdir()
    with pytest.raises(IntakeError, match="seed-anchor or --cycle-index"):
        intake_debug_dump(
            zip_path,
            case_id="REG-1-x",
            seed_anchor=None,
            cycle_index=None,
            private=True,
            private_cases_dir=cases,
        )


def test_intake_rejects_bad_id(tmp_path):
    zip_path = _make_dump_zip(tmp_path)
    cases = tmp_path / "cases"
    cases.mkdir()
    with pytest.raises(IntakeError, match="REG-<issue>"):
        intake_debug_dump(
            zip_path,
            case_id="REG-O-own",
            seed_anchor=SEED,
            cycle_index=None,
            private=True,
            private_cases_dir=cases,
        )


def test_intake_fails_without_recorder(tmp_path):
    zip_path = _make_dump_zip(tmp_path, with_recorder=False)
    cases = tmp_path / "cases"
    cases.mkdir()
    with pytest.raises(IntakeError, match="no recorder"):
        intake_debug_dump(
            zip_path,
            case_id="REG-1-x",
            cycle_index=0,
            seed_anchor=None,
            private=True,
            private_cases_dir=cases,
        )


def test_intake_cycle_index(tmp_path):
    zip_path = _make_dump_zip(tmp_path)
    cases = tmp_path / "cases"
    cases.mkdir()
    case_dir = intake_debug_dump(
        zip_path,
        case_id="REG-7-idx",
        seed_anchor=None,
        cycle_index=0,
        private=True,
        private_cases_dir=cases,
    )
    with (case_dir / "case.yaml").open(encoding="utf-8") as handle:
        meta = yaml.safe_load(handle)
    assert meta["recorder"]["cycle_index"] == 0
