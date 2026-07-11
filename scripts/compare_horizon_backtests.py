"""Vergleicht zwei backtesting_log.json-Läufe (fixed_24h vs sunrise_window)."""
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


def build_comparison(fixed: dict, sunset: dict) -> str:
    ref_id = fixed.get("reference_id", "historical_reference")
    ref_cost = fixed["summary"]["total_eur"].get(ref_id, 0.0)
    fixed_totals = fixed["summary"]["total_eur"]
    sunset_totals = sunset["summary"]["total_eur"]
    labels = fixed.get("labels", {})

    lines = [
        "# Horizont-Vergleich Backtesting 2025",
        "",
        f"**Referenz** ({labels.get(ref_id, ref_id)}): {ref_cost:.2f} €",
        "",
        f"| Szenario | fixed_24h (€) | sunrise_window (€) | Δ Kosten (€) | Δ Einsparung vs. Ref (€) |",
        f"|----------|---------------|---------------------|--------------|---------------------------|",
    ]

    for sid, label in labels.items():
        if sid == ref_id:
            continue
        f_cost = fixed_totals.get(sid)
        s_cost = sunset_totals.get(sid)
        if f_cost is None or s_cost is None:
            continue
        f_save = ref_cost - f_cost
        s_save = ref_cost - s_cost
        lines.append(
            f"| {label} | {f_cost:.2f} | {s_cost:.2f} | {s_cost - f_cost:+.2f} | {s_save - f_save:+.2f} |"
        )

    lines.extend(
        [
            "",
            "## Plausibilität",
            "",
            f"- **fixed_24h:** {_plaus_summary(fixed.get('plausibility', {}))}",
            f"- **sunrise_window:** {_plaus_summary(sunset.get('plausibility', {}))}",
            "",
            "## Metadaten",
            "",
            f"- Fenster: {fixed['period'].get('windows')} · Stunden: {fixed['period'].get('hours')}",
            f"- fixed_24h: `{fixed['period'].get('start')}` – `{fixed['period'].get('last_ts')}`",
            f"- sunrise_window: `{sunset['period'].get('start')}` – `{sunset['period'].get('last_ts')}`",
        ]
    )
    crit_f = fixed.get("critical_cases_summary", {}).get("total", 0)
    crit_s = sunset.get("critical_cases_summary", {}).get("total", 0)
    lines.append(f"- Kritische Fälle: fixed {crit_f}, sunset {crit_s}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Vergleicht zwei Backtesting-JSON-Logs.")
    parser.add_argument("fixed_json", type=Path)
    parser.add_argument("sunset_json", type=Path)
    parser.add_argument("-o", "--output", type=Path, required=True)
    args = parser.parse_args()

    report = build_comparison(_load(args.fixed_json), _load(args.sunset_json))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    print(f"Vergleich geschrieben: {args.output}")


if __name__ == "__main__":
    main()
