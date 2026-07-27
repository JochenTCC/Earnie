"""Fake annual invoices (markdown) after Scenario Explorer runs."""
from __future__ import annotations

import os
import re
from typing import Literal

import pandas as pd

from data.tariff_parameter_preview import tariff_parameter_rows
from simulation.monthly_fees import ScenarioFeeBreakdown
from simulation.period_clip import clip_results_to_period


def _safe_filename(scenario_id: str) -> str:
    cleaned = re.sub(r"[^\w.\-]+", "_", str(scenario_id).strip(), flags=re.UNICODE)
    return cleaned.strip("._") or "scenario"


def _fmt_eur(value: float) -> str:
    return f"{float(value):.2f} €"


def _fmt_kwh(value: float) -> str:
    return f"{float(value):.1f} kWh"


def _fmt_cent(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{float(value):.2f}"


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


def _series_or_nan(df: pd.DataFrame, column: str) -> pd.Series:
    if column in df.columns and not df.empty:
        return pd.to_numeric(df[column], errors="coerce")
    return pd.Series(float("nan"), index=df.index, dtype=float)


def _month_keys(df: pd.DataFrame) -> list[str]:
    if df.empty:
        return []
    return sorted({pd.Timestamp(ts).strftime("%Y-%m") for ts in df.index})


def _month_mask(series: pd.Series, month_key: str) -> pd.Series:
    if series.empty:
        return pd.Series(dtype=bool)
    return pd.Series(
        pd.DatetimeIndex(series.index).strftime("%Y-%m") == month_key,
        index=series.index,
    )


def _monthly_sum(series: pd.Series, month_key: str) -> float:
    if series.empty:
        return 0.0
    return float(series.loc[_month_mask(series, month_key)].sum())


def _mean_tariff_cent(price: pd.Series, month_key: str | None = None) -> float | None:
    """Arithmetic mean of hourly tariff prices over all hours (month or full period)."""
    if price.empty:
        return None
    subset = price if month_key is None else price.loc[_month_mask(price, month_key)]
    valid = subset.dropna()
    if valid.empty:
        return None
    return float(valid.sum() / len(valid))


def _actual_avg_cent(cost_eur: float, energy_kwh: float) -> float | None:
    if energy_kwh <= 0.0:
        return None
    return float(cost_eur) / float(energy_kwh) * 100.0


def _energy_table_lines(
    *,
    title: str,
    energy_label: str,
    eur_label: str,
    months: list[str],
    energy: pd.Series,
    cost_eur: pd.Series,
    price_cent: pd.Series,
) -> list[str]:
    lines = [
        f"## {title}",
        "",
        f"| Monat | {energy_label} | {eur_label} | Ø Tarif Cent/kWh | Ø Ist Cent/kWh |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for month_key in months:
        m_energy = _monthly_sum(energy, month_key)
        m_eur = _monthly_sum(cost_eur, month_key)
        m_tariff = _mean_tariff_cent(price_cent, month_key)
        m_actual = _actual_avg_cent(m_eur, m_energy)
        lines.append(
            f"| {month_key} | {m_energy:.1f} | {m_eur:.2f} | "
            f"{_fmt_cent(m_tariff)} | {_fmt_cent(m_actual)} |"
        )
    energy_year = float(energy.sum()) if not energy.empty else 0.0
    eur_year = float(cost_eur.sum()) if not cost_eur.empty else 0.0
    tariff_year = _mean_tariff_cent(price_cent)
    actual_year = _actual_avg_cent(eur_year, energy_year)
    if months:
        lines.append(
            f"| **Jahr** | **{energy_year:.1f}** | **{eur_year:.2f}** | "
            f"**{_fmt_cent(tariff_year)}** | **{_fmt_cent(actual_year)}** |"
        )
    else:
        lines.append("| — | 0.0 | 0.00 | — | — |")
    lines.append("")
    return lines


def _catalog_table_lines(
    *,
    title: str,
    spec: dict | None,
    kind: Literal["import", "export"],
) -> list[str]:
    lines = [f"## {title}", ""]
    if not isinstance(spec, dict) or not spec:
        lines.extend(["Keine Tarifdaten.", ""])
        return lines
    rows = tariff_parameter_rows(spec, kind=kind)
    lines.extend(["| Parameter | Wert |", "| --- | --- |"])
    if not rows:
        lines.append("| — | — |")
    else:
        for label, value in rows:
            safe_value = str(value).replace("|", "\\|")
            lines.append(f"| {label} | {safe_value} |")
    lines.append("")
    return lines


def _invoice_energy_series(
    df: pd.DataFrame,
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series, pd.Series, pd.Series, pd.Series]:
    import_cost = _series_or_zero(df, "import_cost_eur")
    export_earn = _series_or_zero(df, "export_earn_eur")
    import_kwh = _series_or_zero(df, "import_kwh")
    export_kwh = _series_or_zero(df, "export_kwh")
    k_act = _series_or_nan(df, "k_act")
    k_push_act = _series_or_nan(df, "k_push_act")
    consumption_kwh = _series_or_zero(df, "consumption_kw")
    if "sim_cost" in df.columns and not df.empty and "import_cost_eur" not in df.columns:
        net = df["sim_cost"].fillna(0.0).astype(float)
        import_cost = net.clip(lower=0.0)
        export_earn = (-net).clip(lower=0.0)
    return (
        import_cost,
        export_earn,
        import_kwh,
        export_kwh,
        k_act,
        k_push_act,
        consumption_kwh,
    )


def _year_summary_lines(
    *,
    import_year: float,
    export_year: float,
    import_kwh_year: float,
    export_kwh_year: float,
    consumption_kwh_year: float,
    fees: ScenarioFeeBreakdown,
    month_count: int,
    total_year: float,
) -> list[str]:
    return [
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
    ]


def _hinweise_lines() -> list[str]:
    return [
        "## Hinweise",
        "",
        "- Näherung für Plausibilität im Szenario-Explorer — **keine** echte Stromrechnung.",
        "- Verbrauch (Hauslast inkl. Flex) ist nur Info und geht **nicht** in die Rechnungssumme ein.",
        "- Ø Tarif Cent/kWh: arithmetisches Mittel der stündlichen Tarifpreise "
        "über alle Stunden des Monats (`Summe(k_act)/N` bzw. `k_push_act`).",
        "- Ø Ist Cent/kWh: `Energiekosten € / Netzenergie kWh × 100` "
        "(nur Stunden mit Bezug bzw. Einspeisung wirken über die Summen).",
        "- Fixkosten: Lieferant-Grundpreis je `supplier_id` einmal; "
        "Netzentgelt-/Messstellen-/Sonstige Fixkosten einmal je Hausanschluss "
        "(aus Bezugstarif, sonst Einspeisetarif).",
        "- Nicht modelliert: PLZ-/netzgebietsspezifische Stacks, separate Stromsteuer/"
        "Konzessionsabgabe/Elektrizitätsabgabe (oft im Arbeitspreis).",
        "",
    ]


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
    (
        import_cost,
        export_earn,
        import_kwh,
        export_kwh,
        k_act,
        k_push_act,
        consumption_kwh,
    ) = _invoice_energy_series(df)
    months = _month_keys(df)
    month_count = len(months)
    import_year = float(import_cost.sum()) if not df.empty else 0.0
    export_year = float(export_earn.sum()) if not df.empty else 0.0
    import_kwh_year = float(import_kwh.sum()) if not df.empty else 0.0
    export_kwh_year = float(export_kwh.sum()) if not df.empty else 0.0
    consumption_kwh_year = float(consumption_kwh.sum()) if not df.empty else 0.0
    total_year = import_year - export_year + fees.total_monthly_eur * month_count

    lines = [
        f"# Fake-Jahresrechnung — {label}",
        "",
        f"Szenario-ID: `{scenario_id}`",
        "",
        _tariff_line(import_spec, kind="Bezugstarif"),
        "",
        _tariff_line(export_spec, kind="Einspeisetarif"),
        "",
    ]
    lines.extend(
        _year_summary_lines(
            import_year=import_year,
            export_year=export_year,
            import_kwh_year=import_kwh_year,
            export_kwh_year=export_kwh_year,
            consumption_kwh_year=consumption_kwh_year,
            fees=fees,
            month_count=month_count,
            total_year=total_year,
        )
    )
    lines.extend(
        _energy_table_lines(
            title="Bezug",
            energy_label="Bezug kWh",
            eur_label="Bezug €",
            months=months,
            energy=import_kwh,
            cost_eur=import_cost,
            price_cent=k_act,
        )
    )
    lines.extend(
        _energy_table_lines(
            title="Einspeisung",
            energy_label="Einspeisung kWh",
            eur_label="Einspeisung €",
            months=months,
            energy=export_kwh,
            cost_eur=export_earn,
            price_cent=k_push_act,
        )
    )
    lines.extend(_hinweise_lines())
    lines.extend(
        _catalog_table_lines(
            title="Katalogparameter Bezug",
            spec=import_spec,
            kind="import",
        )
    )
    lines.extend(
        _catalog_table_lines(
            title="Katalogparameter Einspeisung",
            spec=export_spec,
            kind="export",
        )
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
        label = labels.get(scenario_id, scenario_id)
        body = render_scenario_invoice_markdown(
            scenario_id=scenario_id,
            label=label,
            df=frame,
            fees=fees,
            import_spec=import_spec if isinstance(import_spec, dict) else None,
            export_spec=export_spec if isinstance(export_spec, dict) else None,
        )
        path = os.path.join(
            invoice_dir, f"{_safe_filename(label)}_jahresrechnung.md"
        )
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(body)
        written.append(path)
    return written
