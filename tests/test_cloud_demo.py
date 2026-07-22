# tests/test_cloud_demo.py
"""Community Cloud per-session Greenfield (EARNIE_CLOUD_DEMO)."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import unquote

import pytest

from runtime_store import bootstrap, cloud_demo
from runtime_store.persist_paths import (
    env_root,
    resolve_config_json_path,
    resolve_house_profiles_json_path,
)
from ui.navigation import build_page_specs


@pytest.fixture(autouse=True)
def _clear_cloud_session_hook():
    cloud_demo.set_session_env_root_for_tests(None)
    yield
    cloud_demo.set_session_env_root_for_tests(None)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _minimal_share(tmp_path: Path) -> Path:
    share_dir = tmp_path / "share" / "config"
    share_dir.mkdir(parents=True)
    (share_dir / ".env.example").write_text(
        'LOXONE_USER="name-des-benutzers-in-der-loxone"\n'
        'LOXONE_PASS="Passwort-des-benutzers-in-der-loxone"\n'
        "LOXONE_IP=192.168.178.1\n",
        encoding="utf-8",
    )
    _write_json(share_dir / "config.minimal.json", {"flexible_consumers": []})
    _write_json(share_dir / "config.example.json", {"system": {"global_timeout": 10}})
    _write_json(share_dir / "house_profiles.minimal.json", {"profiles": []})
    _write_json(
        share_dir / "tariffs.minimal.json",
        {"import_tariffs": [], "export_tariffs": []},
    )
    _write_json(
        share_dir / "tariffs.example.json",
        {
            "import_tariffs": [{"id": "awattar_at", "label": "aWATTar", "type": "awattar"}],
            "export_tariffs": [
                {
                    "id": "fixed_37ct",
                    "label": "Fix Export",
                    "type": "fixed",
                    "k_push_cent": 3.7,
                }
            ],
        },
    )
    _write_json(share_dir / "tariffs.json", {
        "import_tariffs": [{"id": "awattar_at", "label": "aWATTar", "type": "awattar"}],
        "export_tariffs": [
            {"id": "fixed_37ct", "label": "Fix Export", "type": "fixed", "k_push_cent": 3.7}
        ],
    })
    _write_json(
        share_dir / "backtesting_scenarios.minimal.json",
        {
            "cbc_gap_rel": 0.1,
            "scenarios": [
                {
                    "id": "live",
                    "label": "Live",
                    "settings": {
                        "battery_id": "",
                        "pv_system_ids": [],
                        "import_tariff_id": "",
                        "export_tariff_id": "",
                        "house_profile_id": "",
                    },
                }
            ],
        },
    )
    _write_json(
        share_dir / "components.minimal.json",
        {"batteries": [], "pv_systems": []},
    )
    _write_json(share_dir / "components.example.json", {"batteries": [], "pv_systems": []})
    _write_json(
        share_dir / "deviation_rules.minimal.json",
        {"rules": []},
    )
    _write_json(share_dir / "deviation_rules.example.json", {"rules": []})
    return share_dir


def test_is_cloud_demo_env(monkeypatch):
    monkeypatch.delenv("EARNIE_CLOUD_DEMO", raising=False)
    monkeypatch.delenv("ENERGY_OPTIMIZER_CLOUD_DEMO", raising=False)
    assert cloud_demo.is_cloud_demo() is False
    monkeypatch.setenv("EARNIE_CLOUD_DEMO", "1")
    assert cloud_demo.is_cloud_demo() is True


def test_get_session_env_root_bare_mode_skips_streamlit(monkeypatch):
    """Without CLOUD_DEMO, never probe Streamlit (CLI / backtesting)."""
    monkeypatch.delenv("EARNIE_CLOUD_DEMO", raising=False)
    monkeypatch.delenv("ENERGY_OPTIMIZER_CLOUD_DEMO", raising=False)
    assert cloud_demo.get_session_env_root() is None


def test_get_session_env_root_cloud_demo_without_script_ctx(monkeypatch):
    monkeypatch.setenv("EARNIE_CLOUD_DEMO", "1")
    assert cloud_demo.get_session_env_root() is None


def test_session_env_root_overrides_persist_paths(tmp_path, monkeypatch):
    monkeypatch.delenv("EARNIE_CLOUD_DEMO", raising=False)
    session = tmp_path / "sess_a"
    (session / "config").mkdir(parents=True)
    (session / "runtime").mkdir(parents=True)
    monkeypatch.setenv("EARNIE_ENV_PATH", str(tmp_path / "earnie_env"))
    monkeypatch.setenv("EARNIE_CONFIG_PATH", str(tmp_path / "earnie_env" / "config"))
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path / "earnie_env" / "runtime"))

    cloud_demo.set_session_env_root_for_tests(str(session))
    assert Path(env_root()) == session
    assert Path(resolve_config_json_path()) == session / "config" / "config.json"

    cloud_demo.set_session_env_root_for_tests(None)
    assert "earnie_env" in env_root().replace("\\", "/")


def test_ensure_cloud_session_env_creates_and_reuses(tmp_path, monkeypatch):
    monkeypatch.setenv("EARNIE_CLOUD_DEMO", "1")
    fake_state: dict = {}
    fake_st = SimpleNamespace(session_state=fake_state)
    import sys

    monkeypatch.setitem(sys.modules, "streamlit", fake_st)

    def fake_get_root() -> str | None:
        root = fake_state.get(cloud_demo.SESSION_ENV_KEY)
        if isinstance(root, str) and root.strip():
            return root.strip()
        return None

    monkeypatch.setattr(cloud_demo, "get_session_env_root", fake_get_root)

    first = cloud_demo.ensure_cloud_session_env()
    assert first is not None
    assert Path(first).is_dir()
    assert (Path(first) / "config").is_dir()
    assert (Path(first) / "runtime").is_dir()
    assert fake_state[cloud_demo.SESSION_ENV_KEY] == first

    second = cloud_demo.ensure_cloud_session_env()
    assert second == first


def test_ensure_cloud_session_env_noop_without_flag(monkeypatch):
    monkeypatch.delenv("EARNIE_CLOUD_DEMO", raising=False)
    monkeypatch.delenv("ENERGY_OPTIMIZER_CLOUD_DEMO", raising=False)
    assert cloud_demo.ensure_cloud_session_env() is None


def test_bootstrap_under_cloud_session_skips_offline_seed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _minimal_share(tmp_path)
    session = tmp_path / "cloud_sess"
    (session / "config").mkdir(parents=True)
    (session / "runtime").mkdir(parents=True)
    cloud_demo.set_session_env_root_for_tests(str(session))
    monkeypatch.setenv("EARNIE_CLOUD_DEMO", "1")
    monkeypatch.setenv("EARNIE_OFFLINE", "1")
    for key in (
        "EARNIE_CONFIG_PATH",
        "ENERGY_OPTIMIZER_CONFIG_PATH",
        "ENERGY_OPTIMIZER_HOUSE_PROFILES_PATH",
        "ENERGY_OPTIMIZER_TARIFFS_PATH",
        "ENERGY_OPTIMIZER_BACKTESTING_SCENARIOS_PATH",
        "ENERGY_OPTIMIZER_COMPONENTS_PATH",
        "ENERGY_OPTIMIZER_RUNTIME_PATH",
        "EARNIE_ENV_PATH",
    ):
        monkeypatch.delenv(key, raising=False)

    # Prefill catalogs that would otherwise seed live refs when offline.
    _write_json(
        session / "config" / "components.json",
        {
            "batteries": [{"id": "bat1", "battery_capacity_kwh": 10}],
            "pv_systems": [{"id": "pv1"}],
        },
    )
    _write_json(
        session / "config" / "house_profiles.json",
        {"profiles": [{"id": "home", "label": "Home"}]},
    )
    _write_json(
        session / "config" / "tariffs.json",
        {
            "import_tariffs": [{"id": "awattar_at", "type": "awattar"}],
            "export_tariffs": [
                {"id": "fixed_37ct", "type": "fixed", "k_push_cent": 3.7}
            ],
        },
    )
    _write_json(
        session / "config" / "backtesting_scenarios.json",
        {
            "cbc_gap_rel": 0.1,
            "scenarios": [
                {
                    "id": "live",
                    "label": "Live",
                    "settings": {
                        "battery_id": "",
                        "pv_system_ids": [],
                        "import_tariff_id": "",
                        "export_tariff_id": "",
                        "house_profile_id": "",
                    },
                }
            ],
        },
    )

    bootstrap.run()

    assert Path(resolve_config_json_path()).is_file()
    assert Path(resolve_house_profiles_json_path()).is_file()
    scenarios = json.loads(
        (session / "config" / "backtesting_scenarios.json").read_text(encoding="utf-8")
    )
    settings = scenarios["scenarios"][0]["settings"]
    assert settings["battery_id"] == ""
    assert settings["house_profile_id"] == ""
    assert settings["import_tariff_id"] == ""


def test_cloud_restricted_nav_hauskonfigurator_only(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("EARNIE_CLOUD_DEMO", "1")
    monkeypatch.setenv("ENERGY_OPTIMIZER_CONFIG_PATH", str(config_dir / "config.json"))
    monkeypatch.setenv(
        "ENERGY_OPTIMIZER_HOUSE_PROFILES_PATH",
        str(config_dir / "house_profiles.json"),
    )
    monkeypatch.setenv("ENERGY_OPTIMIZER_TARIFFS_PATH", str(config_dir / "tariffs.json"))
    monkeypatch.setenv(
        "ENERGY_OPTIMIZER_BACKTESTING_SCENARIOS_PATH",
        str(config_dir / "backtesting_scenarios.json"),
    )
    monkeypatch.setenv(
        "ENERGY_OPTIMIZER_COMPONENTS_PATH",
        str(config_dir / "components.json"),
    )
    _write_json(config_dir / "config.json", {"flexible_consumers": []})
    _write_json(config_dir / "components.json", {"batteries": [], "pv_systems": []})
    _write_json(config_dir / "house_profiles.json", {"profiles": []})
    _write_json(
        config_dir / "tariffs.json",
        {"import_tariffs": [], "export_tariffs": []},
    )
    _write_json(
        config_dir / "backtesting_scenarios.json",
        {
            "scenarios": [
                {
                    "id": "live",
                    "label": "Live",
                    "settings": {
                        "battery_id": "",
                        "pv_system_id": "",
                        "import_tariff_id": "",
                        "export_tariff_id": "",
                        "house_profile_id": "",
                    },
                }
            ]
        },
    )

    specs = build_page_specs(["scenario_explorer"])
    titles = [spec.title for spec in specs]
    defaults = [spec for spec in specs if spec.default]

    assert titles == ["Hauskonfigurator"]
    assert len(defaults) == 1
    assert defaults[0].title == "Hauskonfigurator"


def test_render_intro_dismissed(monkeypatch):
    monkeypatch.setenv("EARNIE_CLOUD_DEMO", "1")
    calls: list[str] = []
    fake_state = {cloud_demo.SESSION_INTRO_DISMISSED_KEY: True}
    fake_st = SimpleNamespace(
        session_state=fake_state,
        info=lambda *a, **k: calls.append("info"),
        button=lambda *a, **k: False,
        rerun=lambda: None,
    )
    import sys

    monkeypatch.setitem(sys.modules, "streamlit", fake_st)
    cloud_demo.render_cloud_demo_intro()
    assert calls == []


def test_feedback_mailto_targets_jochen():
    url = cloud_demo.build_cloud_demo_feedback_mailto("Charts unklar")
    assert url.startswith(f"mailto:{cloud_demo.FEEDBACK_EMAIL}?")
    assert "jochen%40techcreacon.com" in url or "jochen@techcreacon.com" in url
    assert "Charts" in url or "Charts%20unklar" in url or "Charts+unklar" in url
    assert "manuell" not in unquote(url).lower()


def test_feedback_mailto_includes_attach_hint_when_agreed():
    url = cloud_demo.build_cloud_demo_feedback_mailto(
        "ok",
        attach_config=True,
    )
    plain = unquote(url)
    assert "manuell" in plain.lower()
    assert "ZIP" in plain
    assert "Tests" in plain or "Bugfix" in plain


def test_mark_se_sim_started_noop_without_cloud_demo(monkeypatch):
    monkeypatch.delenv("EARNIE_CLOUD_DEMO", raising=False)
    monkeypatch.delenv("ENERGY_OPTIMIZER_CLOUD_DEMO", raising=False)
    fake_state: dict = {}
    fake_st = SimpleNamespace(session_state=fake_state)
    import sys

    monkeypatch.setitem(sys.modules, "streamlit", fake_st)
    cloud_demo.mark_cloud_demo_se_simulation_started()
    assert cloud_demo.SESSION_SE_SIM_STARTED_KEY not in fake_state


def test_mark_se_sim_started_sets_flag(monkeypatch):
    monkeypatch.setenv("EARNIE_CLOUD_DEMO", "1")
    fake_state: dict = {}
    fake_st = SimpleNamespace(session_state=fake_state)
    import sys

    monkeypatch.setitem(sys.modules, "streamlit", fake_st)
    cloud_demo.mark_cloud_demo_se_simulation_started()
    assert fake_state[cloud_demo.SESSION_SE_SIM_STARTED_KEY] is True


def test_feedback_banner_hidden_until_sim_started(monkeypatch):
    monkeypatch.setenv("EARNIE_CLOUD_DEMO", "1")
    calls: list[str] = []
    fake_st = SimpleNamespace(
        session_state={},
        info=lambda *a, **k: calls.append("info"),
        text_area=lambda *a, **k: "",
        columns=lambda *a, **k: (SimpleNamespace(), SimpleNamespace()),
        link_button=lambda *a, **k: None,
        button=lambda *a, **k: False,
        rerun=lambda: None,
    )
    import sys

    monkeypatch.setitem(sys.modules, "streamlit", fake_st)
    cloud_demo.render_cloud_demo_feedback_banner()
    assert calls == []


def test_feedback_banner_shows_after_sim_started(monkeypatch):
    monkeypatch.setenv("EARNIE_CLOUD_DEMO", "1")
    calls: list[str] = []
    fake_state = {cloud_demo.SESSION_SE_SIM_STARTED_KEY: True}

    class _Col:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    fake_st = SimpleNamespace(
        session_state=fake_state,
        info=lambda *a, **k: calls.append("info"),
        text_area=lambda *a, **k: "ok",
        checkbox=lambda *a, **k: False,
        download_button=lambda *a, **k: calls.append("download"),
        caption=lambda *a, **k: None,
        error=lambda *a, **k: calls.append("error"),
        columns=lambda *a, **k: (_Col(), _Col()),
        link_button=lambda *a, **k: calls.append("mailto"),
        button=lambda *a, **k: False,
        rerun=lambda: None,
    )
    import sys

    monkeypatch.setitem(sys.modules, "streamlit", fake_st)
    cloud_demo.render_cloud_demo_feedback_banner()
    assert "info" in calls
    assert "mailto" in calls
    assert "download" not in calls


def test_feedback_banner_offers_zip_when_attach_checked(monkeypatch):
    monkeypatch.setenv("EARNIE_CLOUD_DEMO", "1")
    calls: list[str] = []
    fake_state = {cloud_demo.SESSION_SE_SIM_STARTED_KEY: True}

    class _Col:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    fake_st = SimpleNamespace(
        session_state=fake_state,
        info=lambda *a, **k: calls.append("info"),
        text_area=lambda *a, **k: "ok",
        checkbox=lambda *a, **k: True,
        download_button=lambda *a, **k: calls.append("download"),
        caption=lambda *a, **k: calls.append("caption"),
        error=lambda *a, **k: calls.append("error"),
        columns=lambda *a, **k: (_Col(), _Col()),
        link_button=lambda *a, **k: calls.append("mailto"),
        button=lambda *a, **k: False,
        rerun=lambda: None,
    )
    import sys

    monkeypatch.setitem(sys.modules, "streamlit", fake_st)
    monkeypatch.setattr(
        "runtime_store.config_pack.build_config_pack_bytes",
        lambda: b"PK\x03\x04fake",
    )
    cloud_demo.render_cloud_demo_feedback_banner()
    assert "download" in calls
    assert "caption" in calls
