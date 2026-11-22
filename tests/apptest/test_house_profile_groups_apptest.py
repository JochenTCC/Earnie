"""Hausprofil tab: collapsible groups and field order (docs/dev/house-profile-layout.md, stage 1)."""
from __future__ import annotations

from tests.apptest.test_consumer_gain_field_last_apptest import _inputs
from tests.apptest.test_persist_consumers_apptest import (  # noqa: F401 — fixture
    _new_session,
    _profile_with_all_consumer_types,
)

_TIMEOUT_S = 30.0
_KEY = "test_home__"

# Render order; the horizon and the heating feed the consumer forms (stage 1).
_GROUPS = [
    ("house_profile_group_consumption", "**Verbrauch & Haushalt** · Pflicht", True),
    ("house_profile_group_location", "**Standort** · Pflicht", True),
    ("house_profile_group_grid", "**Netzanschluss & Netzentgelt** · Pflicht", True),
    ("house_profile_group_sun", "**Sonne & Horizont**", False),
    ("house_profile_group_heating", "**Heizung**", False),
    ("house_profile_group_cooling", "**Kühlung**", False),
    ("house_profile_group_consumers", "**Verbraucher**", True),
    ("house_profile_group_absence", "**Abwesenheit**", False),
    ("house_profile_group_history", "**Historische Messdaten (CSV)**", False),
]


def _groups(at) -> list:
    keys = {key for key, _title, _open in _GROUPS}
    return [e for e in at.expander if e.key in keys]


def _consumer_expander(at, consumer_type: str):
    return next(
        e
        for e in at.expander
        if "_consumer_expander_" in str(e.key or "") and str(e.key).endswith(f"_{consumer_type}")
    )


def test_groups_in_order_with_marker_and_default_state() -> None:
    at = _new_session()
    assert not at.exception
    groups = _groups(at)
    assert [g.key for g in groups] == [key for key, _title, _open in _GROUPS]
    for group, (_key, title, expanded) in zip(groups, _GROUPS):
        assert group.label.startswith(title), group.label
        assert group.proto.expanded is expanded, group.label


def test_plant_settings_sit_in_the_grid_group() -> None:
    at = _new_session()
    grid = next(g for g in _groups(at) if g.key == "house_profile_group_grid")
    keys = {w.key for w in grid.checkbox}
    assert "house_config_plant_max_export_enabled" in keys
    assert "house_config_plant_grid_meter_at_house" in keys


def test_heating_status_follows_switch_with_stable_group_key() -> None:
    at = _new_session()
    heating = next(g for g in _groups(at) if g.key == "house_profile_group_heating")
    assert heating.label == "**Heizung** — an"
    at.checkbox(key=_KEY + "house_heating_enabled").uncheck().run(timeout=_TIMEOUT_S)
    assert not at.exception
    heating = next(g for g in _groups(at) if g.key == "house_profile_group_heating")
    assert heating.label == "**Heizung** — aus"


def test_generic_consumer_role_before_runs_and_operation_last() -> None:
    at = _new_session()
    labels = [w.label for w in _inputs(_consumer_expander(at, "generic"))]
    assert labels.index("Earnie-Berücksichtigung") < labels.index("Läufe pro Woche")
    assert labels[-2:] == ["Inaktiv wenn abwesend", "Interner Gewinn (Wärme)"]


def test_ev_tuning_fields_in_advanced_expander() -> None:
    at = _new_session()
    ev = _consumer_expander(at, "ev")
    advanced = next(e for e in ev.expander if e.label == "Erweitert")
    assert not advanced.proto.expanded
    labels = [w.label for w in _inputs(advanced)]
    assert labels[0] == "Mindest-Ladedauer (Viertelstunden)"
    assert "Kontinuierlich laden ab Restmenge (kWh)" in labels
