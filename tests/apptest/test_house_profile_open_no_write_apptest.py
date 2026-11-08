"""Opening the Hauskonfigurator must not rewrite house_profiles.json (O3).

The first open of a file that is not yet in the normalised form writes it once and
says so; every later open leaves the file byte-identical and shows no „Gespeichert“.
"""
from __future__ import annotations

import json
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

    stamp = path.stat().st_mtime_ns
    second = _open()
    assert not second.exception
    assert path.read_bytes() == normalised
    assert _captions(second) == []
    assert path.stat().st_mtime_ns == stamp  # no rewrite happened


def test_reference_system_with_heating_rod_is_not_rewritten_on_every_open():
    """A rod part carries ``internal_gain_factor`` 0 on disk (migration dw5.house_gains).

    The form builds the part without the key; the save normalises it back in. The dry
    run must compare the normalised catalog, otherwise every open rewrites both files.
    """
    components_path = Path(os.environ["EARNIE_COMPONENTS_PATH"])
    doc = json.loads(components_path.read_text(encoding="utf-8"))
    system = next(s for s in doc["heating_systems"] if s["id"] == "heating_test_home")
    system["heat_storage"] = {
        "volume_liters": 500.0,
        "heat_loss_kw_per_k": 0.02,
        "setpoint_c": 45.0,
        "tolerance_c": 5.0,
    }
    system["parts"] = [
        {
            "id": "heating_rod",
            "type": "heating_rod",
            "nominal_power_kw": 3.0,
            "internal_gain_factor": 0.0,
        }
    ]
    components_path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    house_path = Path(os.environ["EARNIE_HOUSE_PROFILES_PATH"])
    house = json.loads(house_path.read_text(encoding="utf-8"))
    # The rod adds consumer energy; keep a Grundlast so the profile can be saved at all.
    house["profiles"][0]["annual_kwh"] = 10000.0
    house_path.write_text(json.dumps(house, indent=2), encoding="utf-8")

    first = _open()
    assert not first.exception
    assert _captions(first) == ["Gespeichert – Datei auf das aktuelle Format gebracht"]
    house_stamp = house_path.stat().st_mtime_ns
    components_stamp = components_path.stat().st_mtime_ns
    components_after_first = components_path.read_bytes()

    second = _open()
    assert not second.exception
    assert _captions(second) == []
    assert house_path.stat().st_mtime_ns == house_stamp
    assert components_path.stat().st_mtime_ns == components_stamp
    assert components_path.read_bytes() == components_after_first


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
