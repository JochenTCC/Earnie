# tests/test_ha_addon_smoke.py
from __future__ import annotations

from pathlib import Path

from scripts import ha_addon_smoke as smoke

REPO_ROOT = Path(__file__).resolve().parents[1]
RELEASE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release-publish.yml"


def test_parse_default_options_scalars():
    text = (
        "name: x\n"
        "options:\n"
        "  streamlit_port: 8501\n"
        "  ui_modes: \"a,b\"\n"
        "  auto_start_main: true\n"
        "  # comment\n"
        "  timezone: 'Europe/Vienna'\n"
        "\n"
        "schema:\n"
        "  streamlit_port: \"port?\"\n"
    )
    assert smoke.parse_default_options(text) == {
        "streamlit_port": 8501,
        "ui_modes": "a,b",
        "auto_start_main": True,
        "timezone": "Europe/Vienna",
    }


def test_parse_default_options_matches_shipped_addon_schema():
    text = smoke.ADDON_CONFIG_YAML.read_text(encoding="utf-8")
    options = smoke.parse_default_options(text)
    schema_block = text.split("\nschema:\n", 1)[1]
    schema_keys = {line.split(":", 1)[0].strip() for line in schema_block.splitlines() if line.startswith("  ")}
    assert set(options) == schema_keys
    assert options["auto_start_main"] is True


def test_docker_run_command_mounts_data_and_addon_config(tmp_path):
    cmd = smoke.docker_run_command(
        image="ghcr.io/jochentcc/earnie-addon-aarch64:1.0.0",
        name="smoke",
        platform="linux/arm64",
        host_port=18501,
        data_dir=tmp_path / "data",
        config_dir=tmp_path / "config",
    )
    assert cmd[:4] == ["docker", "run", "-d", "--name"]
    assert ["--platform", "linux/arm64"] == cmd[cmd.index("--platform") : cmd.index("--platform") + 2]
    assert "127.0.0.1:18501:8501" in cmd
    assert f"{tmp_path / 'data'}:/data" in cmd
    assert f"{tmp_path / 'config'}:/config" in cmd
    assert cmd[-1] == "ghcr.io/jochentcc/earnie-addon-aarch64:1.0.0"


def test_docker_run_command_native_platform_omitted(tmp_path):
    cmd = smoke.docker_run_command(
        image="img", name="n", platform=None, host_port=1, data_dir=tmp_path, config_dir=tmp_path
    )
    assert "--platform" not in cmd


def test_check_seeded_config_ok(tmp_path):
    data, config = tmp_path / "data", tmp_path / "config"
    config.mkdir()
    data.mkdir()
    (config / "config.json").write_text("{}", encoding="utf-8")
    assert smoke.check_seeded_config(data, config) == []


def test_check_seeded_config_flags_legacy_path(tmp_path):
    data, config = tmp_path / "data", tmp_path / "config"
    legacy = data / smoke.LEGACY_CONFIG_JSON
    legacy.parent.mkdir(parents=True)
    config.mkdir()
    legacy.write_text("{}", encoding="utf-8")
    errors = smoke.check_seeded_config(data, config)
    assert any("not seeded under /config" in e for e in errors)
    assert any("legacy" in e for e in errors)


def test_release_workflow_gates_user_visible_steps():
    """Candidate build must not touch :next/:latest, the release or HA pins before approval."""
    text = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    assert "build_container --target all --push --versioned-only" in text
    assert "--draft" in text
    assert "environment: release-approval" in text
    assert "needs: [release, addon_smoke, addon_lint, qemu_smoke]" in text
    assert "needs: [release, promote]" in text
    assert "scripts.ha_addon_smoke" in text
