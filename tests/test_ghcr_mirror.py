"""scripts.ghcr_mirror — copy release images to the organisation GHCR namespace."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts import ghcr_mirror as gm

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"


def test_org_image_ref_swaps_namespace_only():
    assert (
        gm.org_image_ref("ghcr.io/jochentcc/earnie-addon-aarch64:2.8.0-dev.3")
        == "ghcr.io/earnie-hems/earnie-addon-aarch64:2.8.0-dev.3"
    )


@pytest.mark.parametrize(
    ("image", "match"),
    [
        ("ghcr.io/someone/earnie-energy:2.8.0", "not in the namespace"),
        ("ghcr.io/earnie-hems/earnie-energy:2.8.0", "not in the namespace"),
        ("ghcr.io/jochentcc/earnie-energy", "no tag"),
        ("ghcr.io/jochentcc/", "no tag"),
    ],
)
def test_org_image_ref_rejects_foreign_or_untagged(image, match):
    with pytest.raises(ValueError, match=match):
        gm.org_image_ref(image)


def test_mirror_command_copies_manifest_without_rebuild():
    assert gm.mirror_command("ghcr.io/jochentcc/earnie-energy:2.8.0") == [
        "docker", "buildx", "imagetools", "create",
        "-t", "ghcr.io/earnie-hems/earnie-energy:2.8.0",
        "ghcr.io/jochentcc/earnie-energy:2.8.0",
    ]


def test_main_runs_one_copy_per_image(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(cmd, check):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(gm.subprocess, "run", fake_run)
    images = ["ghcr.io/jochentcc/earnie-addon-amd64:2.8.0", "ghcr.io/jochentcc/earnie-addon-aarch64:2.8.0"]
    assert gm.main([arg for image in images for arg in ("--image", image)]) == 0
    assert calls == [gm.mirror_command(image) for image in images]


def test_main_fails_loud_when_copy_fails(monkeypatch, capsys):
    monkeypatch.setattr(
        gm.subprocess, "run", lambda cmd, check: subprocess.CompletedProcess(cmd, 1)
    )
    assert gm.main(["--image", "ghcr.io/jochentcc/earnie-energy:2.8.0"]) == 1
    assert "ghcr.io/earnie-hems" in capsys.readouterr().err


def test_main_rejects_foreign_image_before_any_copy(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(gm.subprocess, "run", lambda cmd, check: calls.append(cmd))
    assert gm.main(["--image", "ghcr.io/jochentcc/earnie-energy:2.8.0", "--image", "docker.io/x:1"]) == 1
    assert calls == []


def test_release_workflow_mirrors_base_and_addon_images():
    text = (WORKFLOWS / "release-publish.yml").read_text(encoding="utf-8")
    assert 'python -m scripts.ghcr_mirror --image "ghcr.io/jochentcc/earnie-energy:${VERSION}"' in text
    assert 'python -m scripts.ghcr_mirror --image "$IMAGE"' in text


def test_addon_publish_workflow_mirrors_rebuilt_addon_images():
    text = (WORKFLOWS / "ha-addon-publish.yml").read_text(encoding="utf-8")
    assert 'python -m scripts.ghcr_mirror --image "$IMAGE"' in text


def test_qemu_smoke_checks_org_namespace_has_same_digest():
    text = (WORKFLOWS / "qemu-image-smoke.yml").read_text(encoding="utf-8")
    assert 'ORG_IMAGE="ghcr.io/earnie-hems/earnie-energy:${VERSION}"' in text
