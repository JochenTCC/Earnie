"""Config-pack import must not leave a config behind that does not load.

Regression for the online-demo hang: a pack whose content fails config
validation used to be written anyway; the following Streamlit rerun then hit
``SystemExit`` in ``app.py`` and the browser spun forever.
"""
from __future__ import annotations

import io
import json
import sys
import types
import zipfile
from pathlib import Path

import pytest

from runtime_store import bootstrap, cloud_demo
from runtime_store.config_pack import (
    MANIFEST_NAME,
    PACK_JSON_FILES,
    build_config_pack_bytes,
    import_config_pack_bytes,
)
from runtime_store.data_model import CURRENT_DATA_MODEL, DATA_MODEL_KEY, stamp_data_model
from runtime_store.persist_paths import resolve_uploads_dir

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SHARE_CONFIG = _REPO_ROOT / "share" / "config"

_PATH_ENV_KEYS = (
    "EARNIE_CONFIG_PATH",
    "EARNIE_ENV_PATH",
    "EARNIE_RUNTIME_PATH",
    "EARNIE_TARIFFS_PATH",
    "EARNIE_GRID_FEES_PATH",
    "EARNIE_HOUSE_PROFILES_PATH",
    "EARNIE_BACKTESTING_SCENARIOS_PATH",
    "EARNIE_COMPONENTS_PATH",
    "EARNIE_DEVIATION_RULES_PATH",
)


@pytest.fixture
def cloud_session(tmp_path, monkeypatch):
    """Greenfield cloud-demo workspace with a loadable config (as the demo starts)."""
    monkeypatch.chdir(_REPO_ROOT)
    session = tmp_path / "cloud_sess"
    (session / "config").mkdir(parents=True)
    (session / "runtime").mkdir(parents=True)
    for key in _PATH_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("EARNIE_CLOUD_DEMO", "1")
    monkeypatch.setenv("EARNIE_OFFLINE", "1")
    cloud_demo.set_session_env_root_for_tests(str(session))
    try:
        bootstrap.run()
        import config

        config.reinit_config()
        yield session
    finally:
        cloud_demo.set_session_env_root_for_tests(None)


def _live_files(session: Path) -> dict[str, bytes]:
    config_dir = session / "config"
    return {
        p.relative_to(config_dir).as_posix(): p.read_bytes()
        for p in sorted(config_dir.rglob("*"))
        if p.is_file()
    }


def _break_live_export_tariff(docs: dict[str, dict]) -> None:
    """Point the live scenario at an export tariff that does not exist."""
    live = docs["backtesting_scenarios.json"]["scenarios"][0]
    assert live["id"] == "live"
    live["settings"]["export_tariff_id"] = "does_not_exist"


def _example_pack_bytes(mutate=None) -> bytes:
    """Pack of the six ``share/config/*.example.json`` files, data model 4.

    ``mutate`` may change the documents (keyed by pack name) before zipping.
    """
    docs: dict[str, dict] = {}
    for arcname, _resolver in PACK_JSON_FILES:
        src = _SHARE_CONFIG / arcname.replace(".json", ".example.json")
        if src.is_file():
            docs[arcname] = json.loads(src.read_text(encoding="utf-8-sig"))
    if mutate is not None:
        mutate(docs)
    buffer = io.BytesIO()
    files: list[str] = []
    with zipfile.ZipFile(buffer, "w") as archive:
        for arcname, doc in docs.items():
            stamp_data_model(doc)
            archive.writestr(arcname, json.dumps(doc, ensure_ascii=False))
            files.append(arcname)
        archive.writestr(
            MANIFEST_NAME,
            json.dumps({DATA_MODEL_KEY: CURRENT_DATA_MODEL, "files": files}),
        )
    assert len(files) == 6
    return buffer.getvalue()


def test_example_configs_pack_imports_and_loads(cloud_session):
    """The shipped example set is a loadable config on its own (all scenarios resolve)."""
    import config

    written = import_config_pack_bytes(_example_pack_bytes())

    assert len(written) == 6
    assert config.CONFIG.config_path.startswith(str(cloud_session))
    scenarios = config.CONFIG.get_backtesting_scenarios()
    assert {"live", "entity_refs_planning"} <= set(scenarios)


def test_unloadable_pack_is_rejected_and_previous_config_kept(cloud_session):
    import config

    before = _live_files(cloud_session)
    live_before = config.CONFIG.get_live_scenario_id()

    with pytest.raises(ValueError, match="Config-Paket nicht übernommen.*does_not_exist"):
        import_config_pack_bytes(_example_pack_bytes(_break_live_export_tariff))

    assert _live_files(cloud_session) == before
    # The active config object is rebuilt from the restored files and still works.
    assert config.CONFIG.config_path.startswith(str(cloud_session))
    assert config.CONFIG.get_live_scenario_id() == live_before
    config.reinit_config()


def test_unloadable_pack_removes_uploads_it_created(cloud_session):
    payload = io.BytesIO()
    broken = _example_pack_bytes(_break_live_export_tariff)
    with zipfile.ZipFile(io.BytesIO(broken)) as src, zipfile.ZipFile(
        payload, "w"
    ) as dst:
        for name in src.namelist():
            dst.writestr(name, src.read(name))
        dst.writestr("uploads/new_profile.csv", "timestamp;power_kw\n")
    before = _live_files(cloud_session)

    with pytest.raises(ValueError):
        import_config_pack_bytes(payload.getvalue())

    assert not (Path(resolve_uploads_dir()) / "new_profile.csv").exists()
    assert _live_files(cloud_session) == before


def test_valid_exported_pack_still_imports(cloud_session):
    import config

    payload = build_config_pack_bytes()
    # Change a live file so the import has something to restore.
    config_json = cloud_session / "config" / "config.json"
    exported = json.loads(
        zipfile.ZipFile(io.BytesIO(payload)).read("config.json").decode("utf-8")
    )
    doc = json.loads(config_json.read_text(encoding="utf-8-sig"))
    doc["_test_marker"] = True
    config_json.write_text(json.dumps(doc), encoding="utf-8")

    written = import_config_pack_bytes(payload)

    assert "config.json" in written
    reloaded = json.loads(config_json.read_text(encoding="utf-8-sig"))
    assert "_test_marker" not in reloaded
    assert reloaded == exported
    assert config.CONFIG.config_path.startswith(str(cloud_session))


def test_load_config_for_ui_returns_message_instead_of_exit(tmp_path, monkeypatch):
    """app.py path: a config error becomes a message, never SystemExit."""
    from runtime_store import config_load

    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "config.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("EARNIE_CONFIG_PATH", str(cfg_dir))

    fake = types.ModuleType("config")

    def _broken_reinit(**_kwargs):
        raise ValueError("Unbekannte export_tariff_id 'x'.")

    fake.reinit_config = _broken_reinit
    monkeypatch.setitem(sys.modules, "config", fake)

    module, message = config_load.load_config_for_ui()

    assert module is fake
    assert message == "Unbekannte export_tariff_id 'x'."


def test_load_config_for_ui_missing_config_returns_message(tmp_path, monkeypatch):
    from runtime_store import config_load

    missing = tmp_path / "missing" / "config.json"
    monkeypatch.setenv("EARNIE_CONFIG_PATH", str(missing))

    module, message = config_load.load_config_for_ui()

    assert module is None
    assert message is not None
    assert "Konfigurationsdatei nicht gefunden" in message


def test_load_config_for_ui_success(monkeypatch, tmp_path):
    from runtime_store import config_load

    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "config.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("EARNIE_CONFIG_PATH", str(cfg_dir))
    calls: list[int] = []
    fake = types.ModuleType("config")
    fake.reinit_config = lambda **_kw: calls.append(1)
    monkeypatch.setitem(sys.modules, "config", fake)

    assert config_load.load_config_for_ui() == (fake, None)
    assert calls == [1]
