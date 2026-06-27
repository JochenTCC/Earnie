"""Hilfen zum Laden versionierter Produktiv-Dump-Fixtures."""
from __future__ import annotations

import json
from pathlib import Path

FIXTURES_ROOT = Path(__file__).resolve().parent / "prod_dumps"


def list_prod_dump_ids() -> list[str]:
    if not FIXTURES_ROOT.is_dir():
        return []
    ids: list[str] = []
    for path in sorted(FIXTURES_ROOT.iterdir()):
        if path.is_dir() and (path / "manifest.json").is_file():
            ids.append(path.name)
    return ids


def prod_dump_dir(case_id: str) -> Path:
    path = FIXTURES_ROOT / case_id
    if not path.is_dir():
        raise FileNotFoundError(f"Prod-Dump '{case_id}' nicht unter {FIXTURES_ROOT}")
    return path


def load_manifest(case_id: str) -> dict:
    manifest_path = prod_dump_dir(case_id) / "manifest.json"
    with open(manifest_path, encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"manifest.json in {case_id} ist kein JSON-Objekt")
    return data


def fixture_file(case_id: str, filename: str) -> Path:
    path = prod_dump_dir(case_id) / filename
    if not path.is_file():
        raise FileNotFoundError(f"{filename} fehlt im Prod-Dump '{case_id}'")
    return path


def load_jsonl(case_id: str, filename: str = "optimization_history.jsonl") -> list[dict]:
    rows: list[dict] = []
    with open(fixture_file(case_id, filename), encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                row = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"{filename} Zeile {line_no} in {case_id} ungültig: {exc}"
                ) from exc
            if isinstance(row, dict):
                rows.append(row)
    return rows
