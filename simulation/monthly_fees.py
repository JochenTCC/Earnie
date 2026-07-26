"""Scenario Explorer fixed standing charges (post-aggregation only)."""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ScenarioFeeBreakdown:
    """EUR/month fixed fees for one SE result scenario."""

    supplier_monthly_eur: float = 0.0
    grid_monthly_eur: float = 0.0
    metering_monthly_eur: float = 0.0
    other_monthly_eur: float = 0.0

    @property
    def total_monthly_eur(self) -> float:
        return float(
            self.supplier_monthly_eur
            + self.grid_monthly_eur
            + self.metering_monthly_eur
            + self.other_monthly_eur
        )

    def as_dict(self) -> dict[str, float]:
        payload = asdict(self)
        payload["total_monthly_eur"] = self.total_monthly_eur
        return {key: float(value) for key, value in payload.items()}


_HOUSEHOLD_FEE_KEYS = (
    ("grid_monthly_fee_eur", "grid_monthly_eur"),
    ("metering_monthly_fee_eur", "metering_monthly_eur"),
    ("other_monthly_fee_eur", "other_monthly_eur"),
)


def _fee_from_spec(spec: dict | None, key: str = "monthly_fee_eur") -> float:
    if not isinstance(spec, dict):
        return 0.0
    raw = spec.get(key)
    if raw is None:
        return 0.0
    return float(raw)


def _require_supplier_id(spec: dict) -> str:
    sid = str(spec.get("supplier_id") or "").strip()
    if not sid:
        tariff_id = str(spec.get("id") or "?").strip() or "?"
        raise ValueError(
            f"Tarif '{tariff_id}': supplier_id fehlt für Monatsgebühr-Aggregation."
        )
    return sid


def _household_fee_from_specs(
    import_spec: dict | None,
    export_spec: dict | None,
    key: str,
) -> float:
    """Once per scenario: import wins; else export (do not sum both)."""
    import_fee = _fee_from_spec(import_spec, key)
    if import_fee or (
        isinstance(import_spec, dict) and import_spec.get(key) is not None
    ):
        return import_fee
    return _fee_from_spec(export_spec, key)


def monthly_fee_eur_from_specs(
    import_spec: dict | None,
    export_spec: dict | None,
) -> float:
    """Total EUR/month fixed fees (supplier + household)."""
    return fee_breakdown_from_specs(import_spec, export_spec).total_monthly_eur


def fee_breakdown_from_specs(
    import_spec: dict | None,
    export_spec: dict | None,
) -> ScenarioFeeBreakdown:
    """Supplier fee: max per supplier_id, sum across suppliers. Household: once."""
    by_supplier: dict[str, float] = {}
    for spec in (import_spec, export_spec):
        if not isinstance(spec, dict) or not spec:
            continue
        fee = _fee_from_spec(spec, "monthly_fee_eur")
        sid = _require_supplier_id(spec)
        prev = by_supplier.get(sid)
        by_supplier[sid] = fee if prev is None else max(prev, fee)
    household: dict[str, float] = {}
    for catalog_key, attr in _HOUSEHOLD_FEE_KEYS:
        household[attr] = _household_fee_from_specs(import_spec, export_spec, catalog_key)
    return ScenarioFeeBreakdown(
        supplier_monthly_eur=float(sum(by_supplier.values())),
        grid_monthly_eur=household["grid_monthly_eur"],
        metering_monthly_eur=household["metering_monthly_eur"],
        other_monthly_eur=household["other_monthly_eur"],
    )


def monthly_fee_eur_from_params(params: dict | None) -> float:
    """Fee from resolved scenario params (`_import_tariff_spec` / `_export_tariff_spec`)."""
    return fee_breakdown_from_params(params).total_monthly_eur


def fee_breakdown_from_params(params: dict | None) -> ScenarioFeeBreakdown:
    if not isinstance(params, dict):
        return ScenarioFeeBreakdown()
    return fee_breakdown_from_specs(
        params.get("_import_tariff_spec"),
        params.get("_export_tariff_spec"),
    )


def monthly_fees_by_result_id(
    *,
    scenarios: dict[str, dict],
    historical_params: dict | None,
    historical_id: str,
    extra_ref_specs: list[tuple[str, dict | None, str]] | None = None,
) -> dict[str, float]:
    """Map SE result IDs → EUR/month total fee (0 if unknown)."""
    return {
        sid: breakdown.total_monthly_eur
        for sid, breakdown in fee_breakdowns_by_result_id(
            scenarios=scenarios,
            historical_params=historical_params,
            historical_id=historical_id,
            extra_ref_specs=extra_ref_specs,
        ).items()
    }


def fee_breakdowns_by_result_id(
    *,
    scenarios: dict[str, dict],
    historical_params: dict | None,
    historical_id: str,
    extra_ref_specs: list[tuple[str, dict | None, str]] | None = None,
) -> dict[str, ScenarioFeeBreakdown]:
    """Map SE result IDs → fee breakdown."""
    fees: dict[str, ScenarioFeeBreakdown] = {
        historical_id: fee_breakdown_from_params(historical_params),
    }
    for scenario_id, params in scenarios.items():
        fees[scenario_id] = fee_breakdown_from_params(params)
    for ref_id, params, _label in extra_ref_specs or ():
        fees[ref_id] = fee_breakdown_from_params(params)
    return fees
