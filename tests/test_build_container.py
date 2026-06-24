# tests/test_build_container.py
from __future__ import annotations

from pathlib import Path

import pytest

from scripts import build_container as bc
from version import __version__


def test_default_tags_include_latest_and_version():
    tags = bc.default_tags()
    assert f"ghcr.io/jochentcc/ernie-energy:latest" in tags
    assert f"ghcr.io/jochentcc/ernie-energy:{__version__}" in tags


def test_build_command_assembles_docker_args(tmp_path):
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("FROM python:3.14-slim\n", encoding="utf-8")

    cmd = bc.build_command(
        tags=["ghcr.io/example/ernie:test"],
        platform="linux/amd64",
        dockerfile=dockerfile,
        context=tmp_path,
        no_cache=True,
    )

    assert cmd[0:2] == ["docker", "build"]
    assert "--platform" in cmd and "linux/amd64" in cmd
    assert "-t" in cmd and "ghcr.io/example/ernie:test" in cmd
    assert "--no-cache" in cmd
    assert str(tmp_path) in cmd


def test_build_command_requires_existing_dockerfile(tmp_path):
    with pytest.raises(FileNotFoundError):
        bc.build_command(
            tags=["img:tag"],
            platform="linux/amd64",
            dockerfile=tmp_path / "missing",
            context=tmp_path,
            no_cache=False,
        )


def test_parse_args_custom_tag():
    args = bc.parse_args(["--tag", "myregistry/ernie:custom"])
    assert args.tags == ["myregistry/ernie:custom"]
    assert args.platform == "linux/amd64"
