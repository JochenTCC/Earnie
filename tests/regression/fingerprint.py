"""Input fingerprints for regression goldens (raw input files + effective input series).

Layer ``files``: digests of the input files a case reads (fixtures, recorder cycle).
Layer ``series``: digests of the per-slot inputs the optimizer actually saw, after
code-side preparation (PV, base load, prices). A diff in ``series`` means the
inputs changed; identical ``series`` with different metrics points at the code.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable

DIGEST_LEN = 16
SERIES_DECIMALS = 6
SLOT_HOURS = 0.25

# Result-frame columns that are optimizer inputs (not decisions).
L2_INPUT_SERIES = ("pv_kw", "baseload_kw", "k_act", "k_push_act")
_FIXTURE_SKIP = frozenset({"README.md"})


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:DIGEST_LEN]


def canonical_json_digest(payload: Any) -> str:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return digest_bytes(text.encode("utf-8"))


def file_digest(path: Path) -> str:
    """JSON files are canonicalized (key order / whitespace); others hash raw with LF."""
    raw = path.read_bytes()
    if path.suffix.lower() == ".json":
        return canonical_json_digest(json.loads(raw.decode("utf-8")))
    return digest_bytes(raw.replace(b"\r\n", b"\n"))


def _normalize_value(value: Any) -> float | None:
    if value is None:
        return None
    number = float(value)
    if math.isnan(number):
        return None
    return round(number, SERIES_DECIMALS)


def series_digest(values: Iterable[Any]) -> str:
    return canonical_json_digest([_normalize_value(v) for v in values])


def _series_sum(values: Iterable[Any]) -> float:
    return sum(v for v in (_normalize_value(x) for x in values) if v is not None)


def l2_input_fingerprint(
    *,
    fixtures_root: Path,
    case_inputs: dict[str, Any],
    result_df: Any,
) -> dict[str, Any]:
    # Recursive: the frozen Open-Meteo climate (fixtures/open_meteo/) is an input too.
    files = {
        f"fixtures/{path.relative_to(fixtures_root).as_posix()}": file_digest(path)
        for path in sorted(fixtures_root.rglob("*"))
        if path.is_file() and path.name not in _FIXTURE_SKIP
    }
    files["case.inputs"] = canonical_json_digest(case_inputs)
    missing = [col for col in L2_INPUT_SERIES if col not in result_df.columns]
    if missing:
        raise KeyError(f"L2 result frame lacks input columns {missing}")
    series = {col: series_digest(result_df[col]) for col in L2_INPUT_SERIES}
    sums = {
        "n_slots": float(len(result_df)),
        "pv_kwh": round(_series_sum(result_df["pv_kw"]) * SLOT_HOURS, 4),
        "baseload_kwh": round(_series_sum(result_df["baseload_kw"]) * SLOT_HOURS, 4),
        "k_act_mean": round(float(result_df["k_act"].mean()), 4),
    }
    return {"files": files, "series": series, "sums": sums}


def l1_input_fingerprint(*, entry: dict[str, Any], recorder_root: Path) -> dict[str, Any]:
    """L1 replays recorded inputs; the matrix preparation runs inside the replay."""
    files = {"recorder_cycle": canonical_json_digest(entry)}
    config_hash = str(entry.get("config_hash") or "")
    if not config_hash:
        raise ValueError("recorder cycle entry missing config_hash")
    files["config_snapshot"] = file_digest(recorder_root / "configs" / f"{config_hash}.json")
    return {"files": files, "series": {}, "sums": {}}


def diff_inputs(expected: dict[str, Any], actual: dict[str, Any]) -> dict[str, Any]:
    """Keys whose digest differs (added / removed keys count as changed)."""

    def _changed(layer: str) -> list[str]:
        exp = expected.get(layer) or {}
        act = actual.get(layer) or {}
        return sorted(k for k in set(exp) | set(act) if exp.get(k) != act.get(k))

    exp_sums = expected.get("sums") or {}
    act_sums = actual.get("sums") or {}
    sums = {
        key: (exp_sums.get(key), act_sums.get(key))
        for key in sorted(set(exp_sums) | set(act_sums))
        if exp_sums.get(key) != act_sums.get(key)
    }
    return {"files": _changed("files"), "series": _changed("series"), "sums": sums}
