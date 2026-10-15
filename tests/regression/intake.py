"""Intake: schema-v3 debug-dump ZIP → private L1 regression case."""
from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

import yaml

from runtime_store.cycle_recorder import read_segment_cycles
from runtime_store.debug_dump_archive import extract_dump_to_dir, validate_dump_layout
from tests.regression.loader import resolve_private_cases_dir
from tests.regression.schema import validate_case_meta

CUSTOMER_CASE_ID_RE = re.compile(r"^REG-\d+-[a-z0-9-]+$")


class IntakeError(ValueError):
    """Fail-loud intake error (bad ZIP, missing recorder, bad ID, …)."""


def validate_customer_case_id(case_id: str) -> None:
    if not CUSTOMER_CASE_ID_RE.match(case_id):
        raise IntakeError(
            f"case id {case_id!r} must match REG-<issue>-<slug> "
            f"(e.g. REG-142-eauto-deadline)"
        )


def intake_debug_dump(
    zip_path: Path,
    *,
    case_id: str,
    seed_anchor: str | None,
    cycle_index: int | None,
    private: bool,
    issue: str | None = None,
    title: str | None = None,
    force: bool = False,
    private_cases_dir: Path | None = None,
) -> Path:
    """
    Turn a debug-dump ZIP into a private L1 case folder.

    Requires ``--private`` and either ``seed_anchor`` or ``cycle_index``.
    Does not write ``expected.json`` (use ``--update-golden`` afterwards).
    """
    if not private:
        raise IntakeError(
            "--intake for customer dumps requires --private "
            "(refuses writing into the public cases tree)"
        )
    if seed_anchor is None and cycle_index is None:
        raise IntakeError("intake requires --seed-anchor or --cycle-index")
    if seed_anchor is not None and cycle_index is not None:
        raise IntakeError("pass only one of --seed-anchor or --cycle-index")
    validate_customer_case_id(case_id)

    cases_root = private_cases_dir or resolve_private_cases_dir()
    if cases_root is None:
        raise IntakeError(
            "private cases dir missing; clone Earnie-regression-private as a "
            "sibling or set EARNIE_REGRESSION_PRIVATE_DIR"
        )

    case_dir = cases_root / case_id
    if case_dir.exists() and not force:
        raise IntakeError(
            f"case dir already exists: {case_dir} (pass --force to overwrite)"
        )

    with tempfile.TemporaryDirectory(prefix="reg_intake_") as tmp:
        extract_root = extract_dump_to_dir(zip_path, Path(tmp) / "extract")
        manifest = validate_dump_layout(extract_root)
        recorder_src = extract_root / "recorder"
        if not recorder_src.is_dir():
            raise IntakeError(
                "dump has no recorder/ tree; use a schema-v3 dump with the "
                "cycle recorder enabled (no synthetic fallback)"
            )
        segments = sorted(recorder_src.glob("cycles_*.jsonl.gz"))
        if not segments:
            raise IntakeError(f"no cycles_*.jsonl.gz under {recorder_src}")
        entries = _load_cycles(recorder_src)
        if not entries:
            raise IntakeError(
                f"recorder/ contains no cycle entries under {recorder_src}"
            )
        _assert_selector(entries, seed_anchor=seed_anchor, cycle_index=cycle_index)

        if case_dir.exists() and force:
            shutil.rmtree(case_dir)
        case_dir.mkdir(parents=True, exist_ok=False)
        shutil.copytree(recorder_src, case_dir / "recorder")

        meta = _build_case_yaml(
            case_id=case_id,
            manifest=manifest,
            seed_anchor=seed_anchor,
            cycle_index=cycle_index,
            issue=issue,
            title=title,
        )
        validate_case_meta(meta, case_dir_name=case_id)
        with (case_dir / "case.yaml").open("w", encoding="utf-8") as handle:
            yaml.safe_dump(meta, handle, sort_keys=False, allow_unicode=True)
        return case_dir


def _load_cycles(recorder_root: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for segment in sorted(recorder_root.glob("cycles_*.jsonl.gz")):
        entries.extend(read_segment_cycles(segment))
    return entries


def _assert_selector(
    entries: list[dict[str, Any]],
    *,
    seed_anchor: str | None,
    cycle_index: int | None,
) -> None:
    if seed_anchor is not None:
        for entry in entries:
            window = entry.get("planning_window") or {}
            if str(window.get("seed_anchor") or "") == str(seed_anchor):
                return
        raise IntakeError(
            f"no cycle with seed_anchor={seed_anchor!r} "
            f"({len(entries)} cycle(s) in dump recorder)"
        )
    assert cycle_index is not None
    if cycle_index < 0 or cycle_index >= len(entries):
        raise IntakeError(
            f"cycle_index {cycle_index} out of range (0..{len(entries) - 1})"
        )


def _build_case_yaml(
    *,
    case_id: str,
    manifest: dict[str, Any],
    seed_anchor: str | None,
    cycle_index: int | None,
    issue: str | None,
    title: str | None,
) -> dict[str, Any]:
    meta_block = manifest.get("meta") if isinstance(manifest.get("meta"), dict) else {}
    resolved_title = title or str(meta_block.get("title") or case_id)
    recorder_sel: dict[str, Any] = {"root": "recorder"}
    if seed_anchor is not None:
        recorder_sel["seed_anchor"] = seed_anchor
    else:
        recorder_sel["cycle_index"] = int(cycle_index)  # type: ignore[arg-type]

    meta: dict[str, Any] = {
        "id": case_id,
        "title": resolved_title,
        "level": "L1",
        "source": "customer",
        "anonymized": False,
        "app_version": str(manifest.get("app_version") or ""),
        "recorder": recorder_sel,
    }
    if issue:
        meta["issue"] = issue
    recorder_meta = manifest.get("recorder")
    if isinstance(recorder_meta, dict):
        start = recorder_meta.get("from")
        end = recorder_meta.get("to")
        if start and end:
            meta["window"] = {"start": str(start), "end": str(end)}
    return meta
