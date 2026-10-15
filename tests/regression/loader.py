"""Discover and load regression cases from case directories."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from tests.regression.schema import validate_case_meta, validate_expected

REGRESSION_ROOT = Path(__file__).resolve().parent
DEFAULT_CASES_DIR = REGRESSION_ROOT / "cases"


@dataclass(frozen=True)
class RegressionCase:
    """One golden-master case on disk."""

    case_dir: Path
    meta: dict[str, Any]
    expected: dict[str, Any] | None

    @property
    def id(self) -> str:
        return str(self.meta["id"])

    @property
    def level(self) -> str:
        return str(self.meta["level"])


def discover_case_dirs(*roots: Path) -> list[Path]:
    found: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.iterdir()):
            if path.is_dir() and (path / "case.yaml").is_file():
                found.append(path)
    return found


def load_case(case_dir: Path, *, require_expected: bool = True) -> RegressionCase:
    meta_path = case_dir / "case.yaml"
    if not meta_path.is_file():
        raise FileNotFoundError(f"case.yaml missing: {meta_path}")
    with meta_path.open(encoding="utf-8") as handle:
        meta = yaml.safe_load(handle)
    validate_case_meta(meta, case_dir_name=case_dir.name)
    expected: dict[str, Any] | None = None
    expected_path = case_dir / "expected.json"
    if expected_path.is_file():
        with expected_path.open(encoding="utf-8") as handle:
            expected = json.load(handle)
        validate_expected(expected, case_id=case_dir.name)
    elif require_expected:
        raise FileNotFoundError(
            f"expected.json missing for {case_dir.name} "
            f"(use --update-golden to create it)"
        )
    return RegressionCase(case_dir=case_dir, meta=meta, expected=expected)


def load_cases(
    *roots: Path,
    case_ids: set[str] | None = None,
    require_expected: bool = True,
) -> list[RegressionCase]:
    cases: list[RegressionCase] = []
    for case_dir in discover_case_dirs(*roots):
        if case_ids is not None and case_dir.name not in case_ids:
            continue
        cases.append(load_case(case_dir, require_expected=require_expected))
    if case_ids is not None:
        found = {c.id for c in cases}
        missing = sorted(case_ids - found)
        if missing:
            raise FileNotFoundError(f"requested cases not found: {missing}")
    return cases


def resolve_recorder_root(case: RegressionCase) -> Path:
    """Resolve ``recorder.root`` relative to ``tests/regression/``."""
    raw = str(case.meta["recorder"]["root"])
    path = Path(raw)
    if not path.is_absolute():
        path = REGRESSION_ROOT / path
    if not path.is_dir():
        raise FileNotFoundError(
            f"recorder root missing for {case.id}: {path}"
        )
    return path
