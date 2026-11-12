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
