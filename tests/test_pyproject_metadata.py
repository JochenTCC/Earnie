# tests/test_pyproject_metadata.py
from __future__ import annotations

import tomllib
from pathlib import Path

from version import (
    __version__,
    display_version,
    normalize_for_image_build,
    rewrite_version_file_for_image,
)


def test_pyproject_uses_version_py_as_source_of_truth():
    data = tomllib.loads((Path("pyproject.toml")).read_text(encoding="utf-8"))
    dynamic = data["project"].get("dynamic", [])
    assert "version" in dynamic
    version_attr = data["tool"]["setuptools"]["dynamic"]["version"]["attr"]
    assert version_attr == "version.__version__"
    assert __version__


def test_requirements_txt_installs_project():
    text = Path("requirements.txt").read_text(encoding="utf-8")
    assert "." in text


def test_normalize_for_image_build_keeps_prerelease():
    assert normalize_for_image_build("2.6.0-alpha.7") == "2.6.0-alpha.7"
    assert normalize_for_image_build("2.6.1-beta.1") == "2.6.1-beta.1"
    assert normalize_for_image_build("2.6.0-rc.1") == "2.6.0-rc.1"
    assert normalize_for_image_build("2.5.3") == "2.5.3"
    assert normalize_for_image_build("2.0.0 (wip)") == "2.0.0"
    assert normalize_for_image_build("2.6.0-alpha.7 (wip)") == "2.6.0-alpha.7"


def test_display_version_marks_candidate(monkeypatch):
    import version as version_mod

    monkeypatch.setattr(version_mod, "__version__", "2.6.0-alpha.7")
    assert display_version() == "2.6.0-alpha.7 (candidate)"
    monkeypatch.setattr(version_mod, "__version__", "2.5.3")
    assert display_version() == "2.5.3"


def test_rewrite_version_file_for_image_preserves_helpers(tmp_path):
    target = tmp_path / "version.py"
    target.write_text(
        '"""doc"""\n\n__version__ = "2.6.0-alpha.7 (wip)"\n\n'
        "def display_version() -> str:\n    return __version__\n",
        encoding="utf-8",
    )
    assert rewrite_version_file_for_image(target) == "2.6.0-alpha.7"
    text = target.read_text(encoding="utf-8")
    assert '__version__ = "2.6.0-alpha.7"' in text
    assert "def display_version()" in text
