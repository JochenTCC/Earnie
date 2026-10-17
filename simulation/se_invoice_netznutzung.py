"""Netznutzung section of the SE invoice markdown (split from se_invoice_markdown)."""
from __future__ import annotations

from dataclasses import dataclass
import pandas as pd
from simulation.monthly_fees import ScenarioFeeBreakdown
from simulation.se_invoice_format import (
    _fmt_cent,
    _fmt_eur,
    _fmt_kwh,
)


def _grid_fee_from_params(params: dict | None) -> dict | None:
    """Aufgelöste Netzentgelt-Spec (``_grid_fee_spec``) aus SE-Params."""
    if not isinstance(params, dict):
        return None
    spec = params.get("_grid_fee_spec")
    return spec if isinstance(spec, dict) else None


def _netznutzung_ap_gross_cent(
    ap_net_cent: float,
    import_spec: dict | None,
) -> float:
    """Arbeitspreis Cent/kWh wie in k_act (USt laut Bezugstarif)."""
    if ap_net_cent <= 0.0:
        return 0.0
    spec = import_spec if isinstance(import_spec, dict) else {}
    if bool(spec.get("prices_include_vat", True)):
        return float(ap_net_cent)
    vat = float(spec.get("vat_percent", 0.0) or 0.0)
    return float(ap_net_cent) * (1.0 + vat / 100.0)


@dataclass(frozen=True)
class _NetznutzungComponent:
    """Ein Preisbestandteil (Basis oder Zeitregel) des Netz-Arbeitspreises."""

    label: str
    ap_net_cent: float
    import_kwh: float
    eur: float


def _netznutzung_components(
    df: pd.DataFrame,
    *,
    grid_fee: dict | None,
    import_spec: dict | None,
) -> list[_NetznutzungComponent]:
    """Netzbezug je Slot × (zeitabhängiger) brutto-Arbeitspreis, gruppiert je Regel."""
    if grid_fee is None or df.empty or "import_kwh" not in df.columns:
        return []
    from data.grid_fees import grid_fee_work_cent, matching_rule

    kwh_by_key: dict[str, float] = {}
    eur_by_key: dict[str, float] = {}
    net_by_key: dict[str, float] = {}
    labels: dict[str, str] = {"": "Basis"}
    order: list[str] = [""]
    for rule in grid_fee["rules"]:
        labels[rule["id"]] = f"{rule['id']} ({rule['label']})"
        order.append(rule["id"])
    for ts, kwh in df["import_kwh"].fillna(0.0).items():
        kwh = float(kwh)
        if kwh <= 0.0:
            continue
        slot = pd.Timestamp(ts).to_pydatetime()
        rule = matching_rule(grid_fee, slot)
        key = rule["id"] if rule else ""
        net = grid_fee_work_cent(grid_fee, slot)
        gross = _netznutzung_ap_gross_cent(net, import_spec)
        kwh_by_key[key] = kwh_by_key.get(key, 0.0) + kwh
        eur_by_key[key] = eur_by_key.get(key, 0.0) + kwh * gross / 100.0
        net_by_key[key] = net
    return [
        _NetznutzungComponent(labels[key], net_by_key[key], kwh_by_key[key], eur_by_key[key])
        for key in order
        if key in kwh_by_key
    ]


def _netznutzung_section_lines(
    *,
    ap_net_cent: float,
    ap_gross_cent: float,
    import_kwh_year: float,
    netznutzung_ap_eur: float,
    components: list[_NetznutzungComponent],
    skipped: list[dict],
    fees: ScenarioFeeBreakdown,
    month_count: int,
) -> list[str]:
    """Separate Netznutzung block (Arbeitspreis breakout + Grundpreis-Stub)."""
    lines = [
        "## Netznutzung",
        "",
        "| Position | Wert |",
        "| --- | ---: |",
        f"| Arbeitspreis netto (Basis) | {_fmt_cent(ap_net_cent)} Cent/kWh |",
        f"| Arbeitspreis in k_act (Basis) | {_fmt_cent(ap_gross_cent)} Cent/kWh |",
        f"| Netzbezug | {_fmt_kwh(import_kwh_year)} |",
        f"| Arbeitspreis (Jahr) | {_fmt_eur(netznutzung_ap_eur)} |",
        f"| Grundpreis (Katalog-Stub) | {_fmt_eur(fees.grid_monthly_eur * month_count)} |",
        "",
    ]
    if len(components) > 1 or any(c.label != "Basis" for c in components):
        lines.extend(
            [
                "| Arbeitspreis nach Zeitfenster | Netzbezug | Cent/kWh netto | Betrag |",
                "| --- | ---: | ---: | ---: |",
            ]
        )
        for comp in components:
            lines.append(
                f"| {comp.label} | {_fmt_kwh(comp.import_kwh)} | "
                f"{_fmt_cent(comp.ap_net_cent)} | {_fmt_eur(comp.eur)} |"
            )
        lines.append("")
    if skipped:
        skipped_text = ", ".join(f"{item['id']} ({item['reason']})" for item in skipped)
        lines.extend([f"Nicht berücksichtigte Regeln: {skipped_text}.", ""])
    lines.extend(
        [
            "Der Arbeitspreis kommt aus dem Hausprofil (`netznutzung`) und dem "
            "Netzentgelt-Katalog, unabhängig vom Lieferantentarif. In der "
            "Jahressumme ist er aus dem Energiebezug herausgerechnet (kein "
            "Doppelzählen). Leistungspreis fehlt.",
            "",
        ]
    )
    return lines
