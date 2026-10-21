"""HA Testbed P3: compose file and ``scripts.ha_testbed`` (no Docker needed)."""
from __future__ import annotations

import re

import pytest
import yaml

from scripts import ha_testbed as tb

LAB_COMPOSE = tb.REPO_ROOT / "docker" / "compose" / "ha-lab.yml"


class Recorder:
    def __init__(self, results=None):
        self.calls: list[tuple[list[str], dict[str, str]]] = []
        self.results = results or {}

    def __call__(self, cmd, env):
        self.calls.append((list(cmd), dict(env)))
        for needle, code in self.results.items():
            if needle in cmd:
                return code
        return 0

    def commands(self):
        return [" ".join(c) for c, _ in self.calls]


@pytest.fixture(autouse=True)
def _fake_integration(tmp_path_factory, monkeypatch):
    """Small stand-in tree: the packaging test rewrites the real one in parallel workers."""
    src = tmp_path_factory.mktemp("integration_src") / "earnie_house_sim"
    (src / "_core").mkdir(parents=True)
    (src / "__pycache__").mkdir()
    (src / "manifest.json").write_text("{}", encoding="utf-8")
    (src / "_core" / "physics.py").write_text("", encoding="utf-8")
    (src / "__pycache__" / "x.pyc").write_text("", encoding="utf-8")
    monkeypatch.setattr(tb, "INTEGRATION_SRC", src)


class _Loader(yaml.SafeLoader):
    pass


_Loader.add_constructor("!include_dir_named", lambda loader, node: loader.construct_scalar(node))


# --- compose -----------------------------------------------------------------


def test_compose_has_ha_and_optional_earnie_without_evcc_or_hacs():
    text = tb.COMPOSE_FILE.read_text(encoding="utf-8")
    doc = yaml.safe_load(text)
    assert set(doc["services"]) == {"homeassistant", "earnie"}
    ha, earnie = doc["services"]["homeassistant"], doc["services"]["earnie"]
    assert earnie["profiles"] == ["earnie"] and "profiles" not in ha
    assert "8123:8123" in ha["ports"]
    assert {"8506:8501", "8541:8541"} <= set(earnie["ports"])
    assert ha["container_name"] == tb.HA_CONTAINER
    assert "hacs-init" not in doc["services"]


def test_compose_pins_the_same_ha_image_as_the_lab():
    pattern = r"image:\s*(ghcr\.io/home-assistant/home-assistant:[\w.]+)"
    lab = re.search(pattern, LAB_COMPOSE.read_text(encoding="utf-8"))
    bench = re.search(pattern, tb.COMPOSE_FILE.read_text(encoding="utf-8"))
    assert lab and bench and lab.group(1) == bench.group(1)


def test_compose_container_names_do_not_clash_with_the_lab():
    lab = yaml.safe_load(LAB_COMPOSE.read_text(encoding="utf-8"))["services"]
    bench = yaml.safe_load(tb.COMPOSE_FILE.read_text(encoding="utf-8"))["services"]
    lab_names = {s.get("container_name") for s in lab.values()}
    assert not lab_names & {s.get("container_name") for s in bench.values()}


# --- configuration.yaml patch ------------------------------------------------


def test_patch_creates_block_in_plain_config():
    text, changed = tb.patch_configuration("default_config:\n")
    assert changed and text.endswith("homeassistant:\n  packages: !include_dir_named packages\n")
    assert yaml.load(text, Loader=_Loader)["homeassistant"]["packages"] == "packages"


def test_patch_inserts_into_existing_homeassistant_block():
    src = "homeassistant:\n  name: Home\n  unit_system: metric\n\nhttp:\n  server_port: 8123\n"
    text, changed = tb.patch_configuration(src)
    assert changed
    assert text.splitlines()[:2] == ["homeassistant:", "  packages: !include_dir_named packages"]
    assert "name: Home" in text and "server_port: 8123" in text


def test_patch_is_idempotent():
    once, _ = tb.patch_configuration("default_config:\n")
    twice, changed = tb.patch_configuration(once)
    assert not changed and twice == once


def test_patch_refuses_a_different_packages_setting():
    with pytest.raises(ValueError, match="already sets"):
        tb.patch_configuration("homeassistant:\n  packages: !include_dir_named other\n")
    with pytest.raises(ValueError, match="outside"):
        tb.patch_configuration("packages: !include_dir_named x\n")


def test_patch_ignores_packages_in_a_later_block():
    src = "homeassistant:\n  name: Home\n\nfoo:\n  packages: nope\n"
    text, changed = tb.patch_configuration(src)
    assert changed and text.splitlines()[1] == "  packages: !include_dir_named packages"


# --- commands ----------------------------------------------------------------


def test_up_creates_dirs_and_runs_compose(tmp_path):
    run = Recorder()
    assert tb.main(["--testbed-dir", str(tmp_path / "bench"), "up"], run=run) == 0
    assert all((tmp_path / "bench" / d).is_dir() for d in ("homeassistant", "config", "runtime"))
    cmd, env = run.calls[0]
    assert cmd[:2] == ["docker", "compose"] and cmd[-2:] == ["up", "-d"] and "--profile" not in cmd
    assert env["TESTBED_DIR"] == str((tmp_path / "bench").resolve())


def test_up_with_earnie_builds_the_profile(tmp_path):
    run = Recorder()
    tb.main(["--testbed-dir", str(tmp_path), "up", "--with-earnie"], run=run)
    cmd = run.calls[0][0]
    assert cmd[cmd.index("--profile") + 1] == "earnie" and cmd[-3:] == ["up", "-d", "--build"]


def test_install_copies_integration_patches_config_and_restarts(tmp_path, capsys):
    run = Recorder()
    assert tb.main(["--testbed-dir", str(tmp_path), "install"], run=run) == 0
    ha = tmp_path / "homeassistant"
    assert (ha / "custom_components" / "earnie_house_sim" / "manifest.json").is_file()
    assert (ha / "custom_components" / "earnie_house_sim" / "_core" / "physics.py").is_file()
    assert not list(ha.rglob("__pycache__"))
    assert tb.PACKAGES_LINE in (ha / "configuration.yaml").read_text(encoding="utf-8")
    assert run.commands()[-1] == f"docker restart {tb.HA_CONTAINER}"
    assert "carrier.yaml missing" in capsys.readouterr().err


def test_install_does_not_restart_a_stopped_container(tmp_path):
    run = Recorder(results={"inspect": 1})
    assert tb.main(["--testbed-dir", str(tmp_path), "install"], run=run) == 0
    assert not any("restart" in c for c in run.commands())


def test_install_twice_keeps_configuration_stable(tmp_path):
    run = Recorder()
    tb.main(["--testbed-dir", str(tmp_path), "install"], run=run)
    config = tmp_path / "homeassistant" / "configuration.yaml"
    first = config.read_text(encoding="utf-8")
    tb.main(["--testbed-dir", str(tmp_path), "install"], run=run)
    assert config.read_text(encoding="utf-8") == first


def test_install_aborts_on_conflicting_config_before_copying(tmp_path, capsys):
    ha = tmp_path / "homeassistant"
    ha.mkdir()
    (ha / "configuration.yaml").write_text(
        "homeassistant:\n  packages: !include_dir_named other\n", encoding="utf-8"
    )
    assert tb.main(["--testbed-dir", str(tmp_path), "install"], run=Recorder()) == 2
    assert "already sets" in capsys.readouterr().err
    assert not (ha / "custom_components").exists()


def test_status_reports_installed_state(tmp_path):
    before = {label: ok for label, ok, _ in tb.status_report(tmp_path, port_open=lambda p: False)}
    assert not any(before.values())
    tb.main(["--testbed-dir", str(tmp_path), "install"], run=Recorder())
    ha = tmp_path / "homeassistant"
    (ha / "earnie_house_sim" / "archetypes" / "earnie_pack").mkdir(parents=True)
    (ha / "packages").mkdir()
    (ha / "packages" / "earnie_ha_carrier.yaml").write_text("x", encoding="utf-8")
    after = {
        label: (ok, note)
        for label, ok, note in tb.status_report(tmp_path, port_open=lambda p: p == 8123)
    }
    assert after["integration installed"][0] and after["carrier package"][0]
    assert after["configuration.yaml packages include"][0]
    assert after["generated archetypes"] == (True, "earnie_pack")
    assert after["HA reachable :8123"][0] and not after["Earnie daemon reachable :8541"][0]


def test_reset_needs_confirmation(tmp_path, capsys):
    run = Recorder()
    assert tb.main(["--testbed-dir", str(tmp_path), "reset"], run=run) == 2
    assert run.calls == [] and "--yes" in capsys.readouterr().err


def test_reset_clears_ha_state_but_keeps_gitkeep_and_earnie_dirs(tmp_path):
    for sub in ("homeassistant", "config", "runtime"):
        (tmp_path / sub).mkdir()
        (tmp_path / sub / ".gitkeep").write_text("", encoding="utf-8")
        (tmp_path / sub / "data.txt").write_text("x", encoding="utf-8")
        (tmp_path / sub / "nested").mkdir()
    assert tb.main(["--testbed-dir", str(tmp_path), "reset", "--yes"], run=Recorder()) == 0
    assert sorted(p.name for p in (tmp_path / "homeassistant").iterdir()) == [".gitkeep"]
    assert (tmp_path / "config" / "data.txt").exists()
    assert tb.main(["--testbed-dir", str(tmp_path), "reset", "--yes", "--all"], run=Recorder()) == 0
    assert sorted(p.name for p in (tmp_path / "runtime").iterdir()) == [".gitkeep"]


def test_reset_keeps_data_when_compose_down_fails(tmp_path):
    (tmp_path / "homeassistant").mkdir()
    (tmp_path / "homeassistant" / "data.txt").write_text("x", encoding="utf-8")
    run = Recorder(results={"down": 1})
    assert tb.main(["--testbed-dir", str(tmp_path), "reset", "--yes"], run=run) == 1
    assert (tmp_path / "homeassistant" / "data.txt").exists()
