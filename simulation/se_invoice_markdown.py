"""Fake annual invoices (markdown) after Scenario Explorer runs."""
from __future__ import annotations

import os
import re

import pandas as pd

from simulation.monthly_fees import ScenarioFeeBreakdown
from simulation.period_clip import clip_results_to_period


def _safe_filename(scenario_id: str) -> str:
    cleaned = re.sub(r"[^\w.\-]+", "_", str(scenario_id).strip(), flags=re.UNICODE)
    return cleaned.strip("._") or "scenario"


def _fmt_eur(value: float) -> str:
    return f"{float(value):.2f} €"


def _fmt_kwh(value: float) -> str:
    return f"{float(value):.1f} kWh"


def _tariff_line(spec: dict | None, *, kind: str) -> str:
    if not isinstance(spec, dict) or not spec:
        return f"{kind}: —"
    label = str(spec.get("label") or spec.get("id") or "—").strip() or "—"
    tariff_id = str(spec.get("id") or "").strip()
    if tariff_id:
        return f"{kind}: {label} (`{tariff_id}`)"
    return f"{kind}: {label}"


def _series_or_zero(df: pd.DataFrame, column: str) -> pd.Series:
    if column in df.columns and not df.empty:
        return df[column].fillna(0.0).astype(float)
    return pd.Series(0.0, index=df.index, dtype=float)


def _month_keys(df: pd.DataFrame) -> list[str]:
    if df.empty:
        return []
    return sorted({pd.Timestamp(ts).strftime("%Y-%m") for ts in df.index})


def _monthly_sum(series: pd.Series, month_key: str) -> float:
    if series.empty:
        return 0.0
    mask = pd.DatetimeIndex(series.index).strftime("%Y-%m") == month_key
    return float(series.loc[mask].sum())


def render_scenario_invoice_markdown(
    *,
    scenario_id: str,
    label: str,
    df: pd.DataFrame,
    fees: ScenarioFeeBreakdown,
    import_spec: dict | None,
    export_spec: dict | None,
) -> str:
    """Build one German fake-Jahresrechnung markdown body."""
    import_cost = _series_or_zero(df, "import_cost_eur")
    export_earn = _series_or_zero(df, "export_earn_eur")
    import_kwh = _series_or_zero(df, "import_kwh")
    export_kwh = _series_or_zero(df, "export_kwh")
    # Hourly kW series at 1 h resolution → kWh when summed.
    consumption_kwh = _series_or_zero(df, "consumption_kw")
    if "sim_cost" in df.columns and not df.empty:
        # Prefer explicit parts; fall back to net if parts missing.
        if "import_cost_eur" not in df.columns:
            net = df["sim_cost"].fillna(0.0).astype(float)
            import_cost = net.clip(lower=0.0)
            export_earn = (-net).clip(lower=0.0)

    months = _month_keys(df)
    month_count = len(months)
    fee_total_year = fees.total_monthly_eur * month_count
    import_year = float(import_cost.sum()) if not df.empty else 0.0
    export_year = float(export_earn.sum()) if not df.empty else 0.0
    import_kwh_year = float(import_kwh.sum()) if not df.empty else 0.0
    export_kwh_year = float(export_kwh.sum()) if not df.empty else 0.0
    consumption_kwh_year = float(consumption_kwh.sum()) if not df.empty else 0.0
    total_year = import_year - export_year + fee_total_year

    lines = [
        f"# Fake-Jahresrechnung — {label}",
        "",
        f"Szenario-ID: `{scenario_id}`",
        "",
        _tariff_line(import_spec, kind="Bezugstarif"),
        "",
        _tariff_line(export_spec, kind="Einspeisetarif"),
        "",
        "## Jahr",
        "",
        "| Position | Betrag |",
        "| --- | ---: |",
        f"| Energiebezug | {_fmt_eur(import_year)} ({_fmt_kwh(import_kwh_year)}) |",
        f"| Einspeiseerlös | −{_fmt_eur(export_year)} ({_fmt_kwh(export_kwh_year)}) |",
        f"| Verbrauch (Info) | {_fmt_kwh(consumption_kwh_year)} |",
        f"| Lieferant-Grundpreis | {_fmt_eur(fees.supplier_monthly_eur * month_count)} |",
        f"| Netzentgelt-Grundpreis | {_fmt_eur(fees.grid_monthly_eur * month_count)} |",
        f"| Messstellengebühr | {_fmt_eur(fees.metering_monthly_eur * month_count)} |",
        f"| Sonstige Fixkosten | {_fmt_eur(fees.other_monthly_eur * month_count)} |",
        f"| **Gesamt** | **{_fmt_eur(total_year)}** |",
        "",
        "## Monate",
        "",
        "| Monat | Verbrauch kWh | Bezug kWh | Bezug € | Einspeisung kWh | Einspeisung € | Fixkosten € | Summe € |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for month_key in months:
        m_import = _monthly_sum(import_cost, month_key)
        m_export = _monthly_sum(export_earn, month_key)
        m_import_kwh = _monthly_sum(import_kwh, month_key)
        m_export_kwh = _monthly_sum(export_kwh, month_key)
        m_consumption_kwh = _monthly_sum(consumption_kwh, month_key)
        m_fees = fees.total_monthly_eur
        m_sum = m_import - m_export + m_fees
        lines.append(
            f"| {month_key} | {m_consumption_kwh:.1f} | {m_import_kwh:.1f} | {m_import:.2f} | "
            f"{m_export_kwh:.1f} | {m_export:.2f} | {m_fees:.2f} | {m_sum:.2f} |"
        )
    if not months:
        lines.append("| — | 0.0 | 0.0 | 0.00 | 0.0 | 0.00 | 0.00 | 0.00 |")

    lines.extend(
        [
            "",
            "## Hinweise",
            "",
            "- Näherung für Plausibilität im Szenario-Explorer — **keine** echte Stromrechnung.",
            "- Verbrauch (Hauslast inkl. Flex) ist nur Info und geht **nicht** in die Rechnungssumme ein.",
            "- Fixkosten: Lieferant-Grundpreis je `supplier_id` einmal; "
            "Netzentgelt-/Messstellen-/Sonstige Fixkosten einmal je Hausanschluss "
            "(aus Bezugstarif, sonst Einspeisetarif).",
            "- Nicht modelliert: PLZ-/netzgebietsspezifische Stacks, separate Stromsteuer/"
            "Konzessionsabgabe/Elektrizitätsabgabe (oft im Arbeitspreis).",
            "",
        ]
    )
    return "\n".join(lines)


def _params_for_result_id(
    scenario_id: str,
    *,
    scenarios: dict[str, dict],
    historical_params: dict | None,
    historical_id: str,
    extra_ref_specs: list[tuple[str, dict | None, str]] | None,
) -> dict | None:
    if scenario_id == historical_id:
        return historical_params
    if scenario_id in scenarios:
        return scenarios[scenario_id]
    for ref_id, params, _label in extra_ref_specs or ():
        if ref_id == scenario_id:
            return params
    return None


def write_se_invoices(
    *,
    log_dir: str,
    results: dict[str, pd.DataFrame],
    labels: dict[str, str],
    fee_breakdown_by_scenario: dict[str, ScenarioFeeBreakdown],
    scenarios: dict[str, dict],
    historical_params: dict | None,
    historical_id: str,
    extra_ref_specs: list[tuple[str, dict | None, str]] | None = None,
    period_start: str | None = None,
    period_end: str | None = None,
) -> list[str]:
    """Write one markdown invoice per result scenario under ``log_dir/invoices/``."""
    invoice_dir = os.path.join(log_dir, "invoices")
    os.makedirs(invoice_dir, exist_ok=True)
    written: list[str] = []
    for scenario_id, df in results.items():
        frame = df if isinstance(df, pd.DataFrame) else pd.DataFrame()
        if period_start and period_end and not frame.empty:
            frame = clip_results_to_period(frame, period_start, period_end)
        params = _params_for_result_id(
            scenario_id,
            scenarios=scenarios,
            historical_params=historical_params,
            historical_id=historical_id,
            extra_ref_specs=extra_ref_specs,
        )
        import_spec = None
        export_spec = None
        if isinstance(params, dict):
            import_spec = params.get("_import_tariff_spec")
            export_spec = params.get("_export_tariff_spec")
        fees = fee_breakdown_by_scenario.get(scenario_id) or ScenarioFeeBreakdown()
        body = render_scenario_invoice_markdown(
            scenario_id=scenario_id,
            label=labels.get(scenario_id, scenario_id),
            df=frame,
            fees=fees,
            import_spec=import_spec if isinstance(import_spec, dict) else None,
            export_spec=export_spec if isinstance(export_spec, dict) else None,
        )
        path = os.path.join(
            invoice_dir, f"{_safe_filename(scenario_id)}_jahresrechnung.md"
        )
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(body)
        written.append(path)
    return written
