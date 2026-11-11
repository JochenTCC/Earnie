"""„Interner Gewinn (Wärme)“ is the last input of every consumer form (except „Haus Wärme“)."""
from __future__ import annotations

from tests.apptest.test_persist_consumers_apptest import (  # noqa: F401 — fixture
    _new_session,
    _profile_with_all_consumer_types,
)

_LABEL = "Interner Gewinn (Wärme)"


def _inputs(node) -> list:
    """Input widgets below ``node`` in render order (buttons and containers skipped)."""
    out = []
    children = getattr(node, "children", None)
    for child in (children.values() if isinstance(children, dict) else []):
        if getattr(child, "key", None) and type(child).__name__ not in ("Button", "Expander"):
            out.append(child)
        out.extend(_inputs(child))
    return out


def test_gain_field_is_last_input_of_each_consumer() -> None:
    at = _new_session()
    assert not at.exception
    expanders = [e for e in at.expander if "_consumer_expander_" in str(e.key or "")]
    checked = 0
    for expander in expanders:
        labels = [w.label for w in _inputs(expander)]
        if str(expander.key).endswith("_thermal_annual"):
            assert _LABEL not in labels
            continue
        assert labels[-1] == _LABEL, (expander.label, labels[-3:])
        checked += 1
    assert checked == 3  # Allgemein, E-Auto, Temperatur (RC)
