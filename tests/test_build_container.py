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
    assert "ghcr.io/jochentcc/earnie-energy:next" in tags
    assert "ghcr.io/jochentcc/ernie-energy:next" in tags
    if bc.is_prerelease_version(__version__):
        assert "ghcr.io/jochentcc/earnie-energy:latest" not in tags
        assert "ghcr.io/jochentcc/ernie-energy:latest" not in tags
    else:
        assert "ghcr.io/jochentcc/earnie-energy:latest" in tags
        assert "ghcr.io/jochentcc/ernie-energy:latest" in tags


def test_default_tags_dual_publish_org_namespace_keeps_personal_namespace():
    """GitHub organisation move, Step 1: both namespaces get every tag; the default stays personal."""
    assert bc.DEFAULT_REGISTRY_IMAGE == "ghcr.io/jochentcc/earnie-energy"
    for ver in ("2.8.0", "2.8.0-dev.3"):
        tags = bc.default_tags(ver)
        personal = [t.split("/", 2)[2] for t in tags if t.startswith("ghcr.io/jochentcc/earnie-energy:")]
        org = [t.split("/", 2)[2] for t in tags if t.startswith("ghcr.io/earnie-hems/")]
        assert personal and org == personal


def test_promote_commands_set_org_floating_tags_from_org_version():
    cmds = bc.promote_commands("2.8.0")
    for tag in ("latest", "next"):
        assert [
            "docker", "buildx", "imagetools", "create",
            "-t", f"ghcr.io/earnie-hems/earnie-energy:{tag}",
            "ghcr.io/earnie-hems/earnie-energy:2.8.0",
        ] in cmds


def test_is_dev_version_only_for_dev_builds():
    assert bc.is_dev_version("2.8.0-dev.4") is True
    for version in ("2.8.0", "2.8.0-alpha.1", "2.8.0-beta.1", "2.8.0-rc.1"):
        assert bc.is_dev_version(version) is False


def test_stage_shadow_client_copies_every_client_file(tmp_path: Path):
    from runtime_store.shadow.hooks import CLIENT_FILES

    bc.stage_shadow_client(tmp_path)

    staged = {p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()}
    assert staged == set(CLIENT_FILES)


@pytest.mark.parametrize("platform", ["linux/amd64", bc.MULTIARCH_PLATFORM])
def test_build_command_passes_shadow_client_context_only_when_given(platform: str, tmp_path: Path):
    common = {
        "tags": ["img:1"],
        "platform": platform,
        "dockerfile": bc.REPO_ROOT / "docker" / "Dockerfile",
        "context": bc.REPO_ROOT,
        "no_cache": False,
        "push": True,
    }

    assert "--build-context" not in bc.build_command(**common)

    cmd = bc.build_command(**common, shadow_client_dir=tmp_path)
    assert cmd[cmd.index("--build-context") + 1] == f"shadow-client={tmp_path}"


def test_dockerfile_default_shadow_client_stage_has_no_client_and_is_not_empty():
    """Without the build context (release, CI) the stage adds no client file.

    It must not be empty: BuildKit then reuses the dev build's cached COPY layer, and a
    plain build ends up with the Shadow client.
    """
    text = (bc.REPO_ROOT / "docker" / "Dockerfile").read_text(encoding="utf-8")
    assert (
        f"FROM scratch AS {bc.SHADOW_CLIENT_STAGE}\n"
        "COPY logger_config.py /logger_config.py\n"
    ) in text
    assert f"COPY --from={bc.SHADOW_CLIENT_STAGE} / ./\n" in text


def test_is_prerelease_version():
    assert bc.is_prerelease_version("2.2.0-alpha.1") is True
    assert bc.is_prerelease_version("2.6.1-beta.1") is True
    assert bc.is_prerelease_version("2.2.0-rc.1") is True
    assert bc.is_prerelease_version("2.2.0") is False


def test_default_tags_prerelease_omits_latest():
    tags = bc.default_tags("2.2.0-alpha.1")
    assert tags == [
        "ghcr.io/jochentcc/earnie-energy:next",
        "ghcr.io/jochentcc/earnie-energy:2.2.0-alpha.1",
        "ghcr.io/jochentcc/ernie-energy:next",
        "ghcr.io/jochentcc/ernie-energy:2.2.0-alpha.1",
        "ghcr.io/earnie-hems/earnie-energy:next",
        "ghcr.io/earnie-hems/earnie-energy:2.2.0-alpha.1",
    ]


def test_default_tags_official_includes_latest_and_next():
    tags = bc.default_tags("2.2.0")
    assert "ghcr.io/jochentcc/earnie-energy:latest" in tags
    assert "ghcr.io/jochentcc/earnie-energy:next" in tags
    assert "ghcr.io/jochentcc/earnie-energy:2.2.0" in tags


def test_versioned_and_floating_tags_partition_default_tags():
    for ver in ("2.2.0", "2.2.0-alpha.1"):
        versioned = bc.versioned_tags(ver)
        floating = bc.floating_tags(ver)
        assert sorted(versioned + floating) == sorted(bc.default_tags(ver))
        assert versioned == [
            f"ghcr.io/jochentcc/earnie-energy:{ver}",
            f"ghcr.io/jochentcc/ernie-energy:{ver}",
            f"ghcr.io/earnie-hems/earnie-energy:{ver}",
        ]


def test_floating_tags_prerelease_only_next():
    assert bc.floating_tags("2.2.0-alpha.1") == [
        "ghcr.io/jochentcc/earnie-energy:next",
        "ghcr.io/jochentcc/ernie-energy:next",
        "ghcr.io/earnie-hems/earnie-energy:next",
    ]


def test_promote_commands_retag_from_version_without_rebuild():
    cmds = bc.promote_commands("2.2.0")
    assert [
        "docker", "buildx", "imagetools", "create",
        "-t", "ghcr.io/jochentcc/earnie-energy:latest",
        "ghcr.io/jochentcc/earnie-energy:2.2.0",
    ] in cmds
    assert len(cmds) == len(bc.floating_tags("2.2.0"))
    assert all(cmd[-1].endswith(":2.2.0") for cmd in cmds)


def test_main_promote_runs_only_retags(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(bc, "run_build", calls.append)
    assert bc.main(["--promote"]) == 0
    assert calls == bc.promote_commands()


def test_main_versioned_only_builds_without_floating_tags(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(bc, "run_build", calls.append)
    assert bc.main(["--target", "synology", "--versioned-only"]) == 0
    tagged = [calls[0][i + 1] for i, arg in enumerate(calls[0]) if arg == "-t"]
    assert tagged == bc.versioned_tags()


def test_main_labels_image_with_normalized_version(monkeypatch):
    """LoxBerry plugin reads org.opencontainers.image.version of :latest / :next."""
    calls: list[list[str]] = []
    monkeypatch.setattr(bc, "run_build", calls.append)
    monkeypatch.setattr(bc, "__version__", "2.7.0-dev.48D1")
    assert bc.main(["--target", "synology", "--versioned-only"]) == 0
    labels = [calls[0][i + 1] for i, arg in enumerate(calls[0]) if arg == "--label"]
    assert labels == ["org.opencontainers.image.version=2.7.0-dev.48"]


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
    assert "--build-arg" in cmd
    assert any(a.startswith("BUILD_DATE=") for a in cmd)
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
    assert "--build-arg" in cmd
    assert any(a.startswith("BUILD_DATE=") for a in cmd)
    assert "--push" in cmd
    assert cmd[1] == "buildx"


def test_build_command_revision_adds_oci_label(tmp_path):
    """Release builds carry the commit so scripts.release_image_gate can reuse them."""
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("FROM python:3.14-slim\n", encoding="utf-8")

    cmd = bc.build_command(
        tags=["ghcr.io/example/earnie:1.0.0"],
        platform=bc.MULTIARCH_PLATFORM,
        dockerfile=dockerfile,
        context=tmp_path,
        no_cache=False,
        push=True,
        revision="abc123",
    )

    assert cmd[cmd.index("--label") + 1] == "org.opencontainers.image.revision=abc123"


def test_build_command_version_adds_oci_label(tmp_path):
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("FROM python:3.14-slim\n", encoding="utf-8")

    cmd = bc.build_command(
        tags=["ghcr.io/example/earnie:1.0.0"],
        platform=bc.MULTIARCH_PLATFORM,
        dockerfile=dockerfile,
        context=tmp_path,
        no_cache=False,
        push=True,
        revision="abc123",
        version="1.0.0",
    )

    labels = [cmd[i + 1] for i, arg in enumerate(cmd) if arg == "--label"]
    assert labels == [
        "org.opencontainers.image.revision=abc123",
        "org.opencontainers.image.version=1.0.0",
    ]


def test_build_command_without_revision_has_no_label(tmp_path):
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("FROM python:3.14-slim\n", encoding="utf-8")

    cmd = bc.build_command(
        tags=["ghcr.io/example/earnie:test"],
        platform="linux/amd64",
        dockerfile=dockerfile,
        context=tmp_path,
        no_cache=False,
        push=False,
    )

    assert "--label" not in cmd


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


def test_deploy_tariff_gate_passes_on_shipped_files(capsys):
    """The release build runs this gate; a red gate must show up in the suite, not in CI."""
    bc._run_deploy_tariff_gate()
    assert "Deploy-Gate: Tarifkatalog OK." in capsys.readouterr().out


def test_deploy_tariff_gate_checks_example_scenarios_against_example_tariffs(
    tmp_path, monkeypatch
):
    share = tmp_path / "share" / "config"
    share.mkdir(parents=True)
    src = Path(bc.REPO_ROOT) / "share" / "config"
    for name in ("tariffs.json", "tariffs.example.json", "tariffs.schema.json"):
        (share / name).write_bytes((src / name).read_bytes())
    scenarios = (src / "backtesting_scenarios.example.json").read_text(encoding="utf-8-sig")
    (share / "backtesting_scenarios.example.json").write_text(
        scenarios.replace('"fixed_37ct"', '"at_verbund_v_strom_sonneneinspeisung_fix"', 1),
        encoding="utf-8",
    )
    tools_src = Path(bc.REPO_ROOT) / "tools" / "tariff_catalog"
    tools_dst = tmp_path / "tools" / "tariff_catalog"
    tools_dst.mkdir(parents=True)
    for name in ("stromtarife_dach_kombiniert.json", "einspeisetarife_dach_erweitert.json"):
        (tools_dst / name).write_bytes((tools_src / name).read_bytes())
    monkeypatch.setattr(bc, "REPO_ROOT", tmp_path)
    with pytest.raises(ValueError, match="tariffs.example.json.*at_verbund_v_strom_sonneneinspeisung_fix"):
        bc._run_deploy_tariff_gate()
