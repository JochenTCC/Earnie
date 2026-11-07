"""Import cap of a scenario: the user's limit for the 15-minute grid import (max-power tariff).

Two optional settings on a scenario. Both absent means no cap, so existing files stay valid. The
cap counts only in months with a capacity charge (plan decision D3); which months those are comes
from the grid area through Edibert.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

IMPORT_CAP_KEY = "import_cap_kw"
IMPORT_CAP_MARGIN_KEY = "import_cap_margin_kw"
MARGIN_PROPOSAL_KW = 0.3  # placeholder until the field test of the max-power plan (P5) sets it


@dataclass(frozen=True)
class ImportCap:
    cap_kw: float
    margin_kw: float

    @property
    def planned_kw(self) -> float:
        """What the plan aims for: the cap less the margin."""
        return self.cap_kw - self.margin_kw


@dataclass(frozen=True)
class ImportCapCheck:
    """``errors`` stop saving in the form, ``notes`` say when the cap does not act."""

    errors: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


def _number(value: Any, key: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} ungültig: {value!r}.")
    return float(value)


def parse_import_cap(settings: dict | None) -> ImportCap | None:
    """The cap of scenario settings; ``None`` without one. Invalid values raise ``ValueError``."""
    data = settings or {}
    has_cap = data.get(IMPORT_CAP_KEY) is not None
    has_margin = data.get(IMPORT_CAP_MARGIN_KEY) is not None
    if not has_cap and not has_margin:
        return None
    if not has_cap or not has_margin:
        raise ValueError(f"{IMPORT_CAP_KEY} und {IMPORT_CAP_MARGIN_KEY} gehören zusammen.")
    cap = _number(data[IMPORT_CAP_KEY], IMPORT_CAP_KEY)
    margin = _number(data[IMPORT_CAP_MARGIN_KEY], IMPORT_CAP_MARGIN_KEY)
    if cap <= 0.0:
        raise ValueError(f"{IMPORT_CAP_KEY} muss > 0 sein (Feld weglassen = keine Grenze).")
    if margin < 0.0:
        raise ValueError(f"{IMPORT_CAP_MARGIN_KEY} muss >= 0 sein.")
    if margin >= cap:
        raise ValueError(f"{IMPORT_CAP_MARGIN_KEY} muss kleiner als {IMPORT_CAP_KEY} sein.")
    return ImportCap(cap, margin)


def check_import_cap(cap: ImportCap, fee: Any | None, today: date) -> ImportCapCheck:
    """What the grid area ``fee`` (Edibert ``GridFee``, ``None`` without area) means for the cap."""
    if fee is None:
        return ImportCapCheck(
            errors=("Eine Bezugsgrenze braucht ein Hausprofil mit Netzbereich (Netznutzung).",)
        )
    month = today.replace(day=1)
    open_charges = [c for c in fee.capacity if c.valid_to is None or c.valid_to >= month]
    if not open_charges:
        skipped = ", ".join(f"{cid} (Status {status})" for cid, status in fee.capacity_skipped.items())
        return ImportCapCheck(
            notes=(
                f"Der Netzbereich hat keinen freigegebenen Leistungspreis{f': {skipped}' if skipped else ''}. "
                "Die Grenze bleibt inaktiv.",
            )
        )
    errors: list[str] = []
    minimum = max(float(charge.min_kw) for charge in open_charges)
    if cap.cap_kw < minimum:
        errors.append(
            f"Die Bezugsgrenze liegt unter der Mindestleistung des Netzbereichs ({minimum:g} kW). "
            "Darunter spart sie nichts."
        )
    notes: list[str] = []
    if not any(charge.covers(month) for charge in open_charges):
        starts = [c.valid_from for c in open_charges if c.valid_from is not None]
        if starts:
            notes.append(f"Die Grenze bleibt inaktiv bis {min(starts):%m/%Y}: Dann beginnt der Leistungspreis.")
    return ImportCapCheck(errors=tuple(errors), notes=tuple(notes))
