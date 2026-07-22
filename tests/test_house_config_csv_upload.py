"""Hauskonfigurator: CSV upload naming (resampled from original)."""
from __future__ import annotations

from pathlib import Path

from ui.house_config_io import (
    _resampled_upload_csv_name,
    _stable_upload_csv_name,
    save_profile_consumption_csv,
)


def test_stable_upload_csv_name_per_role_and_consumer():
    assert _stable_upload_csv_name("haus", role="verbrauch") == "haus_verbrauch.csv"
    assert _stable_upload_csv_name("haus", role="pv") == "haus_pv.csv"
    assert _stable_upload_csv_name("haus", consumer_id="ev") == "haus_ev.csv"
    assert _stable_upload_csv_name("haus") == "haus_verbrauch.csv"


def test_resampled_upload_csv_name_from_original():
    assert (
        _resampled_upload_csv_name(
            "BEZUG-2025-22.7.2026.csv",
            fallback="haus_verbrauch.csv",
        )
        == "BEZUG-2025-22.7.2026_resampled.csv"
    )
    assert (
        _resampled_upload_csv_name(
            r"C:\tmp\BEZUG-2025-22.7.2026.csv",
            fallback="haus_verbrauch.csv",
        )
        == "BEZUG-2025-22.7.2026_resampled.csv"
    )
    assert (
        _resampled_upload_csv_name(
            "already_resampled.csv",
            fallback="haus_verbrauch.csv",
        )
        == "already_resampled.csv"
    )
    assert (
        _resampled_upload_csv_name("", fallback="haus_verbrauch.csv")
        == "haus_verbrauch.csv"
    )


def test_save_profile_consumption_csv_uses_resampled_name(
    tmp_path: Path, monkeypatch
):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setenv("EARNIE_CONFIG_PATH", str(config_dir))
    monkeypatch.setattr(
        "house_config.consumption_csv.normalize_profile_csv_file",
        lambda path, min_hours=8760: path,
    )
    first = save_profile_consumption_csv(
        "mein_haus",
        b"a",
        "BEZUG-2025-22.7.2026.csv",
        role="verbrauch",
        normalize=False,
    )
    second = save_profile_consumption_csv(
        "mein_haus",
        b"b",
        "BEZUG-2025-22.7.2026.csv",
        role="verbrauch",
        normalize=False,
    )
    expected = "config/uploads/BEZUG-2025-22.7.2026_resampled.csv"
    assert first == second == expected
    from runtime_store.persist_paths import resolve_config_prefixed_path, resolve_uploads_dir

    assert Path(resolve_config_prefixed_path(first)).read_bytes() == b"b"
    other = save_profile_consumption_csv(
        "mein_haus",
        b"c",
        "other_name.csv",
        role="verbrauch",
        normalize=False,
    )
    assert other == "config/uploads/other_name_resampled.csv"
    uploads = sorted(p.name for p in Path(resolve_uploads_dir()).glob("*.csv"))
    assert uploads == [
        "BEZUG-2025-22.7.2026_resampled.csv",
        "other_name_resampled.csv",
    ]
