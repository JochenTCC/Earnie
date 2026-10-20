"""Fake annual invoices (markdown) after Scenario Explorer runs."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

import pandas as pd

from data.tariff_parameter_preview import tariff_parameter_rows
from simulation.monthly_fees import ScenarioFeeBreakdown
from simulation.period_clip import clip_results_to_period
from simulation.se_invoice_format import (  # noqa: F401  (re-exported)
    _fmt_cent,
    _fmt_eur,
    _fmt_kwh,
    _month_keys,
    _month_mask,
    _monthly_sum,
    _safe_filename,
    _series_or_nan,
    _series_or_zero,
)
from simulation.se_invoice_netznutzung import (  # noqa: F401  (re-exported)
    _NetznutzungComponent,
    _grid_fee_from_params,
    _netznutzung_ap_gross_cent,
    _netznutzung_components,
    _netznutzung_section_lines,
)


















def _tariff_line(spec: dict | None, *, kind: str) -> str:
    if not isinstance(spec, dict) or not spec:
        return f"{kind}: —"
    label = str(spec.get("label") or spec.get("id") or "—").strip() or "—"
    tariff_id = str(spec.get("id") or "").strip()
    if tariff_id:
        return f"{kind}: {label} (`{tariff_id}`)"
    return f"{kind}: {label}"












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
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series, pd.Series, pd.Series]:
    import_cost = _series_or_zero(df, "import_cost_eur")
    export_earn = _series_or_zero(df, "export_earn_eur")
    import_kwh = _series_or_zero(df, "import_kwh")
    export_kwh = _series_or_zero(df, "export_kwh")
    k_act = _series_or_nan(df, "k_act")
    k_push_act = _series_or_nan(df, "k_push_act")
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
    )


def _year_summary_lines(
    *,
    import_year: float,
    export_year: float,
    import_kwh_year: float,
    export_kwh_year: float,
    consumption_kwh_year: float,
    standby_kwh_year: float,
    fees: ScenarioFeeBreakdown,
    month_count: int,
    total_year: float,
    netznutzung_ap_eur: float = 0.0,
) -> list[str]:
    nne = max(0.0, min(float(netznutzung_ap_eur), float(import_year)))
    lieferant_eur = float(import_year) - nne
    lines = [
        "## Jahr",
        "",
        "| Position | Betrag |",
        "| --- | ---: |",
    ]
    if nne > 0.0:
        lines.append(
            f"| Energiebezug (Lieferant) | {_fmt_eur(lieferant_eur)} "
            f"({_fmt_kwh(import_kwh_year)}) |"
        )
        lines.append(f"| Netznutzung Arbeitspreis | {_fmt_eur(nne)} |")
    else:
        lines.append(
            f"| Energiebezug | {_fmt_eur(import_year)} ({_fmt_kwh(import_kwh_year)}) |"
        )
    lines.extend(
        [
            f"| Einspeiseerlös | −{_fmt_eur(export_year)} ({_fmt_kwh(export_kwh_year)}) |",
            f"| Verbrauch (Info) | {_fmt_kwh(consumption_kwh_year)} |",
        ]
    )
    if standby_kwh_year > 0.0:
        lines.append(f"| Speicher-Standby (Info) | {_fmt_kwh(standby_kwh_year)} |")
    lines.extend(
        [
            f"| Lieferant-Grundpreis | {_fmt_eur(fees.supplier_monthly_eur * month_count)} |",
            f"| Netzentgelt-Grundpreis | {_fmt_eur(fees.grid_monthly_eur * month_count)} |",
            f"| Messstellengebühr | {_fmt_eur(fees.metering_monthly_eur * month_count)} |",
            f"| Sonstige Fixkosten | {_fmt_eur(fees.other_monthly_eur * month_count)} |",
            f"| **Gesamt** | **{_fmt_eur(total_year)}** |",
            "",
        ]
    )
    return lines




def _hinweise_lines(*, has_netznutzung_ap: bool) -> list[str]:
    nne_hint = (
        "- Volumetrische **Netznutzung Arbeitspreis** (Hausprofil) ist in `k_act` "
        "enthalten und in der Jahrestabelle als eigene Position ausgewiesen "
        "(aus Energiebezug herausgerechnet)."
        if has_netznutzung_ap
        else "- Volumetrische **Netznutzung Arbeitspreis**: am Hausprofil setzen "
        "(`netznutzung`); sonst 0."
    )
    return [
        "## Hinweise",
        "",
        "- Näherung für Plausibilität im Szenario-Explorer — **keine** echte Stromrechnung.",
        nne_hint,
        "- **Leistungspreis** und netzgebietsspezifische Lookup-Tabellen werden "
        "**nicht** modelliert.",
        "- Verbrauch (Info) = gebuchter Verbrauch der Stundenreihe dieses Szenarios "
        "(jeder Zeitslot einmal, ohne Speicher-Standby) – derselbe Wert wie "
        "„Jahres Verbrauch“ in der SE-Tabelle Gesamtkosten.",
        "- Speicher-Standby (Info) = Eigenverbrauch der Hausbatterie; steckt in "
        "Bezug/Einspeisung, wird aber nicht als Hausverbrauch gezählt.",
        "- Verbrauch und Standby gehen **nicht** direkt in die Rechnungssumme ein.",
        "- Ø Tarif Cent/kWh: arithmetisches Mittel der stündlichen Tarifpreise "
        "über alle Stunden des Monats (`Summe(k_act)/N` bzw. `k_push_act`); "
        "enthält ggf. den Netznutzung-Arbeitspreis.",
        "- Ø Ist Cent/kWh: `Energiekosten € / Netzenergie kWh × 100` "
        "(nur Stunden mit Bezug bzw. Einspeisung wirken über die Summen).",
        "- Fixkosten: Lieferant-Grundpreis je `supplier_id` einmal; "
        "Netzentgelt-/Messstellen-/Sonstige Fixkosten einmal je Hausanschluss "
        "(aus Bezugstarif, sonst Einspeisetarif) — Katalog-Stubs.",
        "- Nicht modelliert: Leistungspreis, PLZ-/netzgebietsspezifische Stacks, "
        "separate Stromsteuer/Konzessionsabgabe/Elektrizitätsabgabe (oft im Arbeitspreis).",
        "",
    ]


@dataclass(frozen=True)
class _InvoiceYearContext:
    """Monatsreihen und Jahreswerte einer Fake-Jahresrechnung."""

    months: list[str]
    import_cost: pd.Series
    export_earn: pd.Series
    import_kwh: pd.Series
    export_kwh: pd.Series
    k_act: pd.Series
    k_push_act: pd.Series
    import_year: float
    export_year: float
    import_kwh_year: float
    export_kwh_year: float
    consumption_kwh_year: float
    standby_kwh_year: float
    total_year: float
    ap_net_cent: float
    ap_gross_cent: float
    netznutzung_ap_eur: float
    netznutzung_components: list[_NetznutzungComponent]
    netznutzung_skipped: list[dict]

    @property
    def month_count(self) -> int:
        return len(self.months)


def _build_invoice_year_context(
    df: pd.DataFrame,
    *,
    fees: ScenarioFeeBreakdown,
    import_spec: dict | None,
    booked_consumption: dict,
    grid_fee: dict | None,
) -> _InvoiceYearContext:
    """Monatsreihen plus Jahressummen, Netznutzungs-AP und Gesamtbetrag."""
    (
        import_cost,
        export_earn,
        import_kwh,
        export_kwh,
        k_act,
        k_push_act,
    ) = _invoice_energy_series(df)
    months = _month_keys(df)
    month_count = len(months)
    import_year = float(import_cost.sum()) if not df.empty else 0.0
    export_year = float(export_earn.sum()) if not df.empty else 0.0
    import_kwh_year = float(import_kwh.sum()) if not df.empty else 0.0
    export_kwh_year = float(export_kwh.sum()) if not df.empty else 0.0
    consumption_kwh_year = float(booked_consumption["consumption_kwh"])
    standby_kwh_year = float(booked_consumption["standby_kwh"])
    total_year = import_year - export_year + fees.total_monthly_eur * month_count
    components = _netznutzung_components(
        df, grid_fee=grid_fee, import_spec=import_spec
    )
    ap_net = float(grid_fee["base_cent_kwh"]) if grid_fee else 0.0
    ap_gross = _netznutzung_ap_gross_cent(ap_net, import_spec)
    nne_eur = sum(comp.eur for comp in components)
    if nne_eur > import_year:
        nne_eur = import_year
    return _InvoiceYearContext(
        months=months,
        import_cost=import_cost,
        export_earn=export_earn,
        import_kwh=import_kwh,
        export_kwh=export_kwh,
        k_act=k_act,
        k_push_act=k_push_act,
        import_year=import_year,
        export_year=export_year,
        import_kwh_year=import_kwh_year,
        export_kwh_year=export_kwh_year,
        consumption_kwh_year=consumption_kwh_year,
        standby_kwh_year=standby_kwh_year,
        total_year=total_year,
        ap_net_cent=ap_net,
        ap_gross_cent=ap_gross,
        netznutzung_ap_eur=nne_eur,
        netznutzung_components=components,
        netznutzung_skipped=list(grid_fee["skipped"]) if grid_fee else [],
    )


def _invoice_summary_lines(
    ctx: _InvoiceYearContext,
    fees: ScenarioFeeBreakdown,
) -> list[str]:
    """Jahresübersicht plus Netznutzungs-Abschnitt, sofern ein AP gesetzt ist."""
    lines: list[str] = []
    lines.extend(
        _year_summary_lines(
            import_year=ctx.import_year,
            export_year=ctx.export_year,
            import_kwh_year=ctx.import_kwh_year,
            export_kwh_year=ctx.export_kwh_year,
            consumption_kwh_year=ctx.consumption_kwh_year,
            standby_kwh_year=ctx.standby_kwh_year,
            fees=fees,
            month_count=ctx.month_count,
            total_year=ctx.total_year,
            netznutzung_ap_eur=ctx.netznutzung_ap_eur,
        )
    )
    if ctx.ap_net_cent > 0.0:
        lines.extend(
            _netznutzung_section_lines(
                ap_net_cent=ctx.ap_net_cent,
                ap_gross_cent=ctx.ap_gross_cent,
                import_kwh_year=ctx.import_kwh_year,
                netznutzung_ap_eur=ctx.netznutzung_ap_eur,
                components=ctx.netznutzung_components,
                skipped=ctx.netznutzung_skipped,
                fees=fees,
                month_count=ctx.month_count,
            )
        )
    return lines


def _invoice_month_table_lines(ctx: _InvoiceYearContext) -> list[str]:
    """Monatstabellen für Bezug und Einspeisung."""
    lines: list[str] = []
    lines.extend(
        _energy_table_lines(
            title="Bezug",
            energy_label="Bezug kWh",
            eur_label="Bezug €",
            months=ctx.months,
            energy=ctx.import_kwh,
            cost_eur=ctx.import_cost,
            price_cent=ctx.k_act,
        )
    )
    lines.extend(
        _energy_table_lines(
            title="Einspeisung",
            energy_label="Einspeisung kWh",
            eur_label="Einspeisung €",
            months=ctx.months,
            energy=ctx.export_kwh,
            cost_eur=ctx.export_earn,
            price_cent=ctx.k_push_act,
        )
    )
    return lines


def _invoice_catalog_lines(
    import_spec: dict | None,
    export_spec: dict | None,
) -> list[str]:
    """Katalogparameter-Tabellen für Bezug und Einspeisung."""
    lines: list[str] = []
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
    return lines


def render_scenario_invoice_markdown(
    *,
    scenario_id: str,
    label: str,
    df: pd.DataFrame,
    fees: ScenarioFeeBreakdown,
    import_spec: dict | None,
    export_spec: dict | None,
    booked_consumption: dict,
    grid_fee: dict | None = None,
) -> str:
    """Build one German fake-Jahresrechnung markdown body.

    ``booked_consumption`` is this result's ``booked_consumption_totals`` entry —
    the same source as SE Gesamtkosten Jahres Verbrauch / Speicher-Standby.

    ``grid_fee`` is the resolved house-profile grid-fee spec (``data.grid_fees``).
    When set, Jahr splits Lieferant vs Netznutzung (same Gesamt; AP already in k_act).
    """
    ctx = _build_invoice_year_context(
        df,
        fees=fees,
        import_spec=import_spec,
        booked_consumption=booked_consumption,
        grid_fee=grid_fee,
    )
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
    lines.extend(_invoice_summary_lines(ctx, fees))
    lines.extend(_invoice_month_table_lines(ctx))
    lines.extend(_hinweise_lines(has_netznutzung_ap=ctx.ap_net_cent > 0.0))
    lines.extend(_invoice_catalog_lines(import_spec, export_spec))
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
    booked_consumption_by_scenario: dict[str, dict],
) -> list[str]:
    """Write one markdown invoice per result scenario under ``log_dir/invoices/``.

    ``booked_consumption_by_scenario`` (``booked_consumption_by_result``) feeds
    Verbrauch (Info) / Speicher-Standby — same values as SE Gesamtkosten.
    """
    missing = [sid for sid in results if sid not in booked_consumption_by_scenario]
    if missing:
        raise ValueError(
            "Gebuchter Verbrauch fehlt für Rechnungen: " + ", ".join(sorted(missing))
        )
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
            booked_consumption=booked_consumption_by_scenario[scenario_id],
            grid_fee=_grid_fee_from_params(params),
        )
        path = os.path.join(
            invoice_dir, f"{_safe_filename(label)}_jahresrechnung.md"
        )
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(body)
        written.append(path)
    return written
