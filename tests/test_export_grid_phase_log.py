"""Shadow feed -> grid_phase_log export (scripts.export_grid_phase_log)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import export_grid_phase_log as exporter

VOLTAGE = "grid.meter.sens_grid_voltage_l1"
POWER = "grid.meter.sens_grid_power_active"


def _feed_row(ts: str, ehal_id: str, raw: str, *, ok: bool = True) -> str:
    return json.dumps(
        {
            "key": f"loxone:io:{ehal_id}",
            "ts": ts,
            "ok": ok,
            "status": None,
            "payload": {"LL": {"value": raw}},
            "error": None if ok else "parse_failed",
        }
    )


def _write_feed(feed_dir: Path, day: str, lines: list[str]) -> Path:
    feed_dir.mkdir(parents=True, exist_ok=True)
    path = feed_dir / f"feed-{day}.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _read_log(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_export_keeps_grid_meter_rows_and_drops_cycle_snapshot(tmp_path: Path) -> None:
    feed = tmp_path / "shadow_feed"
    _write_feed(
        feed,
        "2026-10-29",
        [
            _feed_row("2026-10-29T10:59:57Z", VOLTAGE, "233.0"),
            json.dumps({"key": "ext:outdoor:abc", "ts": "2026-10-29T11:00:00Z", "ok": True, "payload": {}}),
            _feed_row("2026-10-29T11:00:02Z", VOLTAGE, "233.0"),
            _feed_row("2026-10-29T11:00:02Z", "consumer.trockner.sens_power_act", "0.000"),
            _feed_row("2026-10-29T11:00:03Z", VOLTAGE, "233.0"),  # cycle snapshot
            _feed_row("2026-10-29T11:00:07Z", VOLTAGE, "233.0"),  # repeat push, kept
            _feed_row("2026-10-29T11:00:12Z", VOLTAGE, "233.4"),
            _feed_row("2026-10-29T11:00:12Z", POWER, "-0.237"),
        ],
    )
    out = tmp_path / "grid_phase_log"

    assert exporter.main(["--feed-dir", str(feed), "--out-dir", str(out)]) == 0

    rows = _read_log(out / "2026-10-29.jsonl")
    assert [(r["ts"], r["id"], r["v"]) for r in rows] == [
        ("2026-10-29T10:59:57+00:00", VOLTAGE, 233.0),
        ("2026-10-29T11:00:02+00:00", VOLTAGE, 233.0),
        ("2026-10-29T11:00:07+00:00", VOLTAGE, 233.0),
        ("2026-10-29T11:00:12+00:00", VOLTAGE, 233.4),
        ("2026-10-29T11:00:12+00:00", POWER, -0.237),
    ]
    assert all("raw" not in r for r in rows)


def test_keep_snapshots_keeps_every_row(tmp_path: Path) -> None:
    feed = tmp_path / "shadow_feed"
    _write_feed(
        feed,
        "2026-10-29",
        [
            _feed_row("2026-10-29T11:00:02Z", VOLTAGE, "233.0"),
            _feed_row("2026-10-29T11:00:03Z", VOLTAGE, "233.0"),
            _feed_row("2026-10-29T11:00:07Z", VOLTAGE, "233.0"),
            _feed_row("2026-10-29T11:00:12Z", VOLTAGE, "233.0"),
        ],
    )
    out = tmp_path / "log"

    assert exporter.main(["--feed-dir", str(feed), "--out-dir", str(out), "--keep-snapshots"]) == 0

    assert len(_read_log(out / "2026-10-29.jsonl")) == 4


def test_snapshot_with_changed_value_is_kept(tmp_path: Path) -> None:
    pushes = [
        exporter.FeedPush(exporter._parse_ts(f"2026-10-29T11:00:{s:02d}Z"), VOLTAGE, raw)
        for s, raw in ((2, "233.0"), (3, "233.1"), (7, "233.1"), (12, "233.1"))
    ]

    kept, dropped = exporter.drop_cycle_snapshots(pushes)

    assert dropped == 0
    assert kept == pushes


def test_unparsable_push_keeps_raw_text(tmp_path: Path) -> None:
    feed = tmp_path / "shadow_feed"
    _write_feed(feed, "2026-10-29", [_feed_row("2026-10-29T11:00:02Z", VOLTAGE, "<v.4>", ok=False)])
    out = tmp_path / "log"

    assert exporter.main(["--feed-dir", str(feed), "--out-dir", str(out)]) == 0

    assert _read_log(out / "2026-10-29.jsonl") == [
        {"ts": "2026-10-29T11:00:02+00:00", "id": VOLTAGE, "v": None, "raw": "<v.4>"}
    ]


def test_existing_day_file_needs_overwrite(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    feed = tmp_path / "shadow_feed"
    _write_feed(feed, "2026-10-29", [_feed_row("2026-10-29T11:00:02Z", VOLTAGE, "233.0")])
    out = tmp_path / "log"
    out.mkdir()
    (out / "2026-10-29.jsonl").write_text("old\n", encoding="utf-8")

    assert exporter.main(["--feed-dir", str(feed), "--out-dir", str(out)]) == 1
    assert "--overwrite" in capsys.readouterr().err
    assert (out / "2026-10-29.jsonl").read_text(encoding="utf-8") == "old\n"

    assert exporter.main(["--feed-dir", str(feed), "--out-dir", str(out), "--overwrite"]) == 0
    assert len(_read_log(out / "2026-10-29.jsonl")) == 1


def test_day_range_selects_feed_files(tmp_path: Path) -> None:
    feed = tmp_path / "shadow_feed"
    for day in ("2026-10-27", "2026-10-28", "2026-10-29"):
        _write_feed(feed, day, [_feed_row(f"{day}T11:00:02Z", VOLTAGE, "233.0")])

    selected = exporter.feed_files(
        feed,
        day_from=exporter.date.fromisoformat("2026-10-28"),
        day_to=exporter.date.fromisoformat("2026-10-28"),
    )

    assert [p.name for p in selected] == ["feed-2026-10-28.jsonl"]


def test_missing_feed_dir_fails(tmp_path: Path) -> None:
    assert exporter.main(["--feed-dir", str(tmp_path / "nope"), "--out-dir", str(tmp_path / "log")]) == 2
