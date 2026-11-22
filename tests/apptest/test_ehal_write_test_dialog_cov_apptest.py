"""AppTest: EHAL-Com Schreibtest confirmation dialog (restore / force / execute).

Every function that would reach a hub is patched inside the script: ``writes_allowed``,
``restore_safe_setpoints``, ``write_probes``, ``roundtrip_batch`` and
``published_fetched_at``. Calls are recorded in ``session_state["cov_calls"]`` so the tests
assert what *would* have been written. Nothing talks to Loxone / HA / OpenEMS.
"""
from __future__ import annotations

from streamlit.testing.v1 import AppTest

from tests.apptest.helpers import assert_clean

_TIMEOUT = 30
_FORCE_FIELD = "ess.house.set_ess_active_power"
_LIMIT_FIELD = "ess.house.set_ess_charge_power_limit"


def _script() -> None:
    from unittest.mock import patch

    import streamlit as st

    from integrations import ehal_write
    from ui import ehal_write_test as ui

    calls = st.session_state.setdefault("cov_calls", [])
    fields = ["ess.house.set_ess_charge_power_limit", "ess.house.set_ess_active_power"]

    def _restore():
        calls.append(("restore",))
        failure = st.session_state.get("cov_restore_raises")
        if failure:
            raise RuntimeError(failure)

    def _write_probes(values, **kwargs):
        calls.append(("write_probes", dict(values), kwargs["force_ess_active"]))
        return None, dict(values)

    def _roundtrip(values, **kwargs):
        from integrations.ehal_write_test import RoundtripStatus

        calls.append(("roundtrip", dict(values), kwargs["wait_s"], kwargs["restore"]))

        class _Result:
            status = RoundtripStatus.PASS
            written = dict(values)
            echoes = {"set_ess_charge_power_limit": 1000.0}
            message = "Roundtrip OK"

        return _Result()

    with patch.object(
        ui, "writes_allowed", return_value=bool(st.session_state.get("cov_writes_allowed", True))
    ), patch.object(ui, "allowed_probe_fields", return_value=fields), patch.object(
        ui, "mapped_write_targets", return_value={f: f for f in fields}
    ), patch.object(ui, "default_ev_nominal_a", return_value=None), patch.object(
        ui.config, "get_battery_params", return_value={"max_power_kw": 5.0}
    ), patch.object(ui, "restore_safe_setpoints", side_effect=_restore), patch.object(
        ui, "write_probes", side_effect=_write_probes
    ), patch.object(ui, "roundtrip_batch", side_effect=_roundtrip), patch.object(
        ehal_write, "published_fetched_at", return_value=None
    ):
        ui.render_write_test_section()


def _app(pending: dict | None = None, **state) -> AppTest:
    at = AppTest.from_function(_script, default_timeout=_TIMEOUT)
    if pending is not None:
        at.session_state["ehal_write_test_pending"] = pending
    for key, value in state.items():
        at.session_state[key] = value
    at.run()
    assert_clean(at)
    return at


def _pending(action: str, values: dict, *, force: bool = False) -> dict:
    return {
        "action": action,
        "values": values,
        "force": force,
        "wait_s": 1.5,
        "force_confirmed": False,
    }


def _texts(at: AppTest) -> str:
    parts = [m.value for m in at.markdown] + [c.value for c in at.caption]
    parts += [e.value for e in at.error] + [s.value for s in at.success]
    return "\n".join(str(p) for p in parts)


def _calls(at: AppTest) -> list:
    return list(at.session_state["cov_calls"])


# --- restore ----------------------------------------------------------------------------


def test_restore_dialog_asks_before_writing() -> None:
    at = _app(_pending("restore", {}))
    assert "Sichere Sollwerte schreiben" in _texts(at)
    assert {"ewt_restore_yes", "ewt_restore_no"} <= {b.key for b in at.button}
    assert _calls(at) == []  # nothing written before the confirmation


def test_restore_yes_sends_safe_setpoints_once() -> None:
    at = _app(_pending("restore", {}))
    at.button(key="ewt_restore_yes").click().run()
    assert_clean(at)
    assert _calls(at) == [("restore",)]
    assert "ehal_write_test_pending" not in at.session_state
    assert [s.value for s in at.success] == [
        "Sichere Sollwerte gesendet (ESS Automatik, EVCS 0 A)."
    ]


def test_restore_in_silent_mode_is_blocked() -> None:
    at = _app(_pending("restore", {}), cov_writes_allowed=False)
    at.button(key="ewt_restore_yes").click().run()
    assert_clean(at)
    assert _calls(at) == []
    assert "Silent-Modus aktiv — Wiederherstellen blockiert." in [e.value for e in at.error]


def test_restore_hub_error_is_shown() -> None:
    at = _app(_pending("restore", {}), cov_restore_raises="hub down")
    at.button(key="ewt_restore_yes").click().run()
    assert_clean(at)
    assert _calls(at) == [("restore",)]
    assert "hub down" in [e.value for e in at.error]


def test_restore_cancel_drops_the_pending_action() -> None:
    at = _app(_pending("restore", {}))
    at.button(key="ewt_restore_no").click().run()
    assert_clean(at)
    assert _calls(at) == []
    assert "ehal_write_test_pending" not in at.session_state
    assert "ewt_restore_yes" not in {b.key for b in at.button}


# --- force (second confirmation) --------------------------------------------------------


def test_force_field_needs_a_second_confirmation() -> None:
    at = _app(_pending("manual", {_FORCE_FIELD: 100.0, _LIMIT_FIELD: 1000.0}, force=True))
    errors = [e.value for e in at.error]
    assert any(
        "Zweite Bestätigung" in e and f"`{_FORCE_FIELD}=100.0`" in e and _LIMIT_FIELD not in e
        for e in errors
    ), errors
    assert "ewt_run_yes" not in {b.key for b in at.button}
    assert _calls(at) == []


def test_force_cancel_drops_the_pending_action() -> None:
    at = _app(_pending("manual", {_FORCE_FIELD: 100.0}, force=True))
    at.button(key="ewt_force_no").click().run()
    assert_clean(at)
    assert "ehal_write_test_pending" not in at.session_state
    assert _calls(at) == []


def test_force_yes_then_execute_writes_the_values() -> None:
    at = _app(_pending("manual", {_FORCE_FIELD: 100.0}, force=True))
    at.button(key="ewt_force_yes").click().run()
    assert_clean(at)
    assert at.session_state["ehal_write_test_pending"]["force_confirmed"] is True
    text = _texts(at)
    assert "**Alle schreiben:**" in text
    assert "Force ESS-Leistung ist in der Auswahl enthalten." in text
    assert _calls(at) == []  # still only confirmed, not written

    at.button(key="ewt_run_yes").click().run()
    assert_clean(at)
    assert _calls(at) == [("write_probes", {_FORCE_FIELD: 100.0}, True)]
    assert "ehal_write_test_pending" not in at.session_state
    assert any(s.value.startswith("Schreiben OK (published)") for s in at.success)


# --- execute (no force) -----------------------------------------------------------------


def test_execute_confirm_lists_values_without_force_hint() -> None:
    at = _app(_pending("roundtrip", {_LIMIT_FIELD: 1000.0}))
    text = _texts(at)
    assert f"**Auto-Roundtrip:** `{_LIMIT_FIELD}=1000.0`" in text
    assert "Force ESS-Leistung" not in text


def test_execute_roundtrip_yes_runs_the_batch_with_restore() -> None:
    at = _app(_pending("roundtrip", {_LIMIT_FIELD: 1000.0}))
    at.button(key="ewt_run_yes").click().run()
    assert_clean(at)
    assert _calls(at) == [("roundtrip", {_LIMIT_FIELD: 1000.0}, 1.5, True)]
    assert [s.value for s in at.success] == ["Roundtrip OK"]
    assert any(c.value.startswith("Echo: set_ess_charge_power_limit=1000.0") for c in at.caption)


def test_execute_cancel_writes_nothing() -> None:
    at = _app(_pending("manual", {_LIMIT_FIELD: 1000.0}))
    at.button(key="ewt_run_no").click().run()
    assert_clean(at)
    assert _calls(at) == []
    assert "ehal_write_test_pending" not in at.session_state


def test_execute_confirm_with_empty_values_shows_dash() -> None:
    at = _app(_pending("manual", {}))
    assert "**Alle schreiben:** —" in _texts(at)


def test_force_fields_picks_only_active_power_probes() -> None:
    from ui.ehal_write_test import _force_fields

    assert _force_fields({_FORCE_FIELD: 1, _LIMIT_FIELD: 2, "set_ess_active_power": 3}) == [
        _FORCE_FIELD,
        "set_ess_active_power",
    ]
    assert _force_fields({}) == []
