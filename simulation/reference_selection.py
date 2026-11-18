"""Which SE references a run computes: the three boxes on the run page plus the hidden L2.

Boxes (``--references``): ``historical`` (Live without PV and storage, one series),
``l0`` (Referenz ohne Speicher, per scenario), ``l1`` (vendor-mode battery, per scenario).
L2 (Standard-Regeln) only with ``rule_reference``; it always runs with L0 and L1, since the
ladder headline needs L0, L2 and L3. The optimized scenarios, Live among them, always run.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from simulation.reference_costs import (
    HISTORICAL_REFERENCE_ID,
    LADDER_L1,
    LADDER_L2,
    plan_per_scenario_reference_tasks,
)
from simulation.reference_dedup import SharedReferencePlan, share_by_physical_setup

REF_HISTORICAL = "historical"
REF_L0 = "l0"
REF_L1 = LADDER_L1
SELECTABLE_REFERENCES = (REF_HISTORICAL, REF_L0, REF_L1)
# Value of ``--references`` for no box ticked.
NO_REFERENCES = "none"
# ``--references`` when the flag is left out: Historisch and Referenz ohne Speicher, as before.
DEFAULT_REFERENCES = (REF_HISTORICAL, REF_L0)
REFERENCE_LABELS = {
    REF_HISTORICAL: "Historisch",
    REF_L0: "Referenz ohne Speicher",
    REF_L1: "Wechselrichter-Eigenverbrauch (L1)",
}


def parse_references(text: str) -> tuple[str, ...]:
    """``historical,l0,l1`` → ordered tuple; ``none`` → empty. Unknown names fail loud."""
    raw = str(text or "").strip()
    if not raw:
        raise ValueError(
            f"--references braucht eine Liste aus {','.join(SELECTABLE_REFERENCES)} "
            f"oder {NO_REFERENCES}."
        )
    if raw == NO_REFERENCES:
        return ()
    names = [part.strip() for part in raw.split(",") if part.strip()]
    unknown = [name for name in names if name not in SELECTABLE_REFERENCES]
    if unknown:
        raise ValueError(
            f"Unbekannte Referenz {', '.join(unknown)}; erlaubt: "
            f"{', '.join(SELECTABLE_REFERENCES)} oder {NO_REFERENCES}."
        )
    return tuple(name for name in SELECTABLE_REFERENCES if name in names)


def format_references(references: tuple[str, ...] | list[str]) -> str:
    """Inverse of ``parse_references``."""
    ordered = [name for name in SELECTABLE_REFERENCES if name in references]
    return ",".join(ordered) if ordered else NO_REFERENCES


def effective_references(
    references: tuple[str, ...] | list[str], *, rule_reference: bool
) -> tuple[str, ...]:
    """The boxes plus what L2 needs: with ``rule_reference`` L0 and L1 always run."""
    chosen = set(references)
    if rule_reference:
        chosen |= {REF_L0, REF_L1}
    return tuple(name for name in SELECTABLE_REFERENCES if name in chosen)


@dataclass(frozen=True)
class ReferencePlan:
    """Everything a run computes besides the optimized scenarios.

    ``reference_by_scenario``: scenario → its L0 result id (empty without L0).
    ``l0_specs``: L0 series to produce, Historisch included when it runs, as
    ``(ref_id, params, label)``. ``l1_by_scenario``: scenario → its L1 result id.
    ``ladder_by_scenario``: L1 and L2 per scenario, only with ``rule_reference``.
    ``l0_sharing`` / ``l1_sharing``: which of those series are computed and which are booked
    from another tariff's flows (``simulation.reference_dedup``).
    """

    references: tuple[str, ...]
    rule_reference: bool
    reference_by_scenario: dict[str, str]
    l0_specs: list[tuple[str, dict | None, str]]
    l1_by_scenario: dict[str, str]
    ladder_by_scenario: dict[str, dict[str, str]]
    ladder_specs: list = field(default_factory=list)
    l0_sharing: SharedReferencePlan = SharedReferencePlan([], {})
    l1_sharing: SharedReferencePlan = SharedReferencePlan([], {})

    @property
    def runs_historical(self) -> bool:
        return any(ref_id == HISTORICAL_REFERENCE_ID for ref_id, _p, _l in self.l0_specs)

    @property
    def computed_ladder_specs(self) -> list:
        """L2 runs and the L1 runs that are not booked from another tariff's flows."""
        return [spec for spec in self.ladder_specs if spec.ref_id not in self.l1_sharing.rebooked]

    @property
    def computed_l0_specs(self) -> list[tuple[str, dict | None, str]]:
        return [spec for spec in self.l0_specs if spec[0] not in self.l0_sharing.rebooked]

    @property
    def all_ref_specs(self) -> list[tuple[str, dict, str]]:
        """Every per-scenario reference series (L0 without Historisch, L1, L2) with its params."""
        return [
            *((ref_id, params, label) for ref_id, params, label in self.l0_specs
              if ref_id != HISTORICAL_REFERENCE_ID),
            *((spec.ref_id, spec.params, spec.label) for spec in self.ladder_specs),
        ]

    def parallel_task_count(self, scenario_count: int) -> int:
        return len(self.computed_l0_specs) + len(self.computed_ladder_specs) + scenario_count


def plan_references(
    all_scenarios: dict[str, dict],
    scenarios: dict[str, dict],
    *,
    live_scenario_id: str,
    references: tuple[str, ...] | list[str],
    rule_reference: bool,
    historical_params: dict | None,
    historical_label: str,
    scenario_labels: dict[str, str] | None = None,
) -> ReferencePlan:
    """Plan the references of a run.

    ``all_scenarios``: what the L0 plan sees (Live and every active scenario, so a narrowed
    run keeps its L0); ``scenarios``: the ones that run.
    """
    from simulation.reference_ladder import plan_ladder_reference_tasks

    refs = effective_references(references, rule_reference=rule_reference)
    labels = scenario_labels or {}
    reference_by_scenario: dict[str, str] = {}
    extra_specs: list[tuple[str, dict, str]] = []
    if REF_L0 in refs:
        planned, _labels, planned_specs = plan_per_scenario_reference_tasks(
            all_scenarios, live_scenario_id=live_scenario_id, scenario_labels=labels
        )
        reference_by_scenario = {sid: planned[sid] for sid in scenarios}
        used = set(reference_by_scenario.values())
        extra_specs = [spec for spec in planned_specs if spec[0] in used]
    needs_historical = REF_HISTORICAL in refs or HISTORICAL_REFERENCE_ID in set(
        reference_by_scenario.values()
    )
    l0_specs: list[tuple[str, dict | None, str]] = [
        *([(HISTORICAL_REFERENCE_ID, historical_params, historical_label)] if needs_historical else []),
        *extra_specs,
    ]
    steps = (LADDER_L1, LADDER_L2) if rule_reference else (LADDER_L1,) if REF_L1 in refs else ()
    ladder_by_scenario, ladder_specs = (
        plan_ladder_reference_tasks(scenarios, steps=steps, scenario_labels=labels)
        if steps
        else ({}, [])
    )
    return ReferencePlan(
        references=refs,
        rule_reference=rule_reference,
        reference_by_scenario=reference_by_scenario,
        l0_specs=l0_specs,
        l1_by_scenario={sid: steps_[LADDER_L1] for sid, steps_ in ladder_by_scenario.items()},
        ladder_by_scenario=ladder_by_scenario if rule_reference else {},
        ladder_specs=ladder_specs,
        l0_sharing=share_by_physical_setup([(ref_id, params) for ref_id, params, _l in l0_specs]),
        l1_sharing=share_by_physical_setup(
            [(spec.ref_id, spec.params) for spec in ladder_specs if spec.step == LADDER_L1]
        ),
    )
