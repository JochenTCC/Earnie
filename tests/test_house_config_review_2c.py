"""Hausprofil heat and history fixes from the ui slice 2 review, package 2c."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from tests.test_entity_id_lock import profiles_env  # noqa: F401 — fixture


# --- 2c-3: W/kW from the high end, not the median ---------------------------------------


def _hourly(values: list[float]) -> pd.Series:
    index = pd.date_range("2025-06-01", periods=len(values), freq="h")
    return pd.Series(values, index=index, dtype=float)


def test_pv_in_watt_with_night_zeros_is_divided():
    """Median 0 (night) read the W series as kW: 5000 W became 5000 kW."""
    from house_config.consumption_csv import normalize_hourly_power_kw

    day = [0.0] * 14 + [5000.0] * 10
    rows = normalize_hourly_power_kw(_hourly(day * 2), source="pv.csv")
    assert max(kw for _, kw in rows) == pytest.approx(5.0)


def test_kw_series_stays_kw():
    from house_config.consumption_csv import normalize_hourly_power_kw

    rows = normalize_hourly_power_kw(_hourly([0.4, 3.2, 11.0, 0.0] * 12), source="load.csv")
    assert max(kw for _, kw in rows) == pytest.approx(11.0)


def test_unclear_unit_fails_loud():
    from house_config.consumption_csv import normalize_hourly_power_kw

    with pytest.raises(ValueError, match="Einheit unklar"):
        normalize_hourly_power_kw(_hourly([70.0] * 48), source="odd.csv")


# --- 2c-6: timestamps with an offset are rejected, not cut ------------------------------


@pytest.mark.parametrize("stamp", ["2024-06-01T12:00:00+00:00", "2024-06-01T12:00:00Z"])
def test_timestamp_with_offset_is_rejected(tmp_path: Path, stamp: str):
    from house_config.consumption_csv import load_hourly_profile_csv

    path = tmp_path / "ha.csv"
    path.write_text(f"timestamp;power_kw\n{stamp};1.0\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Zeitzone"):
        load_hourly_profile_csv(str(path))


def test_naive_timestamp_still_loads(tmp_path: Path):
    from house_config.consumption_csv import load_hourly_profile_csv

    path = tmp_path / "local.csv"
    path.write_text("timestamp;power_kw\n2024-06-01 12:00:00;1.0\n", encoding="utf-8")
    assert load_hourly_profile_csv(str(path)) == [("2024-06-01 12:00:00", 1.0)]


# --- 2c-1 / 2c-4 / 2c-5: session state of the historical CSVs --------------------------


@pytest.fixture
def session(monkeypatch) -> dict:
    import streamlit as st

    state: dict = {}
    monkeypatch.setattr(st, "session_state", state)
    return state


_BALANCE_PROFILE = {
    "historical_csv_source": "balance",
    "total_profile_csv": "config/uploads/home_balance_verbrauch.csv",
    "pv_profile_csv": "config/uploads/home_pv.csv",
    "battery_profile_csv": "",
    "grid_profile_csv": "config/uploads/home_grid.csv",
}


def test_sign_flags_come_from_the_profile_and_block_a_rederive(session, monkeypatch):
    """2c-1: the checkboxes started unticked and rewrote the load without them."""
    import ui.house_config_historical_modes as modes
    from ui.house_config_historical_csv import (
        historical_csv_save_fields,
        init_historical_csv_session,
        session_keys,
    )

    existing = {
        **_BALANCE_PROFILE,
        "balance_sign_inverts": {"pv": False, "battery": False, "grid": True},
    }
    init_historical_csv_session("home", existing)
    keys = session_keys("home")
    assert session[keys["invert_grid"]] is True
    assert session[keys["invert_pv"]] is False

    def _no_write(*_a, **_k):
        raise AssertionError("unchanged Bilanz inputs must not re-derive the load")

    monkeypatch.setattr(modes, "save_balance_total_from_component_paths", _no_write)
    modes._maybe_persist_balance_total(
        preview_id="home",
        keys=keys,
        pv_path=existing["pv_profile_csv"],
        battery_path="",
        grid_path=existing["grid_profile_csv"],
        invert_pv=False,
        invert_battery=False,
        invert_grid=True,
    )
    fields = historical_csv_save_fields("home", existing)
    assert fields["balance_sign_inverts"] == {"pv": False, "battery": False, "grid": True}


def test_older_profile_without_flags_keeps_its_load_until_a_change(session, monkeypatch):
    import ui.house_config_historical_modes as modes
    from ui.house_config_historical_csv import (
        historical_csv_save_fields,
        init_historical_csv_session,
        session_keys,
    )

    init_historical_csv_session("home", dict(_BALANCE_PROFILE))
    keys = session_keys("home")
    assert session[keys["balance_flags_unknown"]] is True
    # Unknown flags are not written (False would claim the load was derived without a flip).
    assert "balance_sign_inverts" not in historical_csv_save_fields("home", _BALANCE_PROFILE)

    calls: list[dict] = []

    def _derive(_profile_id, **kwargs):
        calls.append(kwargs)
        return {"total_profile_csv": _BALANCE_PROFILE["total_profile_csv"]}

    monkeypatch.setattr(modes, "save_balance_total_from_component_paths", _derive)
    common = {
        "preview_id": "home",
        "keys": keys,
        "pv_path": _BALANCE_PROFILE["pv_profile_csv"],
        "battery_path": "",
        "grid_path": _BALANCE_PROFILE["grid_profile_csv"],
        "invert_pv": False,
        "invert_battery": False,
    }
    modes._maybe_persist_balance_total(**common, invert_grid=False)
    assert calls == []
    session[keys["invert_grid"]] = True
    modes._maybe_persist_balance_total(**common, invert_grid=True)
    assert len(calls) == 1 and calls[0]["invert_grid"] is True
    assert session[keys["balance_flags_unknown"]] is False
    assert historical_csv_save_fields("home", _BALANCE_PROFILE)["balance_sign_inverts"] == {
        "pv": False,
        "battery": False,
        "grid": True,
    }


def test_flags_are_saved_only_for_the_balance_source(session):
    from ui.house_config_historical_csv import (
        historical_csv_save_fields,
        init_historical_csv_session,
    )

    existing = {**_BALANCE_PROFILE, "historical_csv_source": "separate"}
    init_historical_csv_session("home", existing)
    assert "balance_sign_inverts" not in historical_csv_save_fields("home", existing)


def test_historical_keys_follow_the_profile_reseed(session):
    """2c-4: label-slug keys outlived a deleted profile and ignored outside changes."""
    from ui.house_config_historical_csv import init_historical_csv_session, session_keys
    from ui.house_config_profile_session import _clear_scoped_widget_keys

    init_historical_csv_session("home", dict(_BALANCE_PROFILE))
    keys = session_keys("home")
    assert session[keys["verbrauch"]] == _BALANCE_PROFILE["total_profile_csv"]
    _clear_scoped_widget_keys("home")
    assert not any(key in session for key in keys.values())
    # The refill reads the file as it is now.
    init_historical_csv_session("home", {"total_profile_csv": "config/uploads/new.csv"})
    assert session[keys["verbrauch"]] == "config/uploads/new.csv"
    assert session[keys["source"]] == "separate"


def test_balance_series_is_the_ist_only_in_balance_mode():
    """2c-5: Energiemonitor / Getrennte CSVs show the measured Verbrauch file as Ist."""
    from ui.house_config_historical_csv import _load_balance_series

    state = {"pv": "pv.csv", "battery": "", "grid": "grid.csv"}
    assert _load_balance_series(state, "energiemonitor") is None
    assert _load_balance_series(state, "separate") is None


# --- 2c-1: the profile field ------------------------------------------------------------


def _profile(**extra) -> dict:
    return {
        "id": "home",
        "label": "Home",
        "annual_kwh": 5000.0,
        "latitude": 47.4,
        "longitude": 9.7,
        "netznutzung": {"area_id": "user_no_grid_fee"},
        "consumers": [],
        **extra,
    }


def test_balance_sign_inverts_round_trip(profiles_env):
    from house_config.profiles_store import load_house_profiles_document
    from ui.house_config_io import upsert_house_profile

    signs = {"pv": False, "battery": True, "grid": False}
    upsert_house_profile(_profile(historical_csv_source="balance", balance_sign_inverts=signs))
    stored = load_house_profiles_document(str(profiles_env["profiles"]))["profiles"]["home"]
    assert stored["balance_sign_inverts"] == signs


def test_profile_without_flags_keeps_its_shape(profiles_env):
    from house_config.profiles_store import load_house_profiles_document
    from ui.house_config_io import upsert_house_profile

    upsert_house_profile(_profile())
    stored = load_house_profiles_document(str(profiles_env["profiles"]))["profiles"]["home"]
    assert "balance_sign_inverts" not in stored


@pytest.mark.parametrize(
    "value", [{"grid": "yes"}, {"netz": True}, ["grid"]]
)
def test_invalid_balance_sign_inverts_fail_loud(profiles_env, value):
    from ui.house_config_io import upsert_house_profile

    with pytest.raises(ValueError, match="balance_sign_inverts"):
        upsert_house_profile(_profile(balance_sign_inverts=value))
