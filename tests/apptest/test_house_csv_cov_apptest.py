"""Hauskonfigurator CSV imports: save paths, Energiemonitor mode, consumer CSV, import QC.

Covers helpers no other test executed (full-suite coverage run 2026-11-22). AppTest has
no file uploader, so the module's ``single_csv_upload`` is replaced by a fake that hands
out one upload (once: the page reruns after a successful upload). Files land in the
isolated config copy of ``tests/apptest/conftest.py`` (``config/uploads/``).
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from runtime_store.persist_paths import resolve_config_prefixed_path

_TIMEOUT_S = 30.0


# --- CSV fixtures -----------------------------------------------------------------------


def _hourly_csv_text(values: list[float], *, start: datetime = datetime(2024, 1, 1), step_min: int = 60) -> str:
    lines = ["timestamp;power_kw"]
    for index, value in enumerate(values):
        ts = start + timedelta(minutes=step_min * index)
        lines.append(f"{ts:%Y-%m-%d %H:%M:%S};{value}")
    return "\n".join(lines) + "\n"


def _write_config_csv(portable: str, values: list[float], **kwargs) -> str:
    target = Path(resolve_config_prefixed_path(portable))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_hourly_csv_text(values, **kwargs), encoding="utf-8")
    return portable


def _read_rows(portable: str) -> list[tuple[str, float]]:
    with Path(resolve_config_prefixed_path(portable)).open(encoding="utf-8") as handle:
        reader = csv.reader(handle, delimiter=";")
        assert next(reader) == ["timestamp", "power_kw"]
        return [(ts, float(kw)) for ts, kw in reader]


def _energiemonitor_bytes(*, hours: int = 24, with_pv: bool = True) -> bytes:
    if with_pv:
        lines = [
            "Datum;Zeit;Leistung Produktion [kW];Leistung Verbrauch [kW];"
            "Leistung Energieversorger [kW];Leistung Batterie;Ladestand Batterie [%%]"
        ]
    else:
        lines = [
            "Datum;Zeit;Leistung Verbrauch [kW];Leistung Energieversorger [kW];"
            "Leistung Batterie;Ladestand Batterie [%%]"
        ]
    start = datetime(2023, 1, 1)
    for index in range(hours):
        ts = start + timedelta(hours=index)
        prefix = f"{ts:%d.%m.%Y};{ts:%H:%M:%S}"
        if with_pv:
            lines.append(f"{prefix};1,200;0,500;-0,300;-0,400;50,000")
        else:
            lines.append(f"{prefix};0,500;-0,300;-0,400;50,000")
    return ("\n".join(lines) + "\n").encode("latin-1")


@dataclass
class _Upload:
    name: str
    data: bytes

    def getvalue(self) -> bytes:
        return self.data


def _one_shot_upload(monkeypatch, module: str, upload: _Upload) -> list[str]:
    """Replace ``single_csv_upload`` in ``module``: the first call returns ``upload``."""
    calls: list[str] = []

    def fake(label, *, key, help=None):  # noqa: A002 - mirrors the real signature
        calls.append(label)
        return upload if len(calls) == 1 else None

    monkeypatch.setattr(f"{module}.single_csv_upload", fake)
    return calls


def _keys_ending(at: AppTest, suffix: str) -> list[str]:
    return [k for k in at.session_state.keys() if str(k).endswith(suffix)]  # noqa: SIM118


# --- ui.house_config_csv_io --------------------------------------------------------------


def test_queue_csv_path_update_sets_pending_bumps_nonce_and_flash(monkeypatch):
    import streamlit as st

    from ui.house_config_csv_io import queue_csv_path_update

    state: dict = {"nonce": 2}
    monkeypatch.setattr(st, "session_state", state)
    queue_csv_path_update(
        "pending", "config/uploads/x.csv", upload_nonce_key="nonce", flash_key="flash", flash_message="ok"
    )
    assert state == {"nonce": 3, "pending": "config/uploads/x.csv", "flash": "ok"}


def test_queue_csv_path_update_without_nonce_or_message_only_queues_path(monkeypatch):
    import streamlit as st

    from ui.house_config_csv_io import queue_csv_path_update

    state: dict = {}
    monkeypatch.setattr(st, "session_state", state)
    queue_csv_path_update("pending", None, flash_key="flash")  # type: ignore[arg-type]
    assert state == {"pending": ""}


def test_save_energiemonitor_profile_csvs_writes_raw_and_components():
    from ui.house_config_csv_io import save_energiemonitor_profile_csvs

    content = _energiemonitor_bytes(hours=24)
    result = save_energiemonitor_profile_csvs("p1", content, "monitor")
    assert result == {
        "total_profile_csv": "config/uploads/p1_energiemonitor_verbrauch.csv",
        "pv_profile_csv": "config/uploads/p1_energiemonitor_produktion.csv",
        "battery_profile_csv": "config/uploads/p1_energiemonitor_battery.csv",
        "grid_profile_csv": "config/uploads/p1_energiemonitor_grid.csv",
    }
    # A name without .csv gets the suffix; the raw upload is kept byte for byte.
    raw = Path(resolve_config_prefixed_path("config/uploads/p1_energiemonitor_raw_monitor.csv"))
    assert raw.read_bytes() == content
    verbrauch = _read_rows(result["total_profile_csv"])
    assert len(verbrauch) == 24
    assert {kw for _, kw in verbrauch} == {0.5}
    assert {kw for _, kw in _read_rows(result["pv_profile_csv"])} == {1.2}
    # Battery and grid keep their sign (bipolar series).
    assert {kw for _, kw in _read_rows(result["battery_profile_csv"])} == {-0.4}
    assert {kw for _, kw in _read_rows(result["grid_profile_csv"])} == {-0.3}


def test_save_energiemonitor_profile_csvs_honours_min_hours():
    from ui.house_config_csv_io import save_energiemonitor_profile_csvs

    with pytest.raises(ValueError, match="mindestens 100"):
        save_energiemonitor_profile_csvs("p1", _energiemonitor_bytes(hours=24), "em.csv", min_hours=100)


def test_save_balance_total_from_component_paths_derives_and_writes_total():
    from ui.house_config_csv_io import save_balance_total_from_component_paths

    pv = _write_config_csv("config/uploads/b_pv.csv", [2.0] * 6)
    batt = _write_config_csv("config/uploads/b_batt.csv", [-0.5] * 6)
    grid = _write_config_csv("config/uploads/b_grid.csv", [0.25, 0.25, 0.25, -3.0, -3.0, -3.0])
    result = save_balance_total_from_component_paths("b", pv_path=pv, battery_path=batt, grid_path=grid)
    assert result["total_profile_csv"] == "config/uploads/b_balance_verbrauch.csv"
    assert result["hours"] == 6
    # P_Ges = PV + Batt + Grid; negative hours are clipped to 0 and counted.
    assert result["clipped_hours"] == 3
    assert [kw for _, kw in _read_rows(result["total_profile_csv"])] == [1.75] * 3 + [0.0] * 3


def test_save_balance_total_from_component_paths_applies_sign_inverts_and_min_hours():
    from ui.house_config_csv_io import save_balance_total_from_component_paths

    pv = _write_config_csv("config/uploads/i_pv.csv", [2.0] * 4)
    grid = _write_config_csv("config/uploads/i_grid.csv", [-0.5] * 4)
    result = save_balance_total_from_component_paths(
        "i", pv_path=pv, battery_path="", grid_path=grid, invert_grid=True
    )
    assert [kw for _, kw in _read_rows(result["total_profile_csv"])] == [2.5] * 4
    with pytest.raises(ValueError, match="mindestens 10"):
        save_balance_total_from_component_paths("i", pv_path=pv, battery_path="", grid_path=grid, min_hours=10)


# --- ui.house_config_historical_modes: save helpers and pure helpers -------------------------


def test_save_signed_component_csv_keeps_negative_battery_values():
    from ui.house_config_historical_modes import _save_signed_component_csv

    content = _hourly_csv_text([-1.5, 2.0, -0.5]).encode()
    saved = _save_signed_component_csv("p1", content, "speicher.csv", role="battery")
    assert saved == "config/uploads/p1_battery_speicher_resampled.csv"
    assert [kw for _, kw in _read_rows(saved)] == [-1.5, 2.0, -0.5]


def test_save_signed_component_csv_grid_uses_grid_loader():
    from ui.house_config_historical_modes import _save_signed_component_csv

    content = _hourly_csv_text([0.4, -2.0]).encode()
    saved = _save_signed_component_csv("p1", content, "", role="grid")
    # Empty filename: the role is the stem.
    assert saved == "config/uploads/p1_grid_grid_resampled.csv"
    assert [kw for _, kw in _read_rows(saved)] == [0.4, -2.0]


@pytest.mark.parametrize(
    ("preserve_sign", "expected_path", "expected_kw"),
    [
        (True, "config/uploads/p1_battery_batt_resampled.csv", [-1.0, -1.0, 2.0]),
        # Consumption path: majority-negative series is flipped (consumption positive).
        (False, "config/uploads/p1_battery_batt_resampled.csv", [1.0, 1.0, -2.0]),
    ],
)
def test_save_component_csv_routes_by_preserve_sign(preserve_sign, expected_path, expected_kw):
    from ui.house_config_historical_modes import _save_component_csv

    upload = _Upload("batt.csv", _hourly_csv_text([-1.0, -1.0, 2.0]).encode())
    saved = _save_component_csv(upload, preview_id="p1", role="battery", preserve_sign=preserve_sign)
    assert saved == expected_path
    assert [kw for _, kw in _read_rows(saved)] == expected_kw


def test_hourly_consumer_sum_adds_series_per_hour():
    from ui.house_config_historical_modes import _hourly_consumer_sum

    assert _hourly_consumer_sum({}) == []
    assert _hourly_consumer_sum({"a": [1, 2, 3], "b": [0.5, 0.5, 0.5]}) == [1.5, 2.5, 3.5]


@dataclass
class _Probe:
    timestamps: list[str]
    actual_total: list[float] | None
    consumer_series: dict[str, list[float]] = field(default_factory=dict)
    baseload: list[float] = field(default_factory=list)


def test_baseload_display_monthly_is_month_residual_per_hour():
    from ui.house_config_historical_modes import _baseload_display_monthly

    timestamps = ["2024-01-31 22:00:00", "2024-01-31 23:00:00", "2024-02-01 00:00:00", "2024-02-01 01:00:00"]
    probe = _Probe(timestamps, [2.0, 2.0, 1.0, 1.0], {"wp": [0.5, 0.5, 3.0, 3.0]})
    display, kwh, caption = _baseload_display_monthly(probe, [])
    # Jan: (4 − 1) / 2 h = 1.5 kW; Feb: consumers above Ist → 0.
    assert display.baseload == [1.5, 1.5, 0.0, 0.0]
    assert kwh == 3.0
    assert caption.startswith("Monats-Rest-Grundlast: 3 kWh")
    assert probe.baseload == []  # the probe itself is not changed


def test_baseload_display_monthly_falls_back_to_series_without_consumers():
    from ui.house_config_historical_modes import _baseload_display_monthly

    timestamps = ["2024-03-01 00:00:00", "2024-03-01 01:00:00"]
    probe = _Probe(timestamps, None, {})
    display, kwh, _caption = _baseload_display_monthly(probe, [(timestamps[0], 1.0), (timestamps[1], 3.0)])
    assert display.baseload == [2.0, 2.0]
    assert kwh == 4.0


def test_balance_reset_extra_encodes_flags_and_paths():
    from ui.house_config_historical_csv import _balance_reset_extra

    state = {"invert_pv": True, "invert_battery": False, "invert_grid": True, "pv": "a.csv", "battery": "", "grid": "g.csv"}
    assert _balance_reset_extra(state) == "101:a.csv::g.csv"


# --- Energiemonitor mode (AppTest) -------------------------------------------------------


def _em_app():
    import streamlit as st

    from ui.house_config_historical_modes import _render_energiemonitor_mode, session_keys

    keys = session_keys("cov")
    _render_energiemonitor_mode("p1", keys)
    st.session_state["cov_em_paths"] = {slot: st.session_state.get(keys[slot]) for slot in ("verbrauch", "pv", "battery", "grid")}


_EM_MODULE = "ui.house_config_historical_modes"


def test_energiemonitor_upload_sets_all_paths_flash_and_captions(monkeypatch):
    _one_shot_upload(monkeypatch, _EM_MODULE, _Upload("em.csv", _energiemonitor_bytes()))
    at = AppTest.from_function(_em_app, default_timeout=_TIMEOUT_S).run()
    assert not at.exception, [e.value for e in at.exception]
    expected = {
        "verbrauch": "config/uploads/p1_energiemonitor_verbrauch.csv",
        "pv": "config/uploads/p1_energiemonitor_produktion.csv",
        "battery": "config/uploads/p1_energiemonitor_battery.csv",
        "grid": "config/uploads/p1_energiemonitor_grid.csv",
    }
    assert at.session_state["cov_em_paths"] == expected
    # The `_input` widget twins follow the store keys.
    assert at.session_state["cov__house_hist_pv_csv_path_input"] == expected["pv"]
    assert at.session_state["house_profile_em_csv_upload_nonce_p1"] == 1
    [flash] = [s.value for s in at.success]
    assert flash == (
        f"Lastprofil: `{expected['verbrauch']}`; PV: `{expected['pv']}`; "
        f"Batterie: `{expected['battery']}`; Netz: `{expected['grid']}`"
    )
    captions = [c.value for c in at.caption]
    for label, slot in (("Lastprofil", "verbrauch"), ("PV-Erzeugungsprofil", "pv"), ("Batterie", "battery"), ("Netz", "grid")):
        assert f"{label}: `{expected[slot]}`" in captions
    assert Path(resolve_config_prefixed_path(expected["verbrauch"])).is_file()

    # The flash is shown once.
    at.run()
    assert not at.success


def test_energiemonitor_upload_without_pv_column_names_the_gap(monkeypatch):
    _one_shot_upload(monkeypatch, _EM_MODULE, _Upload("em.csv", _energiemonitor_bytes(with_pv=False)))
    at = AppTest.from_function(_em_app, default_timeout=_TIMEOUT_S).run()
    assert not at.exception
    [flash] = [s.value for s in at.success]
    assert "(keine Produktionsspalte — PV leer)" in flash
    assert at.session_state["cov_em_paths"]["pv"] == ""
    assert not any(c.value.startswith("PV-Erzeugungsprofil:") for c in at.caption)


def test_energiemonitor_clear_resets_paths_and_uploader(monkeypatch):
    _one_shot_upload(monkeypatch, _EM_MODULE, _Upload("em.csv", _energiemonitor_bytes()))
    at = AppTest.from_function(_em_app, default_timeout=_TIMEOUT_S).run()
    assert at.session_state["cov_em_paths"]["verbrauch"]
    at.button(key="house_profile_em_csv_clear_p1").click().run()
    assert not at.exception
    assert at.session_state["cov_em_paths"] == {"verbrauch": "", "pv": "", "battery": "", "grid": ""}
    assert at.session_state["cov__house_hist_csv_path_input"] == ""
    assert at.session_state["house_profile_em_csv_upload_nonce_p1"] == 2
    assert not any(
        c.value.startswith(("Lastprofil:", "PV-Erzeugungsprofil:", "Batterie:", "Netz:")) for c in at.caption
    )


def test_energiemonitor_invalid_upload_shows_error_and_keeps_paths(monkeypatch):
    _one_shot_upload(monkeypatch, _EM_MODULE, _Upload("em.csv", b"Datum;Zeit;Irgendwas\n01.01.2023;00:00:00;1\n"))
    at = AppTest.from_function(_em_app, default_timeout=_TIMEOUT_S).run()
    assert not at.exception
    assert any(e.value.startswith("Energiemonitor-CSV ungültig:") for e in at.error)
    assert at.session_state["cov_em_paths"] == {"verbrauch": None, "pv": None, "battery": None, "grid": None}
    assert "house_profile_em_csv_upload_nonce_p1" not in at.session_state


# --- Import QC (AppTest) ----------------------------------------------------------------


def _qc_app(verbrauch: str, pv: str, battery: str, grid: str):
    from ui.house_config_import_qc import render_import_power_qc

    render_import_power_qc(preview_id="cov", verbrauch_path=verbrauch, pv_path=pv, battery_path=battery, grid_path=grid)


def test_import_qc_warns_per_missing_csv():
    at = AppTest.from_function(
        _qc_app,
        default_timeout=_TIMEOUT_S,
        kwargs={"verbrauch": "config/uploads/missing_v.csv", "pv": "", "battery": "", "grid": "config/uploads/missing_g.csv"},
    ).run()
    assert not at.exception
    assert [w.value for w in at.warning] == [
        "Lastprofil-CSV nicht gefunden: `config/uploads/missing_v.csv`",
        "Netz-CSV nicht gefunden: `config/uploads/missing_g.csv`",
    ]


def test_import_qc_full_year_shows_se_horizon_with_march():
    hours = 24 * 400
    verbrauch = _write_config_csv("config/uploads/qc_year.csv", [0.5] * hours, start=datetime(2024, 1, 1))
    at = AppTest.from_function(
        _qc_app, default_timeout=_TIMEOUT_S, kwargs={"verbrauch": verbrauch, "pv": "", "battery": "", "grid": ""}
    ).run()
    assert not at.exception
    # Data end 2025-02-04 → last complete month Jan 2025 → window Feb 2024 – Jan 2025.
    [info] = [i.value for i in at.info]
    assert info == (
        "SE-Zeitraum (letzte 12 vollständige Monate bis Datenende): "
        "2024-02-01 – 2025-01-31. Testmonat SE: März (03)."
    )
    assert not at.warning


# --- Consumer CSV upload + digital 0/1 prompt (AppTest) ----------------------------------


def _consumer_csv_app(nominal: float):
    import streamlit as st

    from ui.house_config_profile_csv import _render_consumer_profile_csv_fields

    st.session_state["cov_result"] = _render_consumer_profile_csv_fields(
        {"id": "pump", "label": "Pumpe"}, 0, session_scope="cov", nominal_power_kw=nominal
    )


_CSV_MODULE = "ui.house_config_profile_csv"
_DIGITAL_VALUES = [0, 1] * 24  # hourly on/off log over 2 days


def _consumer_app(nominal: float = 2.0) -> AppTest:
    return AppTest.from_function(_consumer_csv_app, default_timeout=_TIMEOUT_S, kwargs={"nominal": nominal})


def _decision(at: AppTest):
    [key] = [k for k in _keys_ending(at, "") if "digital_csv_decision_0_" in str(k)] or [None]
    return at.session_state[key] if key else None


def test_consumer_csv_analog_upload_is_stored_without_prompt(monkeypatch):
    _one_shot_upload(monkeypatch, _CSV_MODULE, _Upload("pumpe.csv", _hourly_csv_text([0.3, 0.6, 0.9]).encode()))
    at = _consumer_app().run()
    assert not at.exception, [e.value for e in at.exception]
    saved = at.session_state["cov_result"]["profile_csv"]
    assert saved == "config/uploads/profile_pump_pumpe_resampled.csv"
    assert [s.value for s in at.success] == [f"CSV gespeichert: `{saved}`"]
    assert [kw for _, kw in _read_rows(saved)] == [0.3, 0.6, 0.9]
    # Not digital: no question, and the kept raw upload is dropped.
    assert not any("Digitales Ein/Aus-Signal" in i.value for i in at.info)
    assert not Path(resolve_config_prefixed_path(f"{saved}.raw")).exists()


def test_consumer_csv_digital_upload_scaled_with_nominal_power(monkeypatch):
    _one_shot_upload(
        monkeypatch, _CSV_MODULE, _Upload("pumpe.csv", _hourly_csv_text(_DIGITAL_VALUES).encode())
    )
    at = _consumer_app(2.0).run()
    assert not at.exception, [e.value for e in at.exception]
    saved = at.session_state["cov_result"]["profile_csv"]
    assert any(
        "Digitales Ein/Aus-Signal (0/1) erkannt" in i.value and "2,000 kW" in i.value for i in at.info
    ), [i.value for i in at.info]
    assert Path(resolve_config_prefixed_path(f"{saved}.raw")).is_file()

    yes = next(b for b in at.button if b.label == "Ja, mit Nennleistung multiplizieren")
    yes.click().run()
    assert not at.exception
    assert _decision(at) == "yes"
    assert not any("Digitales Ein/Aus-Signal" in i.value for i in at.info)
    assert {kw for _, kw in _read_rows(saved)} == {0.0, 2.0}
    assert not Path(resolve_config_prefixed_path(f"{saved}.raw")).exists()


def test_consumer_csv_digital_upload_left_unscaled(monkeypatch):
    _one_shot_upload(
        monkeypatch, _CSV_MODULE, _Upload("pumpe.csv", _hourly_csv_text(_DIGITAL_VALUES).encode())
    )
    at = _consumer_app(2.0).run()
    saved = at.session_state["cov_result"]["profile_csv"]
    no = next(b for b in at.button if b.label == "Nein, Werte unverändert lassen")
    no.click().run()
    assert not at.exception
    assert _decision(at) == "no"
    assert {kw for _, kw in _read_rows(saved)} == {0.0, 1.0}
    assert not Path(resolve_config_prefixed_path(f"{saved}.raw")).exists()
    # Asked once: no question on the next run.
    at.run()
    assert not any("Digitales Ein/Aus-Signal" in i.value for i in at.info)


def test_consumer_csv_digital_scale_needs_positive_nominal_power(monkeypatch):
    _one_shot_upload(
        monkeypatch, _CSV_MODULE, _Upload("pumpe.csv", _hourly_csv_text(_DIGITAL_VALUES).encode())
    )
    at = _consumer_app(0.0).run()
    saved = at.session_state["cov_result"]["profile_csv"]
    next(b for b in at.button if b.label == "Ja, mit Nennleistung multiplizieren").click().run()
    assert not at.exception
    assert [e.value for e in at.error] == ["Nennleistung muss > 0 kW sein, um zu skalieren."]
    assert _decision(at) is None
    assert {kw for _, kw in _read_rows(saved)} == {0.0, 1.0}


def test_consumer_csv_invalid_upload_shows_error(monkeypatch):
    _one_shot_upload(monkeypatch, _CSV_MODULE, _Upload("kaputt.csv", b"timestamp;power_kw\n2024-01-01 00:00:00;abc\n"))
    at = _consumer_app().run()
    assert not at.exception
    assert any(e.value.startswith("CSV ungültig:") for e in at.error)
    assert at.session_state["cov_result"] == {"profile_csv": "", "use_profile_csv": False}
