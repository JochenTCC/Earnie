# tests/test_storage_roundtrip.py
"""Ebene 0 der UI-Persistenztests: save() -> load() der Speicherschicht.

Konzept: Earnie UI-Persistenztests (Ebene 0). Geprüft werden pro Store
Werte und Typen nach dem Roundtrip, Unicode, Grenzwerte, Idempotenz
(save -> load -> save ist byte-gleich) und Cache-Invalidierung nach save.
Alle Dateien liegen unter ``tmp_path``.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from house_config.components_store import (
    clear_components_doc_cache,
    load_components_document,
    save_components_document,
)
from house_config.profiles_store import (
    clear_house_profiles_doc_cache,
    load_house_profiles_document,
    save_house_profiles_document,
)
from settings.json_io import read_json_dict, write_json_dict
from settings.system_settings import (
    load_local_settings_document,
    write_silent_mode_to_local_settings,
)


@pytest.fixture(autouse=True)
def _fresh_caches():
    clear_components_doc_cache()
    clear_house_profiles_doc_cache()
    yield
    clear_components_doc_cache()
    clear_house_profiles_doc_cache()


def _assert_same_types(expected, actual, where: str = "") -> None:
    """Rekursiv: gleiche Werte UND gleiche Typen (``5`` ist nicht ``5.0``, ``True`` nicht ``1``)."""
    assert type(expected) is type(actual), f"{where}: {expected!r} -> {actual!r}"
    if isinstance(expected, dict):
        assert expected.keys() == actual.keys(), where
        for key in expected:
            _assert_same_types(expected[key], actual[key], f"{where}.{key}")
    elif isinstance(expected, list):
        assert len(expected) == len(actual), where
        for index, (e, a) in enumerate(zip(expected, actual)):
            _assert_same_types(e, a, f"{where}[{index}]")
    else:
        assert expected == actual, where


# --------------------------------------------------------------------------
# Components (components.json)
# --------------------------------------------------------------------------

def _components_doc(
    *,
    label: str = "Haupt-WR",
    capacity: float = 5.0,
    min_soc: float = 10.0,
    max_soc: float = 100.0,
    kwp: float = 9.0,
    tilt: float = 30.0,
    azimuth: float = 0.0,
) -> dict:
    return {
        "inverters": [
            {
                "id": "wr_main",
                "label": label,
                "type": "hybrid",
                "ac_connection": "grid_tied",
                "control": "full",
                "efficiency": 0.97,
            }
        ],
        "batteries": [
            {
                "id": "bat",
                "label": "Speicher",
                "inverter_id": "wr_main",
                "battery_capacity_kwh": capacity,
                "battery_max_charge_power_kw": 3.0,
                "battery_max_discharge_power_kw": 2.5,
                "battery_efficiency": 0.97,
                "battery_min_soc": min_soc,
                "battery_max_soc": max_soc,
                "threshold_power": 0.05,
                "limits_from_live": True,
                "control": "limits_only",
                "regulates_on": "grid",
                "battery_wear": {"enabled": False},
            }
        ],
        "pv_systems": [
            {
                "id": "pv",
                "label": "Dach",
                "kwp": kwp,
                "pv_tilt": tilt,
                "pv_azimuth": azimuth,
                "inverter_id": "wr_main",
            }
        ],
    }


COMPONENT_CASES = [
    pytest.param({}, id="normal"),
    pytest.param({"label": "Wechselrichter Ünïcödé – 日本 🔋"}, id="unicode-label"),
    pytest.param({"label": "A" * 200}, id="langes-label"),
    pytest.param({"capacity": 0.1, "min_soc": 0.0, "max_soc": 100.0}, id="min-grenzwerte"),
    pytest.param({"capacity": 500.0, "min_soc": 99.0, "max_soc": 100.0}, id="max-grenzwerte"),
    pytest.param({"kwp": 0.01, "tilt": 0.0, "azimuth": -180.0}, id="pv-untergrenzen"),
    pytest.param({"kwp": 1000.0, "tilt": 90.0, "azimuth": 180.0}, id="pv-obergrenzen"),
    pytest.param({"kwp": 9.123456789}, id="viele-nachkommastellen"),
]


@pytest.mark.parametrize("overrides", COMPONENT_CASES)
def test_components_roundtrip_values_and_types(tmp_path: Path, overrides: dict) -> None:
    path = tmp_path / "components.json"
    save_components_document(str(path), _components_doc(**overrides))
    first = load_components_document(str(path))

    # Zweiter Roundtrip: was geladen wird, muss unverändert wieder gespeichert werden.
    clear_components_doc_cache()
    path2 = tmp_path / "components2.json"
    save_components_document(str(path2), first)
    second = load_components_document(str(path2))
    _assert_same_types(first, second, "components")

    expected = _components_doc(**overrides)
    assert first["inverters"][0]["label"] == expected["inverters"][0]["label"]
    assert first["batteries"][0]["battery_capacity_kwh"] == expected["batteries"][0]["battery_capacity_kwh"]
    assert first["batteries"][0]["battery_min_soc"] == expected["batteries"][0]["battery_min_soc"]
    assert first["batteries"][0]["battery_max_soc"] == expected["batteries"][0]["battery_max_soc"]
    assert first["pv_systems"][0]["kwp"] == expected["pv_systems"][0]["kwp"]
    assert first["pv_systems"][0]["pv_tilt"] == expected["pv_systems"][0]["pv_tilt"]
    assert first["pv_systems"][0]["pv_azimuth"] == expected["pv_systems"][0]["pv_azimuth"]


@pytest.mark.parametrize("overrides", COMPONENT_CASES)
def test_components_save_is_idempotent_on_disk(tmp_path: Path, overrides: dict) -> None:
    path = tmp_path / "components.json"
    save_components_document(str(path), _components_doc(**overrides))
    first_bytes = path.read_bytes()

    save_components_document(str(path), load_components_document(str(path)))
    assert path.read_bytes() == first_bytes


def test_components_file_is_utf8_without_ascii_escapes(tmp_path: Path) -> None:
    path = tmp_path / "components.json"
    save_components_document(str(path), _components_doc(label="Wärmepumpe-WR"))
    raw = path.read_bytes()
    assert "Wärmepumpe-WR".encode("utf-8") in raw
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert not Path(str(path) + ".tmp").exists()


def test_components_load_after_save_sees_new_value(tmp_path: Path) -> None:
    """Cache-Invalidierung (Vorstufe T8): kein veralteter Wert nach save."""
    path = tmp_path / "components.json"
    save_components_document(str(path), _components_doc(capacity=5.0))
    assert load_components_document(str(path))["batteries"][0]["battery_capacity_kwh"] == 5.0

    save_components_document(str(path), _components_doc(capacity=12.5))
    assert load_components_document(str(path))["batteries"][0]["battery_capacity_kwh"] == 12.5


def test_components_invalid_document_leaves_file_unchanged(tmp_path: Path) -> None:
    """T3-Vorstufe: abgelehnte Eingabe darf die gespeicherte Datei nicht verändern."""
    path = tmp_path / "components.json"
    save_components_document(str(path), _components_doc())
    before = path.read_bytes()

    bad = _components_doc()
    bad["batteries"].append(dict(bad["batteries"][0]))  # doppelte id
    with pytest.raises(ValueError):
        save_components_document(str(path), bad)

    assert path.read_bytes() == before
    assert not Path(str(path) + ".tmp").exists()


# --------------------------------------------------------------------------
# House profiles (house_profiles.json)
# --------------------------------------------------------------------------

def _profile(**overrides) -> dict:
    base = {
        "id": "haus",
        "label": "Haus Müller",
        "annual_kwh": 4200.0,
        "land": "AT",
        "latitude": 48.2,
        "longitude": 16.37,
        "absent_mode": False,
        "historical_csv_source": "separate",
        "baseload_distribution": "equal",
        "consumers": [],
    }
    base.update(overrides)
    return base


PROFILE_CASES = [
    pytest.param({}, id="normal"),
    pytest.param({"label": "Familie Öztürk – Zürich 🏠"}, id="unicode-label"),
    pytest.param({"annual_kwh": 0.0}, id="verbrauch-null"),
    pytest.param({"annual_kwh": 1_000_000.0}, id="verbrauch-gross"),
    pytest.param({"land": "DE", "latitude": 52.52, "longitude": 13.4}, id="land-de"),
    pytest.param({"land": "CH", "latitude": 47.37, "longitude": 8.54}, id="land-ch"),
    pytest.param({"latitude": -89.9, "longitude": -179.9}, id="koordinaten-negativ"),
    pytest.param({"absent_mode": True}, id="absent-mode"),
    pytest.param({"historical_csv_source": "balance"}, id="csv-source-balance"),
    pytest.param({"total_profile_csv": "pfad/mit Leerzeichen/größe.csv"}, id="csv-pfad-unicode"),
]


@pytest.mark.parametrize("overrides", PROFILE_CASES)
def test_profiles_roundtrip_values_and_types(tmp_path: Path, overrides: dict) -> None:
    path = tmp_path / "house_profiles.json"
    doc = {"profiles": [_profile(**overrides)]}
    save_house_profiles_document(str(path), doc)
    first = load_house_profiles_document(str(path))

    profile = first["profiles"]["haus"]
    for key, value in _profile(**overrides).items():
        if key == "consumers":
            continue
        assert profile[key] == value, key
        assert type(profile[key]) is type(value), key

    clear_house_profiles_doc_cache()
    path2 = tmp_path / "house_profiles2.json"
    save_house_profiles_document(str(path2), {"profiles": list(first["profiles"].values())})
    second = load_house_profiles_document(str(path2))
    _assert_same_types(first["profiles"], second["profiles"], "profiles")


@pytest.mark.parametrize("overrides", PROFILE_CASES)
def test_profiles_save_is_idempotent_on_disk(tmp_path: Path, overrides: dict) -> None:
    path = tmp_path / "house_profiles.json"
    save_house_profiles_document(str(path), {"profiles": [_profile(**overrides)]})
    first_bytes = path.read_bytes()

    loaded = load_house_profiles_document(str(path))
    save_house_profiles_document(str(path), {"profiles": list(loaded["profiles"].values())})
    assert path.read_bytes() == first_bytes


def test_profiles_multiple_profiles_keep_order_and_all_values(tmp_path: Path) -> None:
    """T5-Vorstufe: mehrere Änderungen in einem Save landen vollständig auf der Platte."""
    path = tmp_path / "house_profiles.json"
    doc = {
        "profiles": [
            _profile(id="a", label="A", annual_kwh=1000.0),
            _profile(id="b", label="B", annual_kwh=2000.0, land="DE"),
            _profile(id="c", label="C", annual_kwh=3000.0, absent_mode=True),
        ]
    }
    save_house_profiles_document(str(path), doc)
    loaded = load_house_profiles_document(str(path))
    assert list(loaded["profiles"]) == ["a", "b", "c"]
    assert [p["annual_kwh"] for p in loaded["profiles"].values()] == [1000.0, 2000.0, 3000.0]
    assert loaded["profiles"]["b"]["land"] == "DE"
    assert loaded["profiles"]["c"]["absent_mode"] is True


def test_profiles_load_after_save_sees_new_value(tmp_path: Path) -> None:
    path = tmp_path / "house_profiles.json"
    save_house_profiles_document(str(path), {"profiles": [_profile(annual_kwh=1000.0)]})
    assert load_house_profiles_document(str(path))["profiles"]["haus"]["annual_kwh"] == 1000.0

    save_house_profiles_document(str(path), {"profiles": [_profile(annual_kwh=2500.0)]})
    assert load_house_profiles_document(str(path))["profiles"]["haus"]["annual_kwh"] == 2500.0


def test_profiles_invalid_document_leaves_file_unchanged(tmp_path: Path) -> None:
    path = tmp_path / "house_profiles.json"
    save_house_profiles_document(str(path), {"profiles": [_profile()]})
    before = path.read_bytes()

    with pytest.raises(ValueError):
        save_house_profiles_document(
            str(path), {"profiles": [_profile(), _profile()]}  # doppelte id
        )
    with pytest.raises(ValueError):
        save_house_profiles_document(str(path), {"profiles": [_profile(id="  ")]})

    assert path.read_bytes() == before
    assert not Path(str(path) + ".tmp").exists()


# --------------------------------------------------------------------------
# Generische JSON-Hilfen (json_io) – Grundlage u.a. für tariffs.json
# --------------------------------------------------------------------------

JSON_VALUES = [
    pytest.param({"a": 5}, id="int"),
    pytest.param({"a": 5.0}, id="float-ganzzahlig"),
    pytest.param({"a": 0.1 + 0.2}, id="float-binaer"),
    pytest.param({"a": True, "b": False}, id="bool"),
    pytest.param({"a": None}, id="null"),
    pytest.param({"a": []}, id="leere-liste"),
    pytest.param({"a": ""}, id="leerer-string"),
    pytest.param({"a": "Wärmepumpe – 日本 🔋 \"quote\" \\ \n"}, id="sonderzeichen"),
    pytest.param({"a": [1, 2.5, "x", {"k": [True]}]}, id="verschachtelt"),
    pytest.param({"a": 1e-9, "b": 1e15}, id="exponent"),
]


@pytest.mark.parametrize("data", JSON_VALUES)
def test_json_io_roundtrip_keeps_values_and_types(tmp_path: Path, data: dict) -> None:
    path = tmp_path / "doc.json"
    write_json_dict(str(path), dict(data))
    loaded = read_json_dict(str(path))
    loaded.pop("earnie_data_model", None)
    _assert_same_types(data, loaded, "json")


def test_json_io_write_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "doc.json"
    write_json_dict(str(path), {"a": 5, "b": 5.0, "c": "ä"})
    first = path.read_bytes()
    write_json_dict(str(path), read_json_dict(str(path)))
    assert path.read_bytes() == first


def test_json_io_reads_cp1252_and_bom_but_writes_utf8(tmp_path: Path) -> None:
    """K4-Vorstufe: Altdateien werden gelesen, geschrieben wird UTF-8 ohne BOM."""
    path = tmp_path / "doc.json"
    path.write_bytes(json.dumps({"a": "Wärme"}, ensure_ascii=False).encode("cp1252"))
    assert read_json_dict(str(path))["a"] == "Wärme"

    path.write_bytes(b"\xef\xbb\xbf" + json.dumps({"a": "Wärme"}, ensure_ascii=False).encode("utf-8"))
    loaded = read_json_dict(str(path))
    assert loaded["a"] == "Wärme"

    write_json_dict(str(path), loaded)
    raw = path.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert "Wärme".encode("utf-8") in raw


# --------------------------------------------------------------------------
# local_settings.json (Silent-Schalter)
# --------------------------------------------------------------------------

@pytest.mark.parametrize("silent", [True, False])
def test_local_settings_silent_roundtrip(tmp_path: Path, silent: bool) -> None:
    path = tmp_path / "local_settings.json"
    write_silent_mode_to_local_settings(str(path), silent)
    loaded = load_local_settings_document(str(path))
    assert loaded["silent_mode"] is silent


def test_local_settings_silent_toggle_overwrites_and_preserves_other_keys(tmp_path: Path) -> None:
    path = tmp_path / "local_settings.json"
    path.write_text(
        json.dumps({"other": {"x": 1, "name": "Ä"}, "loxone_silent_mode": True}),
        encoding="utf-8",
    )
    write_silent_mode_to_local_settings(str(path), False)
    loaded = load_local_settings_document(str(path))
    assert loaded == {"other": {"x": 1, "name": "Ä"}, "silent_mode": False}

    write_silent_mode_to_local_settings(str(path), True)
    assert load_local_settings_document(str(path))["silent_mode"] is True


def test_local_settings_missing_file_is_empty_and_created_on_write(tmp_path: Path) -> None:
    path = tmp_path / "sub" / "local_settings.json"
    assert load_local_settings_document(str(path)) == {}
    write_silent_mode_to_local_settings(str(path), True)
    assert path.is_file()


@pytest.mark.parametrize("bad", ["true", 1, 0, None])
def test_local_settings_rejects_non_bool_and_keeps_file(tmp_path: Path, bad) -> None:
    path = tmp_path / "local_settings.json"
    write_silent_mode_to_local_settings(str(path), True)
    before = path.read_bytes()
    with pytest.raises(ValueError):
        write_silent_mode_to_local_settings(str(path), bad)
    assert path.read_bytes() == before


# --------------------------------------------------------------------------
# Property-based (hypothesis): json_io und Zahlenfelder in Components
# --------------------------------------------------------------------------

_PBT = settings(
    max_examples=60,
    deadline=None,  # Dateizugriffe, Laufzeit schwankt
    suppress_health_check=[HealthCheck.too_slow],
)

# Lone Surrogates lassen sich nicht als UTF-8 schreiben - kein Speicherformat-Fall.
_text = st.text(alphabet=st.characters(blacklist_categories=("Cs",)), max_size=40)
_json_scalar = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-(2**53), max_value=2**53),
    st.floats(allow_nan=False, allow_infinity=False),
    _text,
)
_json_value = st.recursive(
    _json_scalar,
    lambda children: st.one_of(
        st.lists(children, max_size=4),
        st.dictionaries(_text, children, max_size=4),
    ),
    max_leaves=12,
)
_json_doc = st.dictionaries(
    _text.filter(lambda key: key != "earnie_data_model"), _json_value, max_size=5
)


@_PBT
@given(doc=_json_doc)
def test_json_io_roundtrip_property(doc: dict) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "doc.json"
        write_json_dict(str(path), json.loads(json.dumps(doc)))
        first = path.read_bytes()
        loaded = read_json_dict(str(path))
        loaded.pop("earnie_data_model", None)
        _assert_same_types(doc, loaded, "json")

        write_json_dict(str(path), read_json_dict(str(path)))
        assert path.read_bytes() == first


@_PBT
@given(
    capacity=st.floats(min_value=0.1, max_value=1000.0),
    min_soc=st.floats(min_value=0.0, max_value=50.0),
    max_soc=st.floats(min_value=51.0, max_value=100.0),
    kwp=st.floats(min_value=0.01, max_value=1000.0),
    tilt=st.floats(min_value=0.0, max_value=90.0),
    azimuth=st.floats(min_value=-180.0, max_value=180.0),
    label=_text.filter(lambda text: text.strip() != ""),
)
def test_components_numeric_fields_roundtrip_property(
    capacity, min_soc, max_soc, kwp, tilt, azimuth, label
) -> None:
    doc = _components_doc(
        label=label,
        capacity=capacity,
        min_soc=min_soc,
        max_soc=max_soc,
        kwp=kwp,
        tilt=tilt,
        azimuth=azimuth,
    )
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "components.json"
        clear_components_doc_cache()
        save_components_document(str(path), doc)
        first_bytes = path.read_bytes()
        loaded = load_components_document(str(path))

        bat = loaded["batteries"][0]
        assert bat["battery_capacity_kwh"] == capacity
        assert bat["battery_min_soc"] == min_soc
        assert bat["battery_max_soc"] == max_soc
        assert loaded["pv_systems"][0]["kwp"] == kwp
        assert loaded["pv_systems"][0]["pv_tilt"] == tilt
        assert loaded["pv_systems"][0]["pv_azimuth"] == azimuth
        assert loaded["inverters"][0]["label"] == label.strip()

        save_components_document(str(path), loaded)
        assert path.read_bytes() == first_bytes
