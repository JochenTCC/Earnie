"""Coverage: EHAL-Com debug helpers (unit pairs, row styling, Loxone/HA/OpenEMS mapping).

Pure functions only; backend selection is monkeypatched, no adapter talks to a hub.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from integrations import ehal_debug_mapping, ehal_live
from ui import loxone_debug
from ui.ehal_live_read_style import style_live_read_rows
from ui.ehal_unit_display import live_read_pair, live_write_pair, units_for_field
from ui.ehal_unit_display import format_value_with_unit


def _w(value: float) -> str:
    return format_value_with_unit(float(value), "W")


# --- ehal_unit_display: OpenEMS pairs ---------------------------------------------------


def test_openems_units_come_from_the_registry() -> None:
    units = units_for_field("set_ess_charge_power_limit", "openems")
    assert (units.hub_unit, units.ehal_unit) == ("W", "W")


def test_openems_read_pair_hub_value_applies_sign_to_ehal() -> None:
    # set_ess_charge_power_limit: sign -1, clamp_min 0 -> hub -1500 W is EHAL 1500 W.
    hub, ehal = live_read_pair(
        "set_ess_charge_power_limit", "openems", "-1500", value_space="hub"
    )
    assert (hub, ehal) == (_w(-1500), _w(1500))


def test_openems_read_pair_ehal_value_is_converted_back_to_hub() -> None:
    hub, ehal = live_read_pair(
        "set_ess_charge_power_limit", "openems", "1500", value_space="ehal"
    )
    assert (hub, ehal) == (_w(-1500), _w(1500))


def test_openems_read_pair_unknown_field_goes_to_the_matching_side() -> None:
    # No OpenEMS spec and no unit: the parsed float is shown on the side it came from.
    text = format_value_with_unit(42.0, None)
    hub, ehal = live_read_pair("sens_ess_soc", "openems", "42", value_space="hub")
    assert (hub, ehal) == (text, "—")
    hub, ehal = live_read_pair("sens_ess_soc", "openems", "42", value_space="ehal")
    assert (hub, ehal) == ("—", text)


def test_openems_write_pair_returns_ehal_then_hub() -> None:
    ehal, hub = live_write_pair(
        "set_ess_charge_power_limit", "openems", "2000", value_space="ehal"
    )
    assert (ehal, hub) == (_w(2000), _w(-2000))
    ehal, hub = live_write_pair(
        "set_ess_charge_power_limit", "openems", "-2000", value_space="hub"
    )
    assert (ehal, hub) == (_w(2000), _w(-2000))


def test_openems_write_pair_unknown_field_goes_to_the_matching_side() -> None:
    text = format_value_with_unit(1.0, None)
    assert live_write_pair("set_ess_mode", "openems", "1", value_space="ehal") == (text, "—")
    assert live_write_pair("set_ess_mode", "openems", "1", value_space="hub") == ("—", text)


def test_openems_discharge_limit_has_identity_scale() -> None:
    hub, ehal = live_read_pair(
        "set_ess_discharge_power_limit", "openems", "3000", value_space="hub"
    )
    assert hub == ehal


# --- ehal_live_read_style: _row_style -----------------------------------------------------


def test_style_live_read_rows_colours_rows_by_status() -> None:
    rows = [
        {"EHAL-Feld": "sens_ess_soc", "Status": "OK", "Detail": ""},
        {"EHAL-Feld": "sens_ess_power", "Status": "Fehler", "Detail": "timeout"},
    ]
    styler = style_live_read_rows(rows)
    styler._compute()  # runs the row function (lazy until rendered)
    ctx = styler.ctx
    from ui.ehal_live_read_style import live_read_text_color

    for index, row in enumerate(rows):
        colour = live_read_text_color(row["Status"], optional=False)
        cells = [ctx.get((index, col), []) for col in range(3)]
        if colour:
            assert all(("color", colour) in cell for cell in cells), (index, cells)
        else:
            assert all(cell == [] for cell in cells), (index, cells)
    # At least one of the two states is coloured, otherwise the test proves nothing.
    assert any(ctx.get((i, 0)) for i in range(2))


def test_style_live_read_rows_empty() -> None:
    assert style_live_read_rows([]).data.empty


# --- loxone_debug helpers ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("age", "expected"),
    [(None, "?"), (0, "0 s"), (119.9, "119 s"), (120, "2 min"), (3599, "59 min")],
)
def test_format_age_text(age, expected) -> None:
    assert loxone_debug._format_age_text(age) == expected


def test_local_receipt_time_converts_utc_to_naive_local() -> None:
    stamp = datetime(2026, 7, 5, 8, 30, 15, tzinfo=timezone.utc)
    expected = stamp.astimezone().replace(tzinfo=None).isoformat(timespec="seconds")
    assert loxone_debug._local_receipt_time(stamp.isoformat()) == expected


def test_local_receipt_time_keeps_naive_and_rejects_garbage() -> None:
    assert loxone_debug._local_receipt_time("2026-07-05T08:30:15.987") == "2026-07-05T08:30:15"
    assert loxone_debug._local_receipt_time("not a time") == ""
    assert loxone_debug._local_receipt_time(None) == ""


def _backend(monkeypatch, *, ha: bool, openems: bool) -> None:
    monkeypatch.setattr(ehal_live, "is_ha_backend", lambda: ha)
    monkeypatch.setattr(ehal_live, "is_openems_backend", lambda: openems)


def test_network_write_mapping_per_backend(monkeypatch) -> None:
    _backend(monkeypatch, ha=False, openems=False)
    assert loxone_debug._network_write_mapping() == {}

    _backend(monkeypatch, ha=True, openems=False)
    monkeypatch.setattr(
        ehal_debug_mapping, "ha_entity_scoped_live_mapping", lambda: {"set_x": "number.x"}
    )
    assert loxone_debug._network_write_mapping() == {"set_x": "number.x"}

    _backend(monkeypatch, ha=False, openems=True)
    adapter = SimpleNamespace(cfg=SimpleNamespace(evcs_channels=(("wb1", "evcs0", "SetChargePower"),)))
    monkeypatch.setattr(ehal_live, "get_openems_adapter", lambda: adapter)
    monkeypatch.setattr(
        loxone_debug.config, "get", lambda key, *a, **k: "ess7" if key == "EHAL_OPENEMS_ESS_COMPONENT" else None
    )
    mapping = loxone_debug._network_write_mapping()
    assert mapping["set_ess_active_power"] == "ess7/SetActivePowerEquals"
    assert "evcs0/SetChargePower" in mapping.values()


def test_telemetry_mapping_for_ha_adds_derived_consumers(monkeypatch) -> None:
    _backend(monkeypatch, ha=True, openems=False)
    monkeypatch.setattr(
        ehal_debug_mapping, "ha_entity_scoped_live_mapping", lambda: {"sens_ess_soc": "sensor.soc"}
    )
    mapping = loxone_debug._telemetry_mapping_for_adapter(object())
    assert mapping == {"sens_ess_soc": "sensor.soc", "sens_power_consumers": "—(abgeleitet)"}

    monkeypatch.setattr(
        ehal_debug_mapping,
        "ha_entity_scoped_live_mapping",
        lambda: {"sens_power_consumers": "sensor.cons"},
    )
    assert loxone_debug._telemetry_mapping_for_adapter(object()) == {
        "sens_power_consumers": "sensor.cons"
    }


def test_telemetry_mapping_for_openems_uses_adapter_cfg(monkeypatch) -> None:
    _backend(monkeypatch, ha=False, openems=True)
    adapter = SimpleNamespace(
        cfg=SimpleNamespace(ess_component="ess3", evcs_channels=(("wb", "evcs1", "X"),))
    )
    mapping = loxone_debug._telemetry_mapping_for_adapter(adapter)
    assert mapping["sens_ess_power"] == "ess3/ActivePower"
    assert mapping["sens_evcs_active_power"] == "evcs1/ActivePower"
    # Adapter without cfg -> defaults.
    plain = loxone_debug._telemetry_mapping_for_adapter(object())
    assert plain["sens_ess_power"] == "ess0/ActivePower"
    assert "sens_evcs_active_power" not in plain


def test_receipt_time_used_for_push_rows_is_local(monkeypatch) -> None:
    """Sanity: an hour-aligned UTC receipt keeps its minutes after conversion."""
    stamp = datetime(2026, 1, 1, 12, 45, tzinfo=timezone.utc) + timedelta(seconds=7)
    assert loxone_debug._local_receipt_time(stamp.isoformat()).endswith(":45:07")
