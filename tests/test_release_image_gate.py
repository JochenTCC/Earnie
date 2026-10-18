# tests/test_release_image_gate.py
from __future__ import annotations

import pytest

from scripts import release_image_gate as gate

IMAGE = "ghcr.io/jochentcc/earnie-energy:2.7.0"
SHA = "abc123"


def _cfg(revision: str | None) -> dict:
    labels = {} if revision is None else {gate.REVISION_LABEL: revision}
    return {"config": {"Labels": labels}}


def test_missing_image_must_be_built():
    assert gate.decide(IMAGE, SHA, None) is False


def test_single_platform_same_revision_is_reused():
    assert gate.decide(IMAGE, SHA, _cfg(SHA)) is True


def test_multiarch_same_revision_is_reused():
    image_json = {"linux/amd64": _cfg(SHA), "linux/arm64": _cfg(SHA)}
    assert gate.decide(IMAGE, SHA, image_json) is True


def test_other_revision_fails_loud():
    """A rewritten tag must not silently ship the image of the old commit."""
    image_json = {"linux/amd64": _cfg("old"), "linux/arm64": _cfg("old")}
    with pytest.raises(gate.RevisionMismatchError, match="old"):
        gate.decide(IMAGE, SHA, image_json)


def test_mixed_revisions_fail_loud():
    image_json = {"linux/amd64": _cfg(SHA), "linux/arm64": _cfg("old")}
    with pytest.raises(gate.RevisionMismatchError):
        gate.decide(IMAGE, SHA, image_json)


def test_legacy_image_without_label_is_reused_with_warning(capsys):
    assert gate.decide(IMAGE, SHA, {"linux/amd64": _cfg(None)}) is True
    assert "::warning::" in capsys.readouterr().out


def test_main_writes_github_output(monkeypatch, tmp_path):
    out = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setattr(gate, "_inspect", lambda _image: _cfg(SHA))
    assert gate.main(["--image", IMAGE, "--revision", SHA]) == 0
    assert out.read_text(encoding="utf-8") == "exists=true\n"


def test_main_mismatch_exits_nonzero(monkeypatch, tmp_path):
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "out"))
    monkeypatch.setattr(gate, "_inspect", lambda _image: _cfg("old"))
    assert gate.main(["--image", IMAGE, "--revision", SHA]) == 1
    assert not (tmp_path / "out").exists()
