# tests/test_build_container.py
from __future__ import annotations

from pathlib import Path

import pytest

from scripts import build_container as bc
from version import __version__


def test_default_tags_follow_version_py():
    """``default_tags()`` without args mirrors ``version.__version__`` (latest only if official)."""
    tags = bc.default_tags()
    assert f"ghcr.io/jochentcc/earnie-energy:{__version__}" in tags
    assert f"ghcr.io/jochentcc/ernie-energy:{__version__}" in tags
    if bc.is_prerelease_version(__version__):
        assert "ghcr.io/jochentcc/earnie-energy:latest" not in tags
        assert "ghcr.io/jochentcc/ernie-energy:latest" not in tags
    else:
        assert "ghcr.io/jochentcc/earnie-energy:latest" in tags
        assert "ghcr.io/jochentcc/ernie-energy:latest" in tags


def test_is_prerelease_version():
    assert bc.is_prerelease_version("2.2.0-alpha.1") is True
    assert bc.is_prerelease_version("2.2.0-rc.1") is True
    assert bc.is_prerelease_version("2.2.0") is False


def test_default_tags_prerelease_omits_latest():
    tags = bc.default_tags("2.2.0-alpha.1")
    assert tags == [
        "ghcr.io/jochentcc/earnie-energy:2.2.0-alpha.1",
        "ghcr.io/jochentcc/ernie-energy:2.2.0-alpha.1",
    ]


def test_default_tags_official_includes_latest():
    tags = bc.default_tags("2.2.0")
    assert "ghcr.io/jochentcc/earnie-energy:latest" in tags
    assert "ghcr.io/jochentcc/earnie-energy:2.2.0" in tags


def test_build_command_assembles_docker_args(tmp_path):
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("FROM python:3.14-slim\n", encoding="utf-8")

    cmd = bc.build_command(
        tags=["ghcr.io/example/earnie:test"],
        platform="linux/amd64",
        dockerfile=dockerfile,
        context=tmp_path,
        no_cache=True,
        push=False,
    )

    assert cmd[0:2] == ["docker", "build"]
    assert "--platform" in cmd and "linux/amd64" in cmd
    assert "-t" in cmd and "ghcr.io/example/earnie:test" in cmd
    assert "--no-cache" in cmd
    assert str(tmp_path) in cmd


def test_build_command_multiarch_uses_buildx_and_push(tmp_path):
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("FROM python:3.14-slim\n", encoding="utf-8")

    cmd = bc.build_command(
        tags=["ghcr.io/example/earnie:latest"],
        platform=bc.MULTIARCH_PLATFORM,
        dockerfile=dockerfile,
        context=tmp_path,
        no_cache=False,
        push=True,
    )

    assert cmd[0:3] == ["docker", "buildx", "build"]
    assert "--platform" in cmd and bc.MULTIARCH_PLATFORM in cmd
    assert "--push" in cmd
    assert cmd[1] == "buildx"


def test_build_command_multiarch_without_push_raises(tmp_path):
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("FROM python:3.14-slim\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Multi-Arch-Build"):
        bc.build_command(
            tags=["ghcr.io/example/earnie:latest"],
            platform=bc.MULTIARCH_PLATFORM,
            dockerfile=dockerfile,
            context=tmp_path,
            no_cache=False,
            push=False,
        )


def test_build_command_requires_existing_dockerfile(tmp_path):
    with pytest.raises(FileNotFoundError):
        bc.build_command(
            tags=["img:tag"],
            platform="linux/amd64",
            dockerfile=tmp_path / "missing",
            context=tmp_path,
            no_cache=False,
            push=False,
        )


def test_resolve_platform_target_synology():
    assert bc.resolve_platform("synology", None) == "linux/amd64"


def test_resolve_platform_target_loxberry():
    assert bc.resolve_platform("loxberry", None) == "linux/arm64"


def test_resolve_platform_target_all():
    assert bc.resolve_platform("all", None) == bc.MULTIARCH_PLATFORM


def test_resolve_platform_target_and_platform_conflict():
    with pytest.raises(ValueError, match="Nur --target oder --platform"):
        bc.resolve_platform("synology", "linux/arm64")


def test_parse_args_custom_tag():
    args = bc.parse_args(["--tag", "myregistry/earnie:custom"])
    assert args.tags == ["myregistry/earnie:custom"]
    assert args.target is None


def test_parse_args_target_loxberry():
    args = bc.parse_args(["--target", "loxberry"])
    assert args.target == "loxberry"
    assert bc.resolve_platform(args.target, args.platform) == "linux/arm64"
