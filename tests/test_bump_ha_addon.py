# tests/test_bump_ha_addon.py
from __future__ import annotations

from pathlib import Path

from scripts import bump_ha_addon as bha


def _write_addon_tree(base: Path) -> None:
    (base / "build.yaml").write_text(
        "\n".join(
            [
                "build_from:",
                "  aarch64: ghcr.io/jochentcc/earnie-energy:0.1.0",
                "  amd64: ghcr.io/jochentcc/earnie-energy:0.1.0",
                "",
                "args:",
                '  EARNIE_VERSION: "0.1.0"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    (base / "config.yaml").write_text('version: "0.1.0"\n', encoding="utf-8")
    (base / "Dockerfile").write_text("ARG EARNIE_VERSION=0.1.0\nFROM scratch\n", encoding="utf-8")
    (base / "CHANGELOG.md").write_text(
        "# Changelog\n\n## 0.1.0\n\n- Initial.\n",
        encoding="utf-8",
    )


def test_bump_build_yaml_updates_all_pins():
    before = (Path(bha.ADDON_DIR) / "build.yaml").read_text(encoding="utf-8")
    after = bha.bump_build_yaml(before, "2.5.0-alpha.9")
    assert "ghcr.io/jochentcc/earnie-energy:2.5.0-alpha.9" in after
    assert 'EARNIE_VERSION: "2.5.0-alpha.9"' in after
    assert "2.5.0-alpha.8" not in after


def test_bump_config_yaml_sets_mirrored_version():
    after = bha.bump_config_yaml('version: "0.1.0"\n', "2.5.0")
    assert after == 'version: "2.5.0"\n'


def test_bump_dockerfile_updates_arg_default():
    after = bha.bump_dockerfile("ARG EARNIE_VERSION=2.4.0\n", "2.5.0")
    assert after == "ARG EARNIE_VERSION=2.5.0\n"


def test_bump_changelog_prepends_new_section(tmp_path: Path, monkeypatch):
    notes_dir = tmp_path / "release-notes"
    notes_dir.mkdir()
    monkeypatch.setattr(bha, "RELEASE_NOTES_DIR", notes_dir)
    addon_dir = tmp_path / "earnie"
    addon_dir.mkdir()
    _write_addon_tree(addon_dir)
    before = (addon_dir / "CHANGELOG.md").read_text(encoding="utf-8")
    after = bha.bump_changelog(before, "2.5.0")
    assert after.index("## 2.5.0") < after.index("## 0.1.0")
    assert "Pins Earnie `2.5.0`" in after


def test_bump_changelog_idempotent(tmp_path: Path):
    addon_dir = tmp_path / "earnie"
    addon_dir.mkdir()
    _write_addon_tree(addon_dir)
    before = (addon_dir / "CHANGELOG.md").read_text(encoding="utf-8")
    once = bha.bump_changelog(before, "2.5.0")
    twice = bha.bump_changelog(once, "2.5.0")
    assert once == twice


def test_apply_bump_idempotent(tmp_path: Path):
    addon_dir = tmp_path / "earnie"
    addon_dir.mkdir()
    _write_addon_tree(addon_dir)
    assert bha.apply_bump("2.5.0", addon_dir=addon_dir) is True
    assert bha.apply_bump("2.5.0", addon_dir=addon_dir) is False


def test_apply_bump_updates_all_files(tmp_path: Path):
    addon_dir = tmp_path / "earnie"
    addon_dir.mkdir()
    _write_addon_tree(addon_dir)
    bha.apply_bump("2.5.0-alpha.9", addon_dir=addon_dir)
    build = (addon_dir / "build.yaml").read_text(encoding="utf-8")
    assert "2.5.0-alpha.9" in build
    assert (addon_dir / "config.yaml").read_text(encoding="utf-8") == 'version: "2.5.0-alpha.9"\n'
    assert (addon_dir / "Dockerfile").read_text(encoding="utf-8").startswith("ARG EARNIE_VERSION=2.5.0-alpha.9")


def test_release_notes_blurb_uses_first_non_heading_paragraph(tmp_path: Path, monkeypatch):
    notes_dir = tmp_path / "release-notes"
    notes_dir.mkdir()
    notes_dir.joinpath("v9.9.9.md").write_text(
        "# Title\n\nCustom release summary line.\n\nMore body.",
        encoding="utf-8",
    )
    monkeypatch.setattr(bha, "RELEASE_NOTES_DIR", notes_dir)
    assert bha._release_notes_blurb("9.9.9") == "Custom release summary line."
