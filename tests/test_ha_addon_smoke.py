# tests/test_ha_addon_smoke.py
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

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
    schema_entries = {}
    for line in schema_block.splitlines():
        if not line.startswith("  "):
            continue
        key, _, typ = line.partition(":")
        schema_entries[key.strip()] = typ.strip().strip('"').strip("'")
    schema_keys = set(schema_entries)
    assert set(options) <= schema_keys
    # Optional schema keys (suffix ?) may be omitted from options so absent = no change.
    missing = schema_keys - set(options)
    assert missing <= {
        key for key, typ in schema_entries.items() if typ.endswith("?")
    }
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


def test_health_check_url_builds_local_streamlit_path():
    assert smoke.health_check_url(18501) == "http://127.0.0.1:18501/_stcore/health"


@pytest.mark.parametrize("port", [0, -1, 65536, True])
def test_health_check_url_rejects_invalid_port(port):
    with pytest.raises(ValueError):
        smoke.health_check_url(port)


def test_safe_local_health_url_allowlists_loopback():
    url = "http://127.0.0.1:18501/_stcore/health"
    assert smoke._safe_local_health_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",
        "https://evil.example/steal",
        "http://127.0.0.1:18501/admin",
        "http://127.0.0.1:18501/_stcore/health?x=1",
        "http://user:pass@127.0.0.1:18501/_stcore/health",
    ],
)
def test_safe_local_health_url_rejects_non_allowlisted(url):
    with pytest.raises(ValueError, match="health URL"):
        smoke._safe_local_health_url(url)


def test_health_ok_does_not_urlopen_non_allowlisted():
    with patch("urllib.request.urlopen") as urlopen:
        assert smoke._health_ok("http://evil.example/steal") is False
        urlopen.assert_not_called()


def test_health_ok_urlopens_allowlisted_local_health():
    resp = MagicMock()
    resp.status = 200
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    with patch("urllib.request.urlopen", return_value=resp) as urlopen:
        assert smoke._health_ok("http://127.0.0.1:18501/_stcore/health") is True
        urlopen.assert_called_once()
        assert urlopen.call_args.args[0] == "http://127.0.0.1:18501/_stcore/health"


def test_release_workflow_gates_user_visible_steps():
    """Candidate build must not touch :next/:latest, the release or HA pins before approval."""
    text = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    assert "build_container --target all --push --versioned-only" in text
    assert "--draft" in text
    assert "environment: release-approval" in text
    assert "needs: [release, addon_smoke, addon_lint, qemu_smoke]" in text
    assert "needs: [release, promote]" in text
    assert "scripts.ha_addon_smoke" in text


def test_release_workflow_addon_lint_checks_out_tag():
    """addon_lint must lint the tagged candidate, not a main that moved on since the tag."""
    text = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    job = text.split("\n  addon_lint:\n", 1)[1].split("\n  promote:\n", 1)[0]
    assert "ref: ${{ needs.release.outputs.tag }}" in job
    assert "ref: main" not in job


def test_release_workflow_dev_builds_stop_before_publish():
    """-dev tags build :<version> candidates only: no notes, no release, no promote, no pin."""
    text = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    release_job = text.split("\n  release:\n", 1)[1].split("\n  addon_smoke:\n", 1)[0]
    for step in (
        "Release notes gate",
        "Prepare release notes",
        "Create GitHub Release (draft until approval)",
    ):
        block = release_job.split(f"- name: {step}", 1)[1].split("- name:", 1)[0]
        assert "if: steps.version.outputs.dev != 'true'" in block, step
    promote = text.split("\n  promote:\n", 1)[1].split("\n    steps:\n", 1)[0]
    assert "needs.release.outputs.dev != 'true'" in promote
    addon_publish = (RELEASE_WORKFLOW.parent / "ha-addon-publish.yml").read_text(encoding="utf-8")
    assert '"$VERSION" == *-dev*' in addon_publish


def test_release_workflow_targets_select_docker_or_ha():
    """targets=docker skips everything add-on; targets=ha keeps :next/:latest untouched."""
    text = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    assert "      targets:\n" in text.split("\njobs:\n", 1)[0]
    gate = text.split("- name: Version gate", 1)[1].split("- name:", 1)[0]
    assert "scripts.release_targets" in gate  # tag push → targets line of the tag message
    assert 'echo "targets=${TARGETS}" >> "$GITHUB_OUTPUT"' in gate
    release_job = text.split("\n  release:\n", 1)[1].split("\n  addon_smoke:\n", 1)[0]
    addon_build = release_job.split("- name: Build and push HA add-on images", 1)[1].split("- name:", 1)[0]
    assert "if: steps.version.outputs.targets != 'docker'" in addon_build
    for job in ("addon_smoke", "addon_lint", "publish_ha_addon"):
        head = text.split(f"\n  {job}:\n", 1)[1].split("\n    steps:\n", 1)[0]
        assert "if: needs.release.outputs.targets != 'docker'" in head, job
    promote = text.split("\n  promote:\n", 1)[1].split("\n  publish_ha_addon:\n", 1)[0]
    assert "needs.release.outputs.targets == 'docker'" in promote.split("\n    steps:\n", 1)[0]
    floating = promote.split("- name: Promote floating tags", 1)[1].split("- name:", 1)[0]
    assert "if: needs.release.outputs.targets != 'ha'" in floating
    publish = promote.split("- name: Publish GitHub Release", 1)[1].split("run:", 1)[0]
    assert "if:" not in publish  # the GitHub Release is always published


def test_release_workflow_builds_are_idempotent():
    """Re-runs reuse :<version> images of the same commit instead of rebuilding them."""
    text = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    release_job = text.split("\n  release:\n", 1)[1].split("\n  addon_smoke:\n", 1)[0]
    assert release_job.count("scripts.release_image_gate") == 2
    base = release_job.split("- name: Build and push multi-arch image", 1)[1].split("- name:", 1)[0]
    assert "if: steps.base_image.outputs.exists != 'true'" in base
    assert "--revision" in base
    assert "org.opencontainers.image.revision=${REVISION}" in release_job
