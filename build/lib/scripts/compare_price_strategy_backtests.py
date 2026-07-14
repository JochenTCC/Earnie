"""Vergleicht Backtesting-Läufe mit Spiegelung vs. OLS-Prognose in der grünen Zone."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def _load(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _plaus_summary(plausibility: dict) -> str:
    parts = []
    for sid, report in plausibility.items():
        if sid == "historical_reference":
            continue
        total = report.get("total_windows", 0)
        ok = report.get("ok_count", 0)
        parts.append(f"{sid}: {ok}/{total}")
    return "; ".join(parts) if parts else "—"


def _battery_summary(hourly_csv: Path | None, scenario_id: str) -> dict[str, float]:
    if hourly_csv is None or not hourly_csv.is_file():
        return {"charge_kwh": 0.0, "discharge_kwh": 0.0}
    import pandas as pd

    df = pd.read_csv(hourly_csv, sep=";")
    mask = df["scenario_id"] == scenario_id
    batt = pd.to_numeric(df.loc[mask, "batt_action_kw"], errors="coerce").fillna(0.0)
    charge = batt.clip(lower=0.0).sum()
    discharge = (-batt.clip(upper=0.0)).sum()
    return {"charge_kwh": float(charge), "discharge_kwh": float(discharge)}


def build_comparison(
    mirror: dict,
    forecast: dict,
    *,
    mirror_hourly: Path | None = None,
    forecast_hourly: Path | None = None,
) -> str:
    ref_id = mirror.get("reference_id", "historical_reference")
    ref_cost = mirror["summary"]["total_eur"].get(ref_id, 0.0)
    mirror_totals = mirror["summary"]["total_eur"]
    forecast_totals = forecast["summary"]["total_eur"]
    labels = mirror.get("labels", {})

    lines = [
        "# Preisstrategie-Vergleich Backtesting",
        "",
        f"**Referenz** ({labels.get(ref_id, ref_id)}): {ref_cost:.2f} €",
        "",
        "| Szenario | Spiegelung (€) | Prognose (€) | Δ Kosten (€) | Δ Einsparung vs. Ref (€) |",
        "|----------|----------------|--------------|--------------|---------------------------|",
    ]

    for sid, label in labels.items():
        if sid == ref_id:
            continue
        m_cost = mirror_totals.get(sid)
        f_cost = forecast_totals.get(sid)
        if m_cost is None or f_cost is None:
            continue
        m_save = ref_cost - m_cost
        f_save = ref_cost - f_cost
        lines.append(
            f"| {label} | {m_cost:.2f} | {f_cost:.2f} | {f_cost - m_cost:+.2f} | {f_save - m_save:+.2f} |"
        )

    lines.extend(
        [
            "",
            "## Batterie (Summe batt_action_kw aus hourly CSV)",
            "",
            "| Szenario | Laden Spiegel (kWh) | Laden Prognose (kWh) | Entladen Spiegel | Entladen Prognose |",
            "|----------|---------------------|----------------------|------------------|-------------------|",
        ]
    )
    for sid, label in labels.items():
        if sid == ref_id:
            continue
        m_batt = _battery_summary(mirror_hourly, sid)
        f_batt = _battery_summary(forecast_hourly, sid)
        lines.append(
            f"| {label} | {m_batt['charge_kwh']:.1f} | {f_batt['charge_kwh']:.1f} | "
            f"{m_batt['discharge_kwh']:.1f} | {f_batt['discharge_kwh']:.1f} |"
        )

    m_period = mirror.get("period", {})
    f_period = forecast.get("period", {})
    lines.extend(
        [
            "",
            "## Plausibilität",
            "",
            f"- **Spiegelung:** {_plaus_summary(mirror.get('plausibility', {}))}",
            f"- **Prognose:** {_plaus_summary(forecast.get('plausibility', {}))}",
            "",
            "## Metadaten",
            "",
            f"- Spiegelung: `{m_period.get('start')}` – `{m_period.get('last_ts')}` · "
            f"strategy={m_period.get('price_strategy')}",
            f"- Prognose: `{f_period.get('start')}` – `{f_period.get('last_ts')}` · "
            f"strategy={f_period.get('price_strategy')}",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Vergleicht mirror- vs. forecast-Backtesting-Logs."
    )
    parser.add_argument("mirror_json", type=Path)
    parser.add_argument("forecast_json", type=Path)
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument("--mirror-hourly", type=Path, default=None)
    parser.add_argument("--forecast-hourly", type=Path, default=None)
    args = parser.parse_args()

    report = build_comparison(
        _load(args.mirror_json),
        _load(args.forecast_json),
        mirror_hourly=args.mirror_hourly,
        forecast_hourly=args.forecast_hourly,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    print(f"Vergleich geschrieben: {args.output}")


if __name__ == "__main__":
    main()
