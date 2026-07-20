"""Tests for earnie_env defaults, config packs, and auto-persist fingerprints."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from runtime_store.config_pack import (
    MANIFEST_NAME,
    build_config_pack_bytes,
    import_config_pack_bytes,
)
from runtime_store.data_model import (
    CURRENT_DATA_MODEL,
    DATA_MODEL_KEY,
    DataModelError,
    ensure_compatible,
)
from runtime_store.persist_paths import (
    config_dir,
    env_root,
    resolve_config_json_path,
    resolve_config_prefixed_path,
    resolve_uploads_dir,
    runtime_dir,
)
from ui.auto_persist import payload_fingerprint

_RUNTIME_ENV_KEYS = (
    "EARNIE_RUNTIME_PATH",
    "ENERGY_OPTIMIZER_RUNTIME_PATH",
    "EARNIE_RUNTIME_DIR",
    "ENERGY_OPTIMIZER_RUNTIME_DIR",
)


def _clear_runtime_overrides(monkeypatch) -> None:
    """Drop PATH and legacy DIR overrides so runtime_dir() uses env_root()."""
    for key in _RUNTIME_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_defaults_resolve_under_earnie_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("EARNIE_ENV_PATH", raising=False)
    monkeypatch.delenv("ENERGY_OPTIMIZER_ENV_PATH", raising=False)
    monkeypatch.delenv("EARNIE_CONFIG_PATH", raising=False)
    monkeypatch.delenv("ENERGY_OPTIMIZER_CONFIG_PATH", raising=False)
    _clear_runtime_overrides(monkeypatch)
    cfg = tmp_path / "earnie_env" / "config"
    rt = tmp_path / "earnie_env" / "runtime"
    cfg.mkdir(parents=True)
    rt.mkdir(parents=True)
    (cfg / "config.json").write_text("{}", encoding="utf-8")
    assert env_root().replace("\\", "/") == "earnie_env"
    assert config_dir().replace("\\", "/") == "earnie_env/config"
    assert resolve_config_json_path().replace("\\", "/") == "earnie_env/config/config.json"
    assert runtime_dir().replace("\\", "/") == "earnie_env/runtime"


def test_env_path_derives_config_and_runtime(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    stack = tmp_path / "custom_env"
    (stack / "config").mkdir(parents=True)
    (stack / "runtime").mkdir(parents=True)
    (stack / "config" / "config.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("EARNIE_ENV_PATH", str(stack))
    monkeypatch.delenv("EARNIE_CONFIG_PATH", raising=False)
    monkeypatch.delenv("ENERGY_OPTIMIZER_CONFIG_PATH", raising=False)
    _clear_runtime_overrides(monkeypatch)
    assert Path(env_root()).resolve() == stack.resolve()
    assert Path(config_dir()).resolve() == (stack / "config").resolve()
    assert Path(resolve_config_json_path()).resolve() == (
        stack / "config" / "config.json"
    ).resolve()
    assert Path(runtime_dir()).resolve() == (stack / "runtime").resolve()


def test_config_path_env_is_directory(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    cfg = tmp_path / "stack" / "config"
    cfg.mkdir(parents=True)
    (cfg / "config.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("EARNIE_CONFIG_PATH", str(cfg))
    assert Path(config_dir()).resolve() == cfg.resolve()
    assert Path(resolve_config_json_path()).resolve() == (cfg / "config.json").resolve()


def test_config_prefixed_uploads_co_located(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("EARNIE_CONFIG_PATH", str(tmp_path / "stack" / "config"))
    uploads = tmp_path / "stack" / "config" / "uploads"
    uploads.mkdir(parents=True)
    target = uploads / "a.csv"
    target.write_text("timestamp;power_kw\n", encoding="utf-8")
    resolved = resolve_config_prefixed_path("config/uploads/a.csv")
    assert Path(resolved).resolve() == target.resolve()
    assert Path(resolve_uploads_dir()).resolve() == uploads.resolve()


def test_ensure_compatible_rejects_unknown_version() -> None:
    with pytest.raises(DataModelError):
        ensure_compatible({DATA_MODEL_KEY: 99}, label="x.json")


def test_config_pack_round_trip(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("EARNIE_ENV_PATH", raising=False)
    monkeypatch.delenv("ENERGY_OPTIMIZER_ENV_PATH", raising=False)
    monkeypatch.delenv("EARNIE_CONFIG_PATH", raising=False)
    monkeypatch.delenv("ENERGY_OPTIMIZER_CONFIG_PATH", raising=False)
    _clear_runtime_overrides(monkeypatch)
    cfg = tmp_path / "earnie_env" / "config"
    cfg.mkdir(parents=True)
    (tmp_path / "earnie_env" / "runtime").mkdir(parents=True)
    docs = {
        "config.json": {DATA_MODEL_KEY: 1, "live_scenario_id": "live"},
        "backtesting_scenarios.json": {DATA_MODEL_KEY: 1, "scenarios": []},
        "components.json": {DATA_MODEL_KEY: 1, "batteries": [], "pv_systems": []},
        "deviation_rules.json": {DATA_MODEL_KEY: 1, "version": 1, "rules": []},
        "house_profiles.json": {DATA_MODEL_KEY: 1, "profiles": []},
        "tariffs.json": {DATA_MODEL_KEY: 1, "import_tariffs": [], "export_tariffs": []},
    }
    for name, doc in docs.items():
        (cfg / name).write_text(json.dumps(doc), encoding="utf-8")
    uploads = cfg / "uploads"
    uploads.mkdir()
    (uploads / "sample.csv").write_text("timestamp;power_kw\n", encoding="utf-8")

    monkeypatch.delenv("EARNIE_CONFIG_PATH", raising=False)
    monkeypatch.delenv("ENERGY_OPTIMIZER_CONFIG_PATH", raising=False)

    payload = build_config_pack_bytes()
    with zipfile.ZipFile(__import__("io").BytesIO(payload)) as zf:
        assert MANIFEST_NAME in zf.namelist()
        assert "uploads/sample.csv" in zf.namelist()

    # Import into a second stack via ENV (directory semantics)
    other = tmp_path / "other" / "config"
    other.mkdir(parents=True)
    monkeypatch.setenv("EARNIE_CONFIG_PATH", str(other))
    for name, doc in docs.items():
        # empty targets so import has somewhere to write
        (other / name).write_text("{}", encoding="utf-8")
    written = import_config_pack_bytes(payload)
    assert "config.json" in written
    assert any(w.startswith("uploads/") for w in written)
    loaded = json.loads((other / "config.json").read_text(encoding="utf-8"))
    assert loaded["live_scenario_id"] == "live"
    assert loaded[DATA_MODEL_KEY] == CURRENT_DATA_MODEL
    assert (other / "uploads" / "sample.csv").is_file()


def test_config_pack_rejects_bad_model(monkeypatch, tmp_path: Path) -> None:
    import io

    monkeypatch.chdir(tmp_path)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            MANIFEST_NAME,
            json.dumps({DATA_MODEL_KEY: 99, "files": []}),
        )
    with pytest.raises(DataModelError):
        import_config_pack_bytes(buf.getvalue())


def test_payload_fingerprint_stable() -> None:
    a = payload_fingerprint({"b": 1, "a": 2})
    b = payload_fingerprint({"a": 2, "b": 1})
    assert a == b
    assert a != payload_fingerprint({"a": 3, "b": 1})
