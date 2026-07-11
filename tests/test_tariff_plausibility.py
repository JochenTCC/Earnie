# tests/test_tariff_plausibility.py
from __future__ import annotations

import json
from pathlib import Path

import pytest

from house_config.tariff_plausibility import (
    collect_scenario_tariff_ref_errors,
    collect_tariff_plausibility_errors,
    validate_tariffs_against_schema,
)


def _write_tariffs(path: Path, *, imports: list | None = None, exports: list | None = None) -> None:
    path.write_text(
        json.dumps(
            {
                "import_tariffs": imports or [],
                "export_tariffs": exports or [],
            }
        ),
        encoding="utf-8",
    )


def _write_scenarios(path: Path, settings: dict) -> None:
    path.write_text(
        json.dumps({"scenarios": [{"id": "live", "settings": settings}]}),
        encoding="utf-8",
    )


def test_collect_tariff_plausibility_errors_ok(tmp_path):
    tariffs = tmp_path / "tariffs.json"
    scenarios = tmp_path / "backtesting_scenarios.json"
    schema = tmp_path / "tariffs.schema.json"
    _write_tariffs(
        tariffs,
        imports=[{"id": "imp1", "label": "Import", "type": "fixed_cent", "fix_cent_kwh": 20.0}],
        exports=[{"id": "exp1", "label": "Export", "type": "fixed", "k_push_cent": 5.0}],
    )
    _write_scenarios(
        scenarios,
        {"import_tariff_id": "imp1", "export_tariff_id": "exp1"},
    )
    schema.write_text(
        json.dumps(
            {
                "type": "object",
                "properties": {
                    "import_tariffs": {"type": "array"},
                    "export_tariffs": {"type": "array"},
                },
            }
        ),
        encoding="utf-8",
    )

    errors = collect_tariff_plausibility_errors(
        tariffs_path=str(tariffs),
        scenarios_path=str(scenarios),
        schema_path=str(schema),
    )
    assert errors == []


def test_collect_scenario_tariff_ref_errors_unknown_export(tmp_path):
    tariffs = tmp_path / "tariffs.json"
    scenarios = tmp_path / "backtesting_scenarios.json"
    _write_tariffs(
        tariffs,
        imports=[{"id": "imp1", "label": "Import", "type": "fixed_cent", "fix_cent_kwh": 20.0}],
        exports=[{"id": "exp1", "label": "Export", "type": "fixed", "k_push_cent": 5.0}],
    )
    _write_scenarios(
        scenarios,
        {"import_tariff_id": "imp1", "export_tariff_id": "missing"},
    )

    errors = collect_scenario_tariff_ref_errors(str(scenarios), str(tariffs))
    assert len(errors) == 1
    assert "missing" in errors[0]


def test_validate_tariffs_against_schema_rejects_invalid_structure(tmp_path):
    tariffs = tmp_path / "tariffs.json"
    schema = tmp_path / "tariffs.schema.json"
    tariffs.write_text(
        json.dumps({"import_tariffs": {}, "export_tariffs": []}),
        encoding="utf-8",
    )
    schema.write_text(
        json.dumps(
            {
                "type": "object",
                "required": ["import_tariffs", "export_tariffs"],
                "properties": {
                    "import_tariffs": {"type": "array"},
                    "export_tariffs": {"type": "array"},
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Schema"):
        validate_tariffs_against_schema(str(tariffs), str(schema))


def test_repo_tariffs_pass_plausibility_and_schema():
    root = Path(__file__).resolve().parents[1]
    tariffs_path = root / "config" / "tariffs.json"
    schema_path = root / "config" / "tariffs.schema.json"
    errors = collect_tariff_plausibility_errors(
        tariffs_path=str(tariffs_path),
        scenarios_path=None,
        schema_path=str(schema_path),
    )
    assert errors == []
