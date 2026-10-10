"""Unit display helpers for EHAL-Com (hub/EHAL units + conversion pairs)."""
from __future__ import annotations

from ui.ehal_unit_display import (
    format_value_with_unit,
    live_read_pair,
    live_write_pair,
    units_for_field,
)


def test_units_for_field_loxone_ess_power() -> None:
    units = units_for_field("ess.house.sens_ess_power", "loxone")
    assert units.hub_unit == "kW"
    assert units.ehal_unit == "W"


def test_units_for_field_loxone_soc_identity() -> None:
    units = units_for_field("sens_ess_soc", "loxone")
    assert units.hub_unit == "%"
    assert units.ehal_unit == "%"


def test_units_for_field_missing_spec() -> None:
    units = units_for_field("sens_ess_energy_charge", "loxone")
    assert units.hub_unit is None
    assert units.ehal_unit is None


def test_format_value_with_unit() -> None:
    assert format_value_with_unit(2.5, "kW") == "2.5 kW"
    assert format_value_with_unit("", "kW") == "—"
    assert format_value_with_unit(65, None) == "65"


def test_live_read_pair_loxone_hub_to_ehal() -> None:
    hub, ehal = live_read_pair(
        "get_ess_max_charge_power",
        "loxone",
        "5",
        value_space="hub",
    )
    assert hub == "5 kW"
    assert ehal == "5000 W"


def test_live_write_pair_loxone_hub_trace_normalized() -> None:
    ehal, hub = live_write_pair(
        "set_ess_charge_power_limit",
        "loxone",
        "3.5",
        value_space="hub",
    )
    assert ehal == "3500 W"
    assert hub == "3.5 kW"


def test_live_read_pair_ha_ehal_without_entity_unit() -> None:
    hub, ehal = live_read_pair(
        "sens_ess_power",
        "ha",
        "1200",
        value_space="ehal",
    )
    assert hub == "—"
    assert ehal == "1200 W"


def test_live_read_pair_ha_with_entity_unit() -> None:
    hub, ehal = live_read_pair(
        "sens_ess_power",
        "ha",
        "1200",
        value_space="ehal",
        hub_unit_hint="kW",
    )
    assert hub == "1.2 kW"
    assert ehal == "1200 W"


def test_live_read_text_color_and_optional() -> None:
    from ui.ehal_live_read_style import (
        is_optional_live_read,
        live_read_text_color,
        style_live_read_rows,
    )

    assert is_optional_live_read("get_ess_max_charge_power")
    assert not is_optional_live_read("sens_ess_soc")
    assert live_read_text_color("Kein Mapping", optional=False) == "#b91c1c"
    assert live_read_text_color("Zuletzt bekannt (gehalten)", optional=False) == "#1d4ed8"
    assert live_read_text_color("OK", optional=True) == "#6b7280"
    styled = style_live_read_rows(
        [
            {
                "EHAL-Feld": "get_ess_soc_min",
                "Wert": "",
                "Wert (EHAL)": "",
                "Status": "OK",
                "Detail": "",
                "Zuletzt gelesen": "t0",
            }
        ]
    )
    assert "optional" in str(styled.data.iloc[0]["Detail"]).lower()
