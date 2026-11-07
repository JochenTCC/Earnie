"""Scenario Explorer fixed standing charges (post-aggregation only)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace


@dataclass(frozen=True)
class GridFixedPart:
    """One fixed yearly amount of the grid area, billed as in Edibert's invoice check."""

    label: str
    net_eur_year: float
    gross_monthly_eur: float  # one twelfth, with the import tariff's VAT


@dataclass(frozen=True)
class ScenarioFeeBreakdown:
    """EUR/month fixed fees for one SE result scenario."""

    supplier_monthly_eur: float = 0.0
    grid_monthly_eur: float = 0.0  # the grid area's fixed amounts (``grid_fixed_parts``)
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
    ("metering_monthly_fee_eur", "metering_monthly_eur"),
    ("other_monthly_fee_eur", "other_monthly_eur"),
)


def _fee_from_spec(spec: dict | None, key: str = "monthly_fee_eur") -> float:
    """Fee as on the invoice: gross, like the work price (Edibert's ``monthly_fees_eur``)."""
    if not isinstance(spec, dict):
        return 0.0
    raw = spec.get(key)
    if raw is None:
        return 0.0
    fee = float(raw)
    if fee == 0.0:
        return 0.0
    include_vat = spec.get("prices_include_vat")
    vat = spec.get("vat_percent")
    if include_vat is None or (not include_vat and vat is None):
        tariff_id = str(spec.get("id") or "?").strip() or "?"
        raise ValueError(
            f"Tarif '{tariff_id}': prices_include_vat oder vat_percent fehlt für {key}."
        )
    return fee if include_vat else fee * (1.0 + float(vat) / 100.0)


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
    """Total EUR/month fixed fees of the tariffs (supplier + household), without the grid area's."""
    return fee_breakdown_from_specs(import_spec, export_spec).total_monthly_eur


def fee_breakdown_from_specs(
    import_spec: dict | None,
    export_spec: dict | None,
) -> ScenarioFeeBreakdown:
    """Tariff fees only, gross. Supplier fee: max per supplier_id, sum across suppliers. Household: once."""
    by_supplier: dict[str, float] = {}
    for spec in (import_spec, export_spec):
        if not isinstance(spec, dict) or not spec:
            continue
        sid = _require_supplier_id(spec)
        fee = _fee_from_spec(spec, "monthly_fee_eur")
        prev = by_supplier.get(sid)
        by_supplier[sid] = fee if prev is None else max(prev, fee)
    household: dict[str, float] = {}
    for catalog_key, attr in _HOUSEHOLD_FEE_KEYS:
        household[attr] = _household_fee_from_specs(import_spec, export_spec, catalog_key)
    return ScenarioFeeBreakdown(
        supplier_monthly_eur=float(sum(by_supplier.values())),
        metering_monthly_eur=household["metering_monthly_eur"],
        other_monthly_eur=household["other_monthly_eur"],
    )


def monthly_fee_eur_from_params(params: dict | None) -> float:
    """Fee from resolved scenario params (`_import_tariff_spec` / `_export_tariff_spec`)."""
    return fee_breakdown_from_params(params).total_monthly_eur


def grid_fixed_parts(params: dict | None) -> tuple[GridFixedPart, ...]:
    """Fixed amounts of the scenario's grid area; empty without a pricing reference or ``netznutzung``."""
    from data.edibert_slot_prices import EDIBERT_PRICING_KEY, grid_fee, tariff
    from house_config.edibert_tariffs import IMPORT

    ref = params.get(EDIBERT_PRICING_KEY) if isinstance(params, dict) else None
    if not isinstance(ref, dict):
        return ()
    fee = grid_fee(ref)
    if fee is None or not fee.fixed:
        return ()
    factor = 1.0 + float(tariff(ref, IMPORT).vat_percent) / 100.0
    return tuple(
        GridFixedPart(part.label, float(part.value), float(part.value) / 12.0 * factor)
        for part in fee.fixed
    )


def fee_breakdown_from_params(params: dict | None) -> ScenarioFeeBreakdown:
    if not isinstance(params, dict):
        return ScenarioFeeBreakdown()
    return replace(
        fee_breakdown_from_specs(
            params.get("_import_tariff_spec"),
            params.get("_export_tariff_spec"),
        ),
        grid_monthly_eur=sum(part.gross_monthly_eur for part in grid_fixed_parts(params)),
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
