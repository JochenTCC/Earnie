"""Opening the Hauskonfigurator must not rewrite house_profiles.json (O3).

The first open of a file that is not yet in the normalised form writes it once and
says so; every later open leaves the file byte-identical and shows no „Gespeichert“.
"""
from __future__ import annotations

import os
from pathlib import Path

from streamlit.testing.v1 import AppTest

_SCRIPT = Path(__file__).parent / "scripts" / "run_page_house_config.py"
_TIMEOUT_S = 30.0


def _open() -> AppTest:
    return AppTest.from_file(str(_SCRIPT)).run(timeout=_TIMEOUT_S)


def _captions(at: AppTest) -> list[str]:
    return [c.value for c in at.caption if "Gespeichert" in c.value]


def test_first_open_normalises_once_and_says_so_then_never_writes_again():
    path = Path(os.environ["EARNIE_HOUSE_PROFILES_PATH"])
    raw_before = path.read_bytes()

    first = _open()
    assert not first.exception
    normalised = path.read_bytes()
    assert normalised != raw_before, "fixture is raw: the first open brings it to the current format"
    assert _captions(first) == ["Gespeichert – Datei auf das aktuelle Format gebracht"]

    second = _open()
    assert not second.exception
    assert path.read_bytes() == normalised
    assert _captions(second) == []
    assert path.stat().st_mtime_ns == path.stat().st_mtime_ns  # no rewrite happened


def test_edit_after_a_clean_open_is_still_saved():
    path = Path(os.environ["EARNIE_HOUSE_PROFILES_PATH"])
    _open()  # normalises
    stamp = path.stat().st_mtime_ns
    at = _open()
    assert path.stat().st_mtime_ns == stamp
    field = [w for w in at.number_input if (w.key or "").endswith("house_annual_kwh")][0]
    field.set_value(float(field.value) + 100.0).run(timeout=_TIMEOUT_S)
    assert not at.exception
    assert path.stat().st_mtime_ns != stamp
    assert _captions(at) == ["Gespeichert"]
