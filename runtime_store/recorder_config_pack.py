"""Compact form of the cycle recorder inside a debug dump.

Config snapshots: each ``recorder/configs/<hash>.json`` carries every input file in
full, including ``inputs/cons_data.csv`` (~2 MB) that changes on every snapshot only
at its end. A dump of 150 snapshots therefore held ~300 MB of nearly identical text.
The dump stores one ``recorder/configs.pack.json`` instead: a shared table of unique
lines and, per snapshot, its JSON skeleton plus runs of line indices per file.
``expand_packed_configs`` rebuilds byte-identical snapshot files (checked by
SHA-256), so replays, case fingerprints and goldens see the same files as before.

Cycle segments: ``cycles_<date>.jsonl.gz`` repeat large blocks from cycle to cycle,
which gzip's 32 KB window does not see. The dump stores them as
``cycles_<date>.jsonl.xz`` (same JSONL text, about a sixth of the gzip size);
``expand_xz_segments`` writes the ``.jsonl.gz`` files back. Their JSONL text is
identical; the gzip bytes are not (gzip header and level), and nothing hashes them.

``expand_recorder_dump`` does both; it is what extraction and intake call.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import lzma
import re
from pathlib import Path
from typing import Any, Iterable

PACK_FILENAME = "configs.pack.json"
PACK_ARCNAME = f"recorder/{PACK_FILENAME}"
PACK_FORMAT = 1

SEGMENT_GZ_SUFFIX = ".jsonl.gz"
SEGMENT_XZ_SUFFIX = ".jsonl.xz"
# Preset 3: 0.93 MB for 49 MB of cycles in 0.4 s; preset 6 gives 0.80 MB in 2.2 s
# (measured 2026-11-19 on the maintainer dump). The dump is built on small NAS CPUs.
SEGMENT_XZ_PRESET = 3

# Snapshot names are config hashes (hex); letters, digits, ``_`` and ``-`` cover test names too.
_SNAPSHOT_NAME_RE = re.compile(r"[A-Za-z0-9_-]+")


class ConfigPackError(ValueError):
    """Pack cannot be built or expanded without losing bytes."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _serialize_snapshot(doc: dict[str, Any]) -> bytes:
    # Same call as cycle_recorder._ensure_config_snapshot (json.dump, ensure_ascii=False).
    return json.dumps(doc, ensure_ascii=False).encode("utf-8")


class _LineTable:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self._index: dict[str, int] = {}

    def runs_for(self, text: str) -> list[list[int]]:
        runs: list[list[int]] = []
        for line in text.splitlines(keepends=True):
            idx = self._index.get(line)
            if idx is None:
                idx = len(self.lines)
                self.lines.append(line)
                self._index[line] = idx
            if runs and runs[-1][0] + runs[-1][1] == idx:
                runs[-1][1] += 1
            else:
                runs.append([idx, 1])
        return runs


def _text_from_runs(lines: list[str], runs: list[list[int]]) -> str:
    parts: list[str] = []
    for start, count in runs:
        if start < 0 or count < 0 or start + count > len(lines):
            raise ConfigPackError(f"line run out of range: {start}+{count} of {len(lines)}")
        parts.extend(lines[start : start + count])
    return "".join(parts)


def build_config_pack(snapshot_paths: Iterable[Path | str]) -> tuple[bytes, dict[str, Any]]:
    """Pack snapshot files; returns (pack JSON bytes, summary for the manifest).

    A snapshot whose rebuild would not match its original bytes is stored
    verbatim (``raw``) and counted in the summary, never altered.
    """
    table = _LineTable()
    snapshots: dict[str, Any] = {}
    raw_count = 0
    original_bytes = 0
    for path_like in sorted(Path(p) for p in snapshot_paths):
        original = path_like.read_bytes()
        original_bytes += len(original)
        name = path_like.stem
        entry: dict[str, Any] = {"sha256": _sha256(original)}
        try:
            doc = json.loads(original.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            doc = None
        files = doc.get("files") if isinstance(doc, dict) else None
        if isinstance(files, dict) and all(isinstance(v, str) for v in files.values()):
            skeleton = dict(doc)
            skeleton["files"] = {key: None for key in files}
            entry["skeleton"] = skeleton
            entry["runs"] = {key: table.runs_for(text) for key, text in files.items()}
            if _serialize_snapshot(_rebuild_doc(entry, table.lines)) != original:
                del entry["skeleton"], entry["runs"]
        if "skeleton" not in entry:
            entry["raw"] = original.decode("utf-8", errors="strict")
            raw_count += 1
        snapshots[name] = entry
    pack = {"format": PACK_FORMAT, "lines": table.lines, "snapshots": snapshots}
    data = json.dumps(pack, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    summary = {
        "arcname": PACK_ARCNAME,
        "format": PACK_FORMAT,
        "snapshot_count": len(snapshots),
        "raw_snapshot_count": raw_count,
        "unique_lines": len(table.lines),
        "original_bytes": original_bytes,
        "packed_bytes": len(data),
    }
    return data, summary


def _rebuild_doc(entry: dict[str, Any], lines: list[str]) -> dict[str, Any]:
    doc = dict(entry["skeleton"])
    doc["files"] = {
        key: _text_from_runs(lines, entry["runs"][key]) for key in entry["skeleton"]["files"]
    }
    return doc


def _rebuild_snapshot_bytes(name: str, entry: dict[str, Any], lines: list[str]) -> bytes:
    if "raw" in entry:
        data = str(entry["raw"]).encode("utf-8")
    elif "skeleton" in entry and "runs" in entry:
        data = _serialize_snapshot(_rebuild_doc(entry, lines))
    else:
        raise ConfigPackError(f"snapshot {name!r} has neither raw nor skeleton/runs")
    if _sha256(data) != entry.get("sha256"):
        raise ConfigPackError(f"snapshot {name!r}: rebuilt bytes do not match sha256")
    return data


def expand_packed_configs(recorder_root: Path | str) -> int:
    """Rebuild ``configs/<hash>.json`` from ``configs.pack.json`` and remove the pack.

    Returns the number of snapshots written; 0 when there is no pack. Raises
    ``ConfigPackError`` on an unknown format, a checksum mismatch, or an existing
    snapshot file with different content (nothing is overwritten).
    """
    root = Path(recorder_root)
    pack_path = root / PACK_FILENAME
    if not pack_path.is_file():
        return 0
    pack = json.loads(pack_path.read_text(encoding="utf-8"))
    if not isinstance(pack, dict) or pack.get("format") != PACK_FORMAT:
        raise ConfigPackError(
            f"unsupported config pack format {pack.get('format') if isinstance(pack, dict) else None!r} "
            f"in {pack_path} (expected {PACK_FORMAT})"
        )
    lines = pack.get("lines")
    snapshots = pack.get("snapshots")
    if not isinstance(lines, list) or not isinstance(snapshots, dict):
        raise ConfigPackError(f"invalid config pack shape: {pack_path}")
    for name in snapshots:
        # The name becomes ``configs/<name>.json``; a dump is foreign input.
        if not _SNAPSHOT_NAME_RE.fullmatch(str(name)):
            raise ConfigPackError(f"snapshot name {name!r} in {pack_path} is not a plain file stem")
    rebuilt = {name: _rebuild_snapshot_bytes(name, entry, lines) for name, entry in snapshots.items()}
    configs = root / "configs"
    configs.mkdir(parents=True, exist_ok=True)
    for name, data in rebuilt.items():
        target = configs / f"{name}.json"
        if target.is_file():
            if target.read_bytes() != data:
                raise ConfigPackError(f"{target} exists with different content")
            continue
        tmp = target.with_suffix(".json.tmp")
        tmp.write_bytes(data)
        tmp.replace(target)
    pack_path.unlink()
    return len(rebuilt)


def segment_xz_arcname(arcname: str) -> str:
    """``recorder/cycles_<date>.jsonl.gz`` → ``recorder/cycles_<date>.jsonl.xz``."""
    if not arcname.endswith(SEGMENT_GZ_SUFFIX):
        raise ConfigPackError(f"not a recorder segment: {arcname!r}")
    return arcname[: -len(SEGMENT_GZ_SUFFIX)] + SEGMENT_XZ_SUFFIX


def compress_segment_xz(gz_path: Path | str) -> tuple[bytes, int]:
    """Re-compress one gzip segment with xz; returns (xz bytes, JSONL text length)."""
    with gzip.open(Path(gz_path), "rb") as handle:
        text = handle.read()
    return lzma.compress(text, preset=SEGMENT_XZ_PRESET), len(text)


def expand_xz_segments(recorder_root: Path | str) -> int:
    """Rewrite ``cycles_*.jsonl.xz`` as ``cycles_*.jsonl.gz`` and remove the ``.xz`` files.

    Returns the number of segments written; 0 when there are none. Raises
    ``ConfigPackError`` on a damaged xz file (xz checks its own CRC) or an existing
    ``.jsonl.gz`` with different JSONL text (nothing is overwritten).
    """
    root = Path(recorder_root)
    if not root.is_dir():
        return 0
    sources = sorted(root.glob(f"cycles_*{SEGMENT_XZ_SUFFIX}"))
    for source in sources:
        try:
            text = lzma.decompress(source.read_bytes())
        except lzma.LZMAError as exc:
            raise ConfigPackError(f"{source}: damaged xz segment ({exc})") from exc
        target = source.with_name(source.name[: -len(SEGMENT_XZ_SUFFIX)] + SEGMENT_GZ_SUFFIX)
        if target.is_file():
            with gzip.open(target, "rb") as handle:
                if handle.read() != text:
                    raise ConfigPackError(f"{target} exists with different content")
        else:
            tmp = target.with_name(target.name + ".tmp")
            tmp.write_bytes(gzip.compress(text, mtime=0))
            tmp.replace(target)
        source.unlink()
    return len(sources)


def expand_recorder_dump(recorder_root: Path | str) -> dict[str, int]:
    """Expand the packed config snapshots and the xz cycle segments of a dump's ``recorder/``."""
    return {
        "configs": expand_packed_configs(recorder_root),
        "segments": expand_xz_segments(recorder_root),
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Expand an extracted debug dump's recorder/: configs.pack.json into "
            "configs/<hash>.json and cycles_*.jsonl.xz into cycles_*.jsonl.gz."
        )
    )
    parser.add_argument("recorder_dir", help="the dump's recorder/ folder")
    args = parser.parse_args(argv)
    counts = expand_recorder_dump(args.recorder_dir)
    print(
        f"expanded {counts['configs']} config snapshot(s), "
        f"{counts['segments']} cycle segment(s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
