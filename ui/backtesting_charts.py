"""Plotly-Charts für die Backtesting-UI."""
from __future__ import annotations

import plotly.graph_objects as go


def scenario_monthly_cost_chart(
    monthly_eur: dict[str, dict[str, float]],
    *,
    scenario_order: list[str] | None = None,
) -> go.Figure:
    """Gruppierter Monats-Kostenvergleich je Szenario (nicht gestapelt)."""
    months = sorted(monthly_eur.keys())
    present = {label for values in monthly_eur.values() for label in values}
    if scenario_order is None:
        scenario_labels = sorted(present)
    else:
        scenario_labels = [label for label in scenario_order if label in present]
        for label in sorted(present):
            if label not in scenario_labels:
                scenario_labels.append(label)
    fig = go.Figure()
    for label in scenario_labels:
        values = [monthly_eur.get(month, {}).get(label, 0.0) for month in months]
        fig.add_bar(name=label, x=months, y=values)
    fig.update_layout(
        barmode="group",
        title="Monatliche Stromkosten je Szenario (€)",
        xaxis_title="Monat",
        yaxis_title="€",
        height=380,
        margin=dict(l=40, r=20, t=50, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    return fig
