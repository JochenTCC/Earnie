"""SupportUpload P1: packed recorder (config snapshots, xz cycle segments) and the history window of debug dumps."""
from __future__ import annotations

import gzip
import json
import lzma
import zipfile
from datetime import date, datetime
from pathlib import Path

import pytest

from runtime_store import debug_dump_archive
from runtime_store.debug_dump_archive import extract_dump_to_dir, write_debug_dump_zip
from runtime_store.recorder_config_pack import (
    PACK_ARCNAME,
    PACK_FILENAME,
    ConfigPackError,
    build_config_pack,
    compress_segment_xz,
    expand_packed_configs,
    expand_recorder_dump,
    expand_xz_segments,
    segment_xz_arcname,
)
from tests.regression.intake import intake_debug_dump
from tests.test_debug_dump_archive import _dump_config


def _cons_csv(rows: int) -> str:
    lines = ["timestamp;total_kw;baseload_kw;pv_kw;source\n"]
    lines += [f"2026-10-{1 + i // 96:02d}T{(i % 96) // 4:02d}:{(i % 4) * 15:02d};{i % 7}.5;0.3;0;m\n" for i in range(rows)]
    return "".join(lines)


def _write_snapshot(configs: Path, name: str, files: dict[str, str]) -> Path:
    configs.mkdir(parents=True, exist_ok=True)
    path = configs / f"{name}.json"
    # Same writer as cycle_recorder._ensure_config_snapshot.
    with path.open("w", encoding="utf-8") as handle:
        json.dump({"schema": 1, "files": files}, handle, ensure_ascii=False)
    return path


def _growing_snapshots(configs: Path, count: int = 5) -> list[Path]:
    return [
        _write_snapshot(
            configs,
            f"hash{i:02d}",
            {
                "inputs/config.json": '{\n  "name": "Häuschen"\n}\n',
                "inputs/cons_data.csv": _cons_csv(800 + 10 * i),
            },
        )
        for i in range(count)
    ]


def test_config_pack_round_trip_is_byte_identical_and_small(tmp_path):
    paths = _growing_snapshots(tmp_path / "src" / "configs")
    originals = {path.name: path.read_bytes() for path in paths}
    data, summary = build_config_pack(paths)
    assert summary["snapshot_count"] == 5
    assert summary["raw_snapshot_count"] == 0
    assert summary["packed_bytes"] * 3 < summary["original_bytes"]

    recorder = tmp_path / "dst"
    recorder.mkdir()
    (recorder / PACK_FILENAME).write_bytes(data)
    assert expand_packed_configs(recorder) == 5
    assert not (recorder / PACK_FILENAME).exists()
    rebuilt = {path.name: path.read_bytes() for path in (recorder / "configs").glob("*.json")}
    assert rebuilt == originals


def test_config_pack_keeps_unusual_snapshot_raw(tmp_path):
    configs = tmp_path / "configs"
    configs.mkdir()
    odd = configs / "odd.json"
    odd.write_text(json.dumps({"schema": 1, "files": {"a": "x\n"}}, indent=2), encoding="utf-8")
    data, summary = build_config_pack([odd])
    assert summary["raw_snapshot_count"] == 1
    recorder = tmp_path / "dst"
    recorder.mkdir()
    (recorder / PACK_FILENAME).write_bytes(data)
    expand_packed_configs(recorder)
    assert (recorder / "configs" / "odd.json").read_bytes() == odd.read_bytes()


def test_config_pack_checksum_mismatch_fails_loud(tmp_path):
    paths = _growing_snapshots(tmp_path / "configs", count=2)
    data, _ = build_config_pack(paths)
    pack = json.loads(data)
    pack["lines"][1] = "tampered\n"
    recorder = tmp_path / "dst"
    recorder.mkdir()
    (recorder / PACK_FILENAME).write_text(json.dumps(pack), encoding="utf-8")
    with pytest.raises(ConfigPackError, match="sha256"):
        expand_packed_configs(recorder)
    assert (recorder / PACK_FILENAME).exists()


def test_config_pack_does_not_overwrite_different_file(tmp_path):
    paths = _growing_snapshots(tmp_path / "configs", count=1)
    data, _ = build_config_pack(paths)
    recorder = tmp_path / "dst"
    (recorder / "configs").mkdir(parents=True)
    (recorder / "configs" / "hash00.json").write_text("{}", encoding="utf-8")
    (recorder / PACK_FILENAME).write_bytes(data)
    with pytest.raises(ConfigPackError, match="different content"):
        expand_packed_configs(recorder)


def test_config_pack_rejects_unknown_format(tmp_path):
    (tmp_path / PACK_FILENAME).write_text('{"format": 99}', encoding="utf-8")
    with pytest.raises(ConfigPackError, match="format"):
        expand_packed_configs(tmp_path)


def test_config_pack_rejects_snapshot_name_that_leaves_configs(tmp_path):
    """A dump is foreign input: a snapshot name with path parts must not become a file path."""
    import hashlib

    recorder = tmp_path / "dump" / "recorder"
    recorder.mkdir(parents=True)
    raw = "{}"
    pack = {
        "format": 1,
        "lines": [],
        "snapshots": {"../../escaped": {"sha256": hashlib.sha256(raw.encode()).hexdigest(), "raw": raw}},
    }
    (recorder / PACK_FILENAME).write_text(json.dumps(pack), encoding="utf-8")

    with pytest.raises(ConfigPackError, match="plain file stem"):
        expand_packed_configs(recorder)

    assert not (tmp_path / "escaped.json").exists()
    assert (recorder / PACK_FILENAME).is_file()


def test_expand_without_pack_is_noop(tmp_path):
    assert expand_packed_configs(tmp_path) == 0
    assert expand_recorder_dump(tmp_path) == {"configs": 0, "segments": 0}
    assert expand_xz_segments(tmp_path / "missing") == 0


def _gz_segment(root: Path, day: str, text: bytes) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"cycles_{day}.jsonl.gz"
    with gzip.open(path, "wb") as handle:
        handle.write(text)
    return path


_LINE_1 = b'{"n": 1}\n'


def _repeating_cycles(count: int = 200) -> bytes:
    block = json.dumps({"matrix": list(range(3000))})
    return "".join(
        json.dumps({"n": i, "block": block}) + "\n" for i in range(count)
    ).encode("utf-8")


def test_segment_xz_round_trip_keeps_jsonl_text_and_is_small(tmp_path):
    text = _repeating_cycles()
    gz_path = _gz_segment(tmp_path / "src", "2026-11-18", text)
    xz_bytes, text_len = compress_segment_xz(gz_path)
    assert text_len == len(text)
    assert len(xz_bytes) * 3 < gz_path.stat().st_size

    recorder = tmp_path / "dst"
    recorder.mkdir()
    (recorder / "cycles_2026-11-18.jsonl.xz").write_bytes(xz_bytes)
    assert expand_xz_segments(recorder) == 1
    assert not (recorder / "cycles_2026-11-18.jsonl.xz").exists()
    with gzip.open(recorder / "cycles_2026-11-18.jsonl.gz", "rb") as handle:
        assert handle.read() == text


def test_segment_xz_arcname_requires_a_gz_segment():
    assert segment_xz_arcname("recorder/cycles_2026-11-18.jsonl.gz") == (
        "recorder/cycles_2026-11-18.jsonl.xz"
    )
    with pytest.raises(ConfigPackError, match="not a recorder segment"):
        segment_xz_arcname("recorder/configs/abc.json")


def test_damaged_xz_segment_fails_loud(tmp_path):
    good = lzma.compress(_LINE_1)
    (tmp_path / "cycles_2026-11-18.jsonl.xz").write_bytes(good[:-8] + bytes(8))
    with pytest.raises(ConfigPackError, match="damaged xz segment"):
        expand_xz_segments(tmp_path)
    assert not (tmp_path / "cycles_2026-11-18.jsonl.gz").exists()


def test_xz_segment_does_not_overwrite_different_gz(tmp_path):
    _gz_segment(tmp_path, "2026-11-18", _LINE_1)
    (tmp_path / "cycles_2026-11-18.jsonl.xz").write_bytes(lzma.compress(b'{"n": 2}\n'))
    with pytest.raises(ConfigPackError, match="different content"):
        expand_xz_segments(tmp_path)


def test_xz_segment_beside_equal_gz_is_dropped(tmp_path):
    _gz_segment(tmp_path, "2026-11-18", _LINE_1)
    (tmp_path / "cycles_2026-11-18.jsonl.xz").write_bytes(lzma.compress(_LINE_1))
    assert expand_xz_segments(tmp_path) == 1
    assert not (tmp_path / "cycles_2026-11-18.jsonl.xz").exists()


def test_replay_names_xz_segments_that_were_not_expanded(tmp_path):
    from runtime_store.recorder_replay import _segment_paths_for_root

    (tmp_path / "cycles_2026-11-18.jsonl.xz").write_bytes(lzma.compress(b"{}\n"))
    with pytest.raises(FileNotFoundError, match="xz-packed"):
        _segment_paths_for_root(tmp_path)


def _history_line(stamp: str, n: int) -> str:
    return json.dumps({"schema_version": 1, "written_at": stamp, "n": n}) + "\n"


def _write_runtime_history(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    (runtime / "optimization_history.jsonl").write_text(
        _history_line("2026-11-01T08:00:00", 1)
        + _history_line("2026-11-12T08:00:00", 2)
        + '{"no_timestamp": true}\n'
        + _history_line("2026-11-18T08:00:00", 3),
        encoding="utf-8",
    )
    # Month file the window reaches into (window starts 2026-11-12 for 7 days).
    (runtime / "optimization_history.jsonl.2026-11-12_00-00-00").write_text(
        _history_line("2026-11-11T23:00:00", 4) + _history_line("2026-11-12T00:00:00", 5),
        encoding="utf-8",
    )
    # Month file entirely before the window.
    (runtime / "optimization_history.jsonl.2026-10-01_00-00-00").write_text(
        _history_line("2026-10-15T08:00:00", 6),
        encoding="utf-8",
    )


def _history_numbers(archive: zipfile.ZipFile, arcname: str) -> list:
    return [json.loads(line).get("n") for line in archive.read(arcname).decode().splitlines()]


def test_history_window_keeps_recorder_days_only(tmp_path, monkeypatch):
    with _dump_config(tmp_path, monkeypatch):
        _write_runtime_history(tmp_path)
        zip_path = write_debug_dump_zip(captured_at=datetime(2026, 11, 18, 9, 0, 0))
    with zipfile.ZipFile(zip_path) as archive:
        names = set(archive.namelist())
        assert _history_numbers(archive, "runtime/optimization_history.jsonl") == [2, None, 3]
        assert _history_numbers(
            archive, "runtime/optimization_history.jsonl.2026-11-12_00-00-00"
        ) == [5]
        assert "runtime/optimization_history.jsonl.2026-10-01_00-00-00" not in names
        manifest = json.loads(archive.read("manifest.json"))
    assert manifest["history"] == {
        "mode": "window",
        "since": "2026-11-12",
        "files": [
            "runtime/optimization_history.jsonl",
            "runtime/optimization_history.jsonl.2026-11-12_00-00-00",
        ],
        "lines_kept": 4,
        "lines_dropped": 3,
        "lines_without_written_at": 1,
        "last_line_outside_window": False,
    }


def test_full_history_copies_files_unchanged(tmp_path, monkeypatch):
    with _dump_config(tmp_path, monkeypatch):
        _write_runtime_history(tmp_path)
        zip_path = write_debug_dump_zip(
            captured_at=datetime(2026, 11, 18, 9, 0, 0), full_history=True
        )
        source = (tmp_path / "runtime" / "optimization_history.jsonl").read_bytes()
    with zipfile.ZipFile(zip_path) as archive:
        assert archive.read("runtime/optimization_history.jsonl") == source
        assert "runtime/optimization_history.jsonl.2026-10-01_00-00-00" in archive.namelist()
        manifest = json.loads(archive.read("manifest.json"))
    assert manifest["history"]["mode"] == "full"


def test_history_window_keeps_last_line_when_window_is_empty(tmp_path, monkeypatch):
    with _dump_config(tmp_path, monkeypatch):
        runtime = tmp_path / "runtime"
        runtime.mkdir(parents=True, exist_ok=True)
        (runtime / "optimization_history.jsonl").write_text(
            _history_line("2026-07-01T08:00:00", 1) + _history_line("2026-07-02T08:00:00", 2),
            encoding="utf-8",
        )
        zip_path = write_debug_dump_zip(captured_at=datetime(2026, 11, 18, 9, 0, 0))
    with zipfile.ZipFile(zip_path) as archive:
        assert _history_numbers(archive, "runtime/optimization_history.jsonl") == [2]
        manifest = json.loads(archive.read("manifest.json"))
    assert manifest["history"]["last_line_outside_window"] is True
    assert manifest["history"]["lines_dropped"] == 1


def test_history_window_start_follows_recorder_retention(monkeypatch):
    from runtime_store import cycle_recorder

    monkeypatch.setattr(cycle_recorder, "retention_days", lambda: 3)
    assert debug_dump_archive.history_window_start(date(2026, 11, 18)) == date(2026, 11, 16)


def _dump_with_packed_recorder(tmp_path: Path) -> tuple[Path, dict[str, bytes]]:
    """Dump folder in the new layout: one cycle + packed snapshot ``abc123``."""
    from tests.test_regression_intake import _minimal_cycle, _write_recorder_segment

    root = tmp_path / "dump_src"
    (root / "runtime").mkdir(parents=True)
    (root / "runtime" / "optimization_history.jsonl").write_text(
        _history_line("2026-07-16T10:00:00", 1), encoding="utf-8"
    )
    recorder = root / "recorder"
    _write_recorder_segment(recorder, _minimal_cycle())
    segment = recorder / "cycles_2026-07-16.jsonl.gz"
    xz_bytes, _ = compress_segment_xz(segment)
    segment.unlink()
    (recorder / "cycles_2026-07-16.jsonl.xz").write_bytes(xz_bytes)
    (recorder / "configs" / "abc123.json").unlink()
    snapshot = _write_snapshot(
        tmp_path / "snap", "abc123", {"inputs/cons_data.csv": _cons_csv(50)}
    )
    data, _ = build_config_pack([snapshot])
    (recorder / "configs").rmdir()
    (recorder / PACK_FILENAME).write_bytes(data)
    (root / "manifest.json").write_text(
        json.dumps({"schema_version": 3, "dump_type": "debug", "app_version": "x", "meta": {}}),
        encoding="utf-8",
    )
    return root, {"abc123.json": snapshot.read_bytes()}


def test_extract_dump_zip_expands_packed_configs(tmp_path):
    root, expected = _dump_with_packed_recorder(tmp_path)
    zip_path = tmp_path / "dump.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        for path in root.rglob("*"):
            if path.is_file():
                archive.write(path, arcname=path.relative_to(root).as_posix())
    assert PACK_ARCNAME in zipfile.ZipFile(zip_path).namelist()
    out = extract_dump_to_dir(zip_path, tmp_path / "out")
    assert (out / "recorder" / "configs" / "abc123.json").read_bytes() == expected["abc123.json"]
    assert not (out / "recorder" / PACK_FILENAME).exists()
    assert (out / "recorder" / "cycles_2026-07-16.jsonl.gz").is_file()
    assert not (out / "recorder" / "cycles_2026-07-16.jsonl.xz").exists()


def test_intake_from_dump_folder_expands_packed_configs(tmp_path):
    root, expected = _dump_with_packed_recorder(tmp_path)
    cases = tmp_path / "cases"
    cases.mkdir()
    case_dir = intake_debug_dump(
        root,
        case_id="REG-1-packed",
        seed_anchor="2026-07-16T10:00:00",
        cycle_index=None,
        private=True,
        private_cases_dir=cases,
    )
    snapshot = case_dir / "recorder" / "configs" / "abc123.json"
    assert snapshot.read_bytes() == expected["abc123.json"]
    assert not (case_dir / "recorder" / PACK_FILENAME).exists()
    assert (case_dir / "recorder" / "cycles_2026-07-16.jsonl.gz").is_file()
    assert not (case_dir / "recorder" / "cycles_2026-07-16.jsonl.xz").exists()
    # The source folder is left as it was.
    assert (root / "recorder" / PACK_FILENAME).is_file()
    assert (root / "recorder" / "cycles_2026-07-16.jsonl.xz").is_file()
