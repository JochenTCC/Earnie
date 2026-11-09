"""Step dm6.wallboxes — the wallbox becomes plant hardware (multi-EV M1, D1–D3, D11).

Until data model 5 an EV consumer carried both the car and its charger: the kW limits
(``nominal_power_kw``, ``min_power_kw``), voltage and phases for the A → kW conversion in
``charging_schedule`` (or its ``loxone`` block) and the charger bindings (``EVCS_KINDS``).

- ``components.json``: one wallbox per EV Kennung in ``wallboxes[]`` (Kennung = the EV's, so the
  ``evcs.<Kennung>.*`` IDs stay the same) with voltage, phases, the current range and the
  charger bindings, moved off the EV.
- every EV consumer: the kW limits become currents with the old voltage and phases (230 V /
  1 phase when none was set, as the old conversion did) and are written to **both** the wallbox
  and the EV, so the pair keeps exactly its old limits (D2); ``phases`` and
  ``wallbox_assignment: fixed`` written.
- every Earnie-track file: ``earnie_data_model`` 6.
- The same EV Kennung in several house profiles (profiles made by copying) gets one wallbox
  when its charger data are equal; different charger data stop the step with a blocker (Q1).
"""
from __future__ import annotations

import copy
from typing import Any, Iterator

from house_config.wallboxes import (
    ASSIGNMENT_FIXED,
    EV_MAX_CURRENT_KEY,
    EV_MIN_CURRENT_KEY,
    EV_PHASES_KEY,
    LEGACY_EV_POWER_KEYS,
    LEGACY_SCHEDULE_CONVERSION_KEYS,
    WALLBOX_ASSIGNMENT_KEY,
    WALLBOXES_KEY,
    is_charger_binding_key,
)
from house_config.required_signal_activation import activate_wallbox_required
from runtime_store.data_model import CURRENT_DATA_MODEL, read_data_model, stamp_data_model
from runtime_store.migration.io_util import EARNIE_TRACK_FILES
from runtime_store.migration.types import (
    Answers,
    Blocker,
    Docs,
    MigrationStep,
    StepResult,
)

STEP_ID = "dm6.wallboxes"
HOUSE_FILE = "house_profiles.json"
COMPONENTS_FILE = "components.json"

# The pre-dm6 conversion defaults (settings.ev_power before data model 6).
OLD_DEFAULT_VOLTAGE_V = 230.0
OLD_DEFAULT_PHASES = 1


def _iter_profiles(house: Any) -> Iterator[dict[str, Any]]:
    profiles = house.get("profiles") if isinstance(house, dict) else None
    items = list(profiles.values()) if isinstance(profiles, dict) else profiles or []
    for profile in items:
        if isinstance(profile, dict):
            yield profile


def _iter_evs(house: Any) -> Iterator[tuple[dict[str, Any], dict[str, Any]]]:
    for profile in _iter_profiles(house):
        for key in ("consumers", "inactive_consumers"):
            for consumer in profile.get(key) or []:
                if isinstance(consumer, dict) and str(consumer.get("type") or "") == "ev":
                    yield profile, consumer


def _ev_pending(consumer: dict[str, Any]) -> bool:
    if WALLBOX_ASSIGNMENT_KEY not in consumer:
        return True
    return any(k in consumer for k in LEGACY_EV_POWER_KEYS)


def _needs_stamp(docs: Docs) -> bool:
    return any(
        read_data_model(docs.get(name)) not in (None, CURRENT_DATA_MODEL)
        for name in EARNIE_TRACK_FILES
    )


def detect(docs: Docs) -> bool:
    if _needs_stamp(docs):
        return True
    return any(_ev_pending(c) for _, c in _iter_evs(docs.get(HOUSE_FILE)))


def _old_conversion(consumer: dict[str, Any]) -> tuple[float, int]:
    """Voltage / phases exactly as ``ev_nominal_power_conversion`` read them before dm6."""
    sched = consumer.get("charging_schedule") or {}
    lox = sched.get("loxone") or {}
    voltage = sched.get("nominal_power_voltage_v")
    if voltage is None:
        voltage = lox.get("nominal_power_voltage_v")
    phases = sched.get("nominal_power_phases")
    if phases is None:
        phases = lox.get("nominal_power_phases")
    voltage_v = float(voltage if voltage is not None else OLD_DEFAULT_VOLTAGE_V)
    phase_count = max(1, int(phases if phases is not None else OLD_DEFAULT_PHASES))
    return voltage_v, phase_count


def _current(kw: Any, *, voltage_v: float, phases: int) -> float:
    return float(kw or 0.0) * 1000.0 / (voltage_v * phases)


def _wallbox_from_ev(consumer: dict[str, Any]) -> dict[str, Any]:
    voltage_v, phases = _old_conversion(consumer)
    bindings = consumer.get("ehal_bindings") or {}
    label = str(consumer.get("label") or consumer["id"]).strip() or consumer["id"]
    return {
        "id": str(consumer["id"]).strip(),
        "label": f"Wallbox {label}",
        "voltage_v": voltage_v,
        "phases": phases,
        EV_MIN_CURRENT_KEY: _current(
            consumer.get("min_power_kw"), voltage_v=voltage_v, phases=phases
        ),
        EV_MAX_CURRENT_KEY: _current(
            consumer.get("nominal_power_kw"), voltage_v=voltage_v, phases=phases
        ),
        "ehal_bindings": {
            str(k): v for k, v in bindings.items() if is_charger_binding_key(str(k))
        },
    }


def _charger_data(wallbox: dict[str, Any]) -> dict[str, Any]:
    """Everything that must match for one shared wallbox (the label may differ)."""
    return {k: v for k, v in wallbox.items() if k != "label"}


def _rewrite_ev(consumer: dict[str, Any], wallbox: dict[str, Any]) -> None:
    for key in LEGACY_EV_POWER_KEYS:
        consumer.pop(key, None)
    consumer[EV_PHASES_KEY] = wallbox["phases"]
    consumer[EV_MIN_CURRENT_KEY] = wallbox[EV_MIN_CURRENT_KEY]
    consumer[EV_MAX_CURRENT_KEY] = wallbox[EV_MAX_CURRENT_KEY]
    consumer[WALLBOX_ASSIGNMENT_KEY] = {"mode": ASSIGNMENT_FIXED, "wallbox_id": wallbox["id"]}
    sched = consumer.get("charging_schedule")
    if isinstance(sched, dict):
        for key in LEGACY_SCHEDULE_CONVERSION_KEYS:
            sched.pop(key, None)
        lox = sched.get("loxone")
        if isinstance(lox, dict):
            for key in LEGACY_SCHEDULE_CONVERSION_KEYS:
                lox.pop(key, None)
            if not lox:
                sched.pop("loxone")
    bindings = consumer.get("ehal_bindings")
    if isinstance(bindings, dict):
        kept = {k: v for k, v in bindings.items() if not is_charger_binding_key(str(k))}
        if kept:
            consumer["ehal_bindings"] = kept
        else:
            consumer.pop("ehal_bindings")


def _blocked(docs: Docs, message: str) -> StepResult:
    return StepResult(
        docs=docs,
        changed_files=(),
        blockers=(Blocker(step_id=STEP_ID, message_de=message),),
    )


def apply(docs: Docs, answers: Answers) -> StepResult:
    del answers
    out = {k: copy.deepcopy(v) for k, v in docs.items()}
    components = out.get(COMPONENTS_FILE)
    if not isinstance(components, dict):
        return _blocked(
            docs,
            "components.json fehlt: die Wallboxen der E-Autos werden dort angelegt.",
        )
    existing = components.get(WALLBOXES_KEY) or []
    if not isinstance(existing, list):
        return _blocked(docs, "components.json: wallboxes muss ein Array sein.")
    wallboxes: dict[str, dict[str, Any]] = {
        str(w.get("id")): w for w in existing if isinstance(w, dict)
    }
    new_ids: list[str] = []
    for profile, consumer in _iter_evs(out.get(HOUSE_FILE)):
        if not _ev_pending(consumer):
            continue
        # The EV carried this activation since dm4.required_signal_activation; an EV
        # without it gets it on its wallbox, so that step stays done.
        candidate = activate_wallbox_required(_wallbox_from_ev(consumer))
        known = wallboxes.get(candidate["id"])
        if known is not None and _charger_data(known) != _charger_data(candidate):
            return _blocked(
                docs,
                f"E-Auto '{candidate['id']}' (Hausprofil '{profile.get('id')}'): dieselbe "
                "Kennung steht in mehreren Hausprofilen mit unterschiedlicher Ladeleistung, "
                "Spannung, Phasen oder Lade-Bindings. Ein E-Auto gehört zu genau einem "
                "Hausprofil — vor der Migration angleichen oder in einem Profil umbenennen.",
            )
        if known is None:
            wallboxes[candidate["id"]] = candidate
            new_ids.append(candidate["id"])
        _rewrite_ev(consumer, wallboxes[candidate["id"]])
    if new_ids:
        components[WALLBOXES_KEY] = [*existing, *(wallboxes[i] for i in new_ids)]
    # Data model 5 → 6 for every Earnie-track file of the pack.
    for name in EARNIE_TRACK_FILES:
        doc = out.get(name)
        if isinstance(doc, dict) and read_data_model(doc) != CURRENT_DATA_MODEL:
            stamp_data_model(doc)
    changed = tuple(sorted(name for name in out if out.get(name) != docs.get(name)))
    return StepResult(docs=out, changed_files=changed)


STEP = MigrationStep(
    id=STEP_ID,
    data_model=6,
    title_de=(
        "Datenmodell 6: Wallboxen als Anlagenteil — je E-Auto eine Wallbox in den Komponenten, "
        "Ladegrenzen als Strom (A) an Wallbox und E-Auto, feste Zuordnung"
    ),
    files=tuple(sorted(EARNIE_TRACK_FILES)),
    detect=detect,
    apply=apply,
)
