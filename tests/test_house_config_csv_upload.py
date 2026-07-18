"""Hauskonfigurator: single CSV upload path stability."""
from __future__ import annotations

from pathlib import Path

from ui.house_config_io import _stable_upload_csv_name, save_profile_consumption_csv


def test_stable_upload_csv_name_per_role_and_consumer():
    assert _stable_upload_csv_name("haus", role="verbrauch") == "haus_verbrauch.csv"
    assert _stable_upload_csv_name("haus", role="pv") == "haus_pv.csv"
    assert _stable_upload_csv_name("haus", consumer_id="ev") == "haus_ev.csv"
    assert _stable_upload_csv_name("haus") == "haus_verbrauch.csv"


def test_save_profile_consumption_csv_overwrites_same_path(
    tmp_path: Path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "house_config.consumption_csv.normalize_profile_csv_file",
        lambda path, min_hours=8760: path,
    )
    first = save_profile_consumption_csv(
        "mein_haus",
        b"a",
        "first.csv",
        role="verbrauch",
        normalize=False,
    )
    second = save_profile_consumption_csv(
        "mein_haus",
        b"b",
        "other_name.csv",
        role="verbrauch",
        normalize=False,
    )
    assert first == second == "config/uploads/mein_haus_verbrauch.csv"
    from runtime_store.persist_paths import resolve_config_prefixed_path, resolve_uploads_dir

    assert Path(resolve_config_prefixed_path(first)).read_bytes() == b"b"
    uploads = list(Path(resolve_uploads_dir()).glob("*.csv"))
    assert len(uploads) == 1
