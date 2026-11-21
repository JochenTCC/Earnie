"""Sidebar "Sichern & Übertragen" → Support-Paket helpers."""
from __future__ import annotations

import io
import zipfile
from types import SimpleNamespace

from ui.support_package import CONFIG_PACK_ARCNAME, build_config_only_bundle_bytes


def test_config_only_bundle_has_pack_and_attachments_but_no_history():
    attachment = SimpleNamespace(name="notiz.txt", getvalue=lambda: b"hello")
    payload = build_config_only_bundle_bytes(
        [attachment],
        config_pack=b"PK\x03\x04fake",
    )
    with zipfile.ZipFile(io.BytesIO(payload), "r") as archive:
        names = set(archive.namelist())
    assert names == {CONFIG_PACK_ARCNAME, "anhänge/notiz.txt"}


def test_config_only_bundle_without_attachments():
    payload = build_config_only_bundle_bytes(None, config_pack=b"pack")
    with zipfile.ZipFile(io.BytesIO(payload), "r") as archive:
        assert archive.namelist() == [CONFIG_PACK_ARCNAME]
        assert archive.read(CONFIG_PACK_ARCNAME) == b"pack"


def test_full_support_package_passes_full_history_flag(monkeypatch):
    from ui import support_package

    calls = []
    monkeypatch.setattr(
        support_package, "write_debug_dump_zip", lambda **kwargs: calls.append(kwargs) or "x.zip"
    )
    support_package.save_full_support_package(title="t", symptom="s", attachments=[])
    support_package.save_full_support_package(
        title="t", symptom="s", attachments=[], full_history=True
    )
    assert [call["full_history"] for call in calls] == [False, True]


def test_redact_secrets_removes_passwords_and_tokens():
    from runtime_store.secret_redaction import REDACTED, redact_secrets

    doc = {"ehal": {"openems": {"host": "h", "password": "pw"}}, "list": [{"api_token": "t"}]}
    out = redact_secrets(doc)
    assert out["ehal"]["openems"] == {"host": "h", "password": REDACTED}
    assert out["list"][0]["api_token"] == REDACTED
    assert doc["ehal"]["openems"]["password"] == "pw"


def test_support_config_pack_has_no_secret_and_no_uploads(tmp_path, monkeypatch):
    import io
    import json
    import zipfile

    from runtime_store import config_pack

    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"ehal": {"openems": {"password": "pw"}}}), encoding="utf-8")
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (uploads / "cons.csv").write_text("x", encoding="utf-8")
    monkeypatch.setattr(
        config_pack, "PACK_JSON_FILES", (("config.json", lambda: str(cfg)),)
    )
    monkeypatch.setattr(config_pack, "resolve_uploads_dir", lambda: str(uploads))

    with zipfile.ZipFile(io.BytesIO(config_pack.build_config_pack_bytes(for_support=True))) as z:
        names = z.namelist()
        assert "pw" not in z.read("config.json").decode("utf-8")
    assert not [n for n in names if n.startswith("uploads/")]
    with zipfile.ZipFile(io.BytesIO(config_pack.build_config_pack_bytes())) as z:
        assert "uploads/cons.csv" in z.namelist()
