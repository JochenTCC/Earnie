# tests/test_pyproject_metadata.py
from __future__ import annotations

import tomllib
from pathlib import Path

from version import __version__


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
