from __future__ import annotations

import json
from pathlib import Path

from scripts import archive_prod_dump as archive_script


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_archive_prod_dump_includes_resolved_inputs(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "optimization_history.jsonl").write_text(
        '{"written_at":"2026-07-07T11:00:00"}\n',
        encoding="utf-8",
    )
    _write_json(source / "optimizer_run_state.json", {"ok": True})

    config_path = tmp_path / "cfg" / "config.json"
    rules_path = tmp_path / "cfg" / "deviation_rules.json"
    local_settings_path = tmp_path / "runtime" / "local_settings.json"
    model_path = tmp_path / "runtime" / "price_model_coefficients.json"
    cons_data_path = tmp_path / "runtime" / "cons_data_hourly.csv"
    _write_json(
        config_path,
        {
            "market_prices": {"forecast_model_path": "runtime/price_model_coefficients.json"},
            "file_paths_battery_simulation": {"path_cons_data": "runtime/cons_data_hourly.csv"},
            "runtime_settings": {"battery_capacity_kwh": 5.0},
        },
    )
    _write_json(
        rules_path,
        {
            "version": 1,
            "tolerances": {"power_kw": 0.2},
            "categories": {"hint": {}, "warning": {}, "error": {}},
            "rules": [],
            "fallback": {"on_unclassified_mismatch": "warning"},
        },
    )
    _write_json(local_settings_path, {"loxone_silent_mode": True})
    _write_json(model_path, {"version": 2, "coefficients": {}})
    cons_data_path.write_text("timestamp;total_kw;baseload_kw;pv_kw;source\n", encoding="utf-8")

    monkeypatch.setenv("ENERGY_OPTIMIZER_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("ENERGY_OPTIMIZER_DEVIATION_RULES_PATH", str(rules_path))
    monkeypatch.setenv("ENERGY_OPTIMIZER_LOCAL_SETTINGS_PATH", str(local_settings_path))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(archive_script, "FIXTURES_ROOT", tmp_path / "fixtures")

    target = archive_script.archive_prod_dump(
        case_id="case_debug_dump",
        title="Debug dump",
        symptom="Repro inputs",
        source=source,
        app_version="1.2.3",
        recorded_at="2026-07-07",
        regression={},
        force=False,
    )

    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["resolved_paths"]["config_json"] == str(config_path)
    assert manifest["resolved_paths"]["deviation_rules_json"] == str(rules_path)
    assert manifest["resolved_paths"]["local_settings_json"] == str(local_settings_path)
    assert manifest["resolved_paths"]["forecast_model_path"] == str(model_path)
    assert manifest["resolved_paths"]["cons_data_path"] == str(cons_data_path)
    assert manifest["env_overrides"]["ENERGY_OPTIMIZER_CONFIG_PATH"] == str(config_path)
    assert "inputs/config.json" in manifest["files"]
    assert "inputs/deviation_rules.json" in manifest["files"]
    assert "inputs/local_settings.json" in manifest["files"]
    assert "inputs/price_model_coefficients.json" in manifest["files"]
    assert "inputs/cons_data_hourly.csv" in manifest["files"]
    assert (target / "inputs" / "config.json").is_file()
    assert (target / "inputs" / "deviation_rules.json").is_file()
    assert (target / "inputs" / "local_settings.json").is_file()
    assert (target / "inputs" / "price_model_coefficients.json").is_file()
    assert (target / "inputs" / "cons_data_hourly.csv").is_file()
