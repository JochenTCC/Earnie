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
                "tariff_format": 1,
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
        imports=[{"id": "imp1", "land": "AT", "label": "Import", "type": "fixed_cent", "fix_cent_kwh": 20.0}],
        exports=[{"id": "exp1", "land": "AT", "label": "Export", "type": "fixed", "k_push_cent": 5.0}],
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
        imports=[{"id": "imp1", "land": "AT", "label": "Import", "type": "fixed_cent", "fix_cent_kwh": 20.0}],
        exports=[{"id": "exp1", "land": "AT", "label": "Export", "type": "fixed", "k_push_cent": 5.0}],
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
        json.dumps({"tariff_format": 1, "import_tariffs": {}, "export_tariffs": []}),
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
    tariffs_path = root / "share" / "config" / "tariffs.json"
    schema_path = root / "share" / "config" / "tariffs.schema.json"
    errors = collect_tariff_plausibility_errors(
        tariffs_path=str(tariffs_path),
        scenarios_path=None,
        schema_path=str(schema_path),
    )
    assert errors == []


def test_scenarios_using_tariff_lists_import_and_export_users(tmp_path):
    from house_config.tariff_plausibility import scenarios_using_tariff

    path = tmp_path / "backtesting_scenarios.json"
    path.write_text(
        json.dumps(
            {
                "scenarios": [
                    {"id": "a", "settings": {"import_tariff_id": "user_x", "export_tariff_id": "user_y"}},
                    {"id": "b", "settings": {"import_tariff_id": "fixed_25ct", "export_tariff_id": "user_x"}},
                    {"id": "c", "settings": {"import_tariff_id": "user_x"}},
                ]
            }
        ),
        encoding="utf-8",
    )
    assert scenarios_using_tariff(str(path), "import", "user_x") == ["a", "c"]
    assert scenarios_using_tariff(str(path), "export", "user_x") == ["b"]
    assert scenarios_using_tariff(str(tmp_path / "fehlt.json"), "import", "user_x") == []
    with pytest.raises(ValueError, match="direction"):
        scenarios_using_tariff(str(path), "both", "user_x")
