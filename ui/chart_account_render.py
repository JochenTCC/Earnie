"""Chart 2 as an account view: Streamlit and Plotly (spec ``docs/dev/chart2-account-view.md``).

The money panel shows two balances from 0 € at the window start, the gap between them
coloured green (saved) or red (more spent), and labels without a sign. The panel below
checks that both sides were costed with the same consumption. The Monitor offers the
anchor switch; the Scenario Explorer window has no *Jetzt*, so both modes coincide
there and the switch is not shown.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from data.planning_window import UiChartWindow
from runtime_store.history_timeline import SLOT_MISSING
from ui.chart_account_view import (
    ANCHOR_NOW,
    ANCHOR_START,
    SLOT_PLAN,
    SLOT_STATES_MARKED,
    AccountSlots,
    AccountView,
    build_account_view,
    gap_runs,
)
from ui.chart_baseline_label import baseline_label
from ui.chart_colors import (
    CHART_MISSING_SLOT_FILL,
    COLOR_COST_BASELINE,
    COLOR_COST_OPTIMIZED,
    COLOR_COST_SAVINGS,
    COLOR_COST_SAVINGS_FILL,
    COLOR_COST_SAVINGS_NEGATIVE,
    COLOR_COST_SAVINGS_NEGATIVE_FILL,
)
from ui.chart_decorations import (
    _add_sun_markers,
    _add_zone_backgrounds,
    _chart_range_start,
    _collapsible_chart_layout,
)
from ui.chart_legend_mobile import (
    inject_mobile_legend_css,
    render_collapsible_legend_from_figure,
)
from ui.chart_slot_axis import ChartSlotAxis, _chart_xaxis_config
from ui.help_hint import render_title_with_help
from ui.number_format import format_decimal, localized_figure
from ui.saving_text import saving_is_loss, saving_text, soc_correction_text


CHART2_TITLE = "Kontostand: mit und ohne Earnie"
SESSION_ANCHOR_MODE = "chart2_anchor_mode"
ANCHOR_LABELS = {ANCHOR_NOW: "Ist bei Jetzt", ANCHOR_START: "Gemeinsamer Start"}

CHART2_HELP = (
    "Die Linien zeigen den **Kontostand seit Fensterstart**: Stromkosten und "
    "Einspeiseerlöse zu den Preisen des Ersparnis-Buchs, ohne Grund- und Netzgebühren. "
    "Fällt die Linie, wird bezahlt. **Links von Jetzt** stehen die gebuchten Kosten "
    "aus dem Ersparnis-Buch: mit Earnie und ohne Earnie (Batterie im Herstellermodus, "
    "gleicher Verbrauch, gleiche PV, gleiche Preise). **Rechts von Jetzt** steht der Plan: "
    "optimiert und BL Ziel, das ab dem aktuellen Speicherstand rechnet. Die Vergleichslinie "
    "ändert bei Jetzt also ihre Bedeutung. **Ist bei Jetzt** verschiebt sie so, dass sich "
    "beide Linien bei Jetzt treffen: Der Abstand am Fensterstart ist das bisher Gesparte, "
    "der Abstand am Fensterende das Erwartete. **Gemeinsamer Start** lässt beide bei 0 € "
    "beginnen: Der Abstand bei Jetzt ist das bisher Gesparte, am Ende das Gesamte. Grün "
    "heißt gespart, rot mehr ausgegeben; Beträge stehen ohne Vorzeichen. Die "
    "**SoC-Korrektur** (Speicherstand gegenüber der Vergleichsbatterie, bewertet) steckt "
    "in keinem Abstand und steht als eigenes Label. Orange Slots hat das Buch nicht "
    "gezählt (fehlende Messwerte oder Buch nicht gelaufen), sie zählen auf beiden Seiten "
    "null. Die gerade laufende Viertelstunde erscheint, sobald sie gebucht ist. Das untere "
    "Panel prüft den Verbrauch: Vergleich minus optimiert in kWh, null am Horizontende. "
    "Links von Jetzt ist es flach, weil beide Seiten denselben gemessenen Verbrauch "
    "nutzen."
)
SE_CHART2_HELP = (
    "Die Linien zeigen den **Kontostand seit Fensterstart**: gebuchte Stromkosten und "
    "Einspeiseerlöse beider Läufe, ohne Grund- und Netzgebühren. Fällt die Linie, wird "
    "bezahlt. Beide beginnen bei 0 €; der Abstand am Fensterende ist die Ersparnis des "
    "Fensters, grün gespart, rot mehr ausgegeben. Das untere Panel prüft den Verbrauch: "
    "Vergleich minus optimiert in kWh, null am Fensterende."
)

_LABEL_FONT = dict(size=13)


def _series(view: dict, key: str, count: int) -> list[float]:
    values = view.get(key)
    if values is None or len(values) != count:
        raise ValueError(
            f"Chart 2: {key} has {0 if values is None else len(values)} slots, the window {count}"
        )
    return [float(value) for value in values]


def account_slots(savings_view: dict, *, history_slot_count: int, slot_count: int) -> AccountSlots:
    """Ledger slots left of *Jetzt*, plan slots right of it (spec § 4)."""
    anchor = max(0, min(int(history_slot_count or 0), slot_count))
    plan_with = _series(savings_view, "hourly_optimized_cost_euro", slot_count)
    plan_without = _series(savings_view, "hourly_matched_baseline_cost_euro", slot_count)
    plan_base_kwh = _series(savings_view, "hourly_matched_baseline_consumption_kwh", slot_count)
    plan_opt_kwh = _series(savings_view, "hourly_optimized_consumption_kwh", slot_count)
    states = [SLOT_PLAN] * slot_count
    with_eur = list(plan_with)
    without_eur = list(plan_without)
    base_kwh = list(plan_base_kwh)
    opt_kwh = list(plan_opt_kwh)
    if anchor:
        ledger = savings_view.get("ledger_savings")
        if not ledger:
            raise ValueError("Chart 2: slots left of Jetzt need the ledger figures")
        ledger_with = _series(ledger, "slot_with_eur", slot_count)
        ledger_without = _series(ledger, "slot_without_eur", slot_count)
        ledger_states = list(ledger["slot_states"])
        for index in range(anchor):
            with_eur[index] = ledger_with[index]
            without_eur[index] = ledger_without[index]
            states[index] = ledger_states[index]
            # Both sides use the logged load left of Jetzt (savings_v 1), so the control is flat.
            base_kwh[index] = 0.0
            opt_kwh[index] = 0.0
    return AccountSlots(
        with_eur=tuple(with_eur),
        without_eur=tuple(without_eur),
        baseline_kwh=tuple(base_kwh),
        optimized_kwh=tuple(opt_kwh),
        states=tuple(states),
        anchor=anchor,
        baseline_after_window_kwh=float(
            savings_view.get("hourly_matched_baseline_consumption_after_window_kwh") or 0.0
        ),
        optimized_after_window_kwh=float(
            savings_view.get("hourly_optimized_consumption_after_window_kwh") or 0.0
        ),
    )


def _boundary_times(axis: ChartSlotAxis) -> list[datetime]:
    starts = [pd.Timestamp(value).to_pydatetime() for value in axis.starts]
    last = len(starts) - 1
    return starts + [starts[last] + axis.slot_duration(last)]


def _time_at(times: list[datetime], position: float) -> datetime:
    index = int(position)
    if index >= len(times) - 1:
        return times[-1]
    fraction = position - index
    return times[index] + (times[index + 1] - times[index]) * fraction


def saving_color(euro: float) -> str:
    """By the shown cents, so 0,00 € is neither green nor red."""
    cents = round(euro, 2)
    if cents > 0:
        return COLOR_COST_SAVINGS
    if saving_is_loss(euro):
        return COLOR_COST_SAVINGS_NEGATIVE
    return COLOR_COST_BASELINE


def _add_gap_fills(fig: go.Figure, view: AccountView, times: list[datetime]) -> None:
    for run in gap_runs(view):
        x = [_time_at(times, p) for p in run.positions]
        color = COLOR_COST_SAVINGS_FILL if run.saving else COLOR_COST_SAVINGS_NEGATIVE_FILL
        fig.add_trace(
            go.Scatter(
                x=x + x[::-1],
                y=list(run.optimized) + list(run.baseline)[::-1],
                fill="toself",
                fillcolor=color,
                line=dict(width=0),
                mode="lines",
                hoverinfo="skip",
                showlegend=False,
            ),
            row=1,
            col=1,
        )


def _line_trace(
    fig: go.Figure,
    times: list[datetime],
    values: tuple[float, ...],
    lo: int,
    hi: int,
    *,
    name: str,
    color: str,
    dash: str | None = None,
) -> None:
    if hi <= lo:
        return
    fig.add_trace(
        go.Scatter(
            x=times[lo : hi + 1],
            y=list(values[lo : hi + 1]),
            mode="lines",
            name=name,
            line=dict(color=color, width=2.5, dash=dash),
            hovertemplate=f"{name}: %{{y:.2f}} €<extra></extra>",
        ),
        row=1,
        col=1,
    )


def _add_balance_lines(
    fig: go.Figure, view: AccountView, times: list[datetime], *, ledger_names: bool
) -> None:
    n = view.slot_count
    past_with = "Mit Earnie (gebucht)" if ledger_names else "Optimiert"
    past_without = "Ohne Earnie (gebucht)" if ledger_names else baseline_label()
    _line_trace(fig, times, view.optimized, 0, view.anchor, name=past_with, color=COLOR_COST_OPTIMIZED)
    _line_trace(fig, times, view.baseline, 0, view.anchor, name=past_without, color=COLOR_COST_BASELINE)
    _line_trace(
        fig, times, view.optimized, view.anchor, n, name="Optimiert (Plan)", color=COLOR_COST_OPTIMIZED,
        dash="dash" if ledger_names else None,
    )
    _line_trace(
        fig, times, view.baseline, view.anchor, n, name=f"{baseline_label()} (Plan)",
        color=COLOR_COST_BASELINE, dash="dash" if ledger_names else None,
    )


def _gap_label(
    fig: go.Figure, times: list[datetime], view: AccountView, k: int, text: str, euro: float,
    *, xanchor: str,
) -> None:
    fig.add_annotation(
        x=times[k],
        y=(view.optimized[k] + view.baseline[k]) / 2,
        text=text,
        showarrow=False,
        xanchor=xanchor,
        font=dict(**_LABEL_FONT, color=saving_color(euro)),
        bgcolor="rgba(255,255,255,0.75)",
        row=1,
        col=1,
    )


def _add_gap_labels(
    fig: go.Figure, view: AccountView, times: list[datetime], *, so_far_name: str = "Bisher"
) -> None:
    n = view.slot_count
    if not view.has_past:
        _gap_label(fig, times, view, n, f"Plan: {saving_text(view.saving_after_eur)}",
                   view.saving_after_eur, xanchor="right")
        return
    so_far = f"{so_far_name}: {saving_text(view.saving_so_far_eur)}"
    if view.mode == ANCHOR_NOW:
        _gap_label(fig, times, view, 0, so_far, view.saving_so_far_eur, xanchor="left")
        if view.has_future:
            _gap_label(fig, times, view, n, f"Erwartet: {saving_text(view.saving_after_eur)}",
                       view.saving_after_eur, xanchor="right")
        return
    _gap_label(fig, times, view, view.anchor, so_far, view.saving_so_far_eur, xanchor="right")
    if view.has_future:
        _gap_label(fig, times, view, n, f"Gesamt: {saving_text(view.saving_total_eur)}",
                   view.saving_total_eur, xanchor="right")


def _add_ledger_labels(
    fig: go.Figure,
    ledger: dict | None,
    times: list[datetime],
    view: AccountView,
    *,
    period: bool = False,
) -> None:
    """Closed days keep their ledger result; the open day's SoC correction is its own label.

    A ``period`` of several weeks has no room for a label per day: it marks only the
    incomplete days and leaves the SoC corrections to the caption under the chart.
    """
    if not ledger:
        return
    start, end = times[0], times[-1]
    for day in ledger.get("closed_days") or []:
        day_start = max(datetime.fromisoformat(day["day_start"]), start)
        day_end = min(datetime.fromisoformat(day["day_end"]), end)
        if day_end <= day_start:
            continue
        if period:
            if day["incomplete"]:
                fig.add_annotation(
                    x=day_start + (day_end - day_start) / 2, y=1.0, xref="x", yref="paper",
                    yanchor="top", text="unvollständig", showarrow=False, textangle=-90,
                    font=dict(size=10, color=COLOR_COST_BASELINE),
                )
            continue
        text = f"Ergebnis: {saving_text(day['saving_adjusted_eur'])}"
        if day["incomplete"]:
            text += " · unvollständig"
        fig.add_annotation(
            x=day_start + (day_end - day_start) / 2, y=1.0, xref="x", yref="paper",
            yanchor="top", text=text, showarrow=False,
            font=dict(**_LABEL_FONT, color=saving_color(day["saving_adjusted_eur"])),
        )
    correction = ledger.get("soc_correction_euro")
    open_start = ledger.get("open_day_start")
    if period or correction is None or open_start is None or not view.has_past:
        return
    if not (datetime.fromisoformat(open_start) < end and datetime.fromisoformat(ledger["open_day_end"]) > start):
        return
    fig.add_annotation(
        x=times[view.anchor], y=0.93, xref="x", yref="paper", yanchor="top",
        xanchor="left" if view.has_future else "right",
        text=f"SoC: {soc_correction_text(correction)}", showarrow=False,
        font=dict(**_LABEL_FONT, color=saving_color(correction)),
    )


def _marked_runs(slots: AccountSlots, slot_qualities: tuple[str, ...] | None) -> list[tuple[int, int]]:
    """Runs ``[first, last]`` of slots shown orange; one shape per run keeps long windows light."""
    qualities = slot_qualities if slot_qualities and len(slot_qualities) == len(slots.states) else None
    runs: list[tuple[int, int]] = []
    for index, state in enumerate(slots.states):
        missing_log = qualities is not None and qualities[index] == SLOT_MISSING
        if state not in SLOT_STATES_MARKED and not missing_log:
            continue
        if runs and runs[-1][1] == index - 1:
            runs[-1] = (runs[-1][0], index)
        else:
            runs.append((index, index))
    return runs


def _add_marked_slots(
    fig: go.Figure, axis: ChartSlotAxis, slots: AccountSlots, slot_qualities: tuple[str, ...] | None
) -> None:
    for first, last in _marked_runs(slots, slot_qualities):
        fig.add_vrect(
            x0=axis.legacy_index_time(first - 0.5),
            x1=axis.legacy_index_time(last + 0.5),
            fillcolor=CHART_MISSING_SLOT_FILL,
            line_width=0,
            layer="below",
        )


def _add_consumption_panel(fig: go.Figure, view: AccountView, times: list[datetime]) -> None:
    name = f"Verbrauch {baseline_label()} − optimiert"
    fig.add_trace(
        go.Scatter(
            x=times,
            y=list(view.consumption_gap_kwh),
            mode="lines",
            name=name,
            line=dict(color=COLOR_COST_BASELINE, width=1.5, shape="linear"),
            hovertemplate=f"{name}: %{{y:.2f}} kWh<extra></extra>",
        ),
        row=2,
        col=1,
    )
    fig.add_hline(y=0, line=dict(color="rgba(128,128,128,0.6)", width=1), row=2, col=1)


def _add_saving_panel(fig: go.Figure, view: AccountView, times: list[datetime]) -> None:
    """Saving since the window start alone, on its own scale (spec § 6 item 1, decided P3)."""
    # Balances: the optimized line above the baseline means saved.
    cumulative = [opt - base for opt, base in zip(view.optimized, _start_baseline(view))]
    for sign, color in ((1, COLOR_COST_SAVINGS_FILL), (-1, COLOR_COST_SAVINGS_NEGATIVE_FILL)):
        fig.add_trace(
            go.Scatter(
                x=times,
                y=[max(sign * value, 0.0) * sign for value in cumulative],
                mode="lines",
                line=dict(width=0),
                fill="tozeroy",
                fillcolor=color,
                hoverinfo="skip",
                showlegend=False,
            ),
            row=2,
            col=1,
        )
    name = "Ersparnis seit Fensterstart"
    fig.add_trace(
        go.Scatter(
            x=times,
            y=cumulative,
            mode="lines",
            name=name,
            line=dict(color=COLOR_COST_BASELINE, width=1.5),
            hovertemplate=f"{name}: %{{y:.2f}} €<extra></extra>",
        ),
        row=2,
        col=1,
    )
    fig.add_hline(y=0, line=dict(color="rgba(128,128,128,0.6)", width=1), row=2, col=1)


def _start_baseline(view: AccountView) -> list[float]:
    """The baseline as in "Gemeinsamer Start", whatever the chosen mode."""
    shift = view.baseline[0] - view.optimized[0]
    return [value - shift for value in view.baseline]


def energy_difference_hint(view: AccountView) -> str | None:
    """Spec § 6 item 5: the plan compares unequal energies, so "erwartet" holds their price."""
    if not view.flag_energy_difference:
        return None
    diff = view.plan_energy_diff_kwh
    word = "mehr" if diff > 0 else "weniger"
    figure = "Erwartet" if view.has_past else "Plan"
    return (
        f"Der Plan rechnet für {baseline_label()} mit {format_decimal(abs(diff), 1)} kWh {word} Verbrauch als "
        f"für die Optimierung. „{figure}“ enthält deshalb auch den Preis dieser Energie."
    )


def build_account_figure(
    df: pd.DataFrame,
    slots: AccountSlots,
    view: AccountView,
    *,
    ledger: dict | None,
    chart_window: UiChartWindow | None,
    chart_zones=None,
    slot_qualities: tuple[str, ...] | None = None,
    sun_markers=None,
    period: bool = False,
) -> go.Figure:
    """``period``: the analysis page's 7 / 28 days, with the saving panel below (spec § 6, P3)."""
    axis = ChartSlotAxis.from_dataframe(df)
    times = _boundary_times(axis)
    range_start = _chart_range_start(chart_window)
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, row_heights=[0.74, 0.26], vertical_spacing=0.06
    )
    # Traces first: Plotly leaves shapes out of subplots that are still empty.
    _add_gap_fills(fig, view, times)
    _add_balance_lines(fig, view, times, ledger_names=view.has_past)
    if period:
        _add_saving_panel(fig, view, times)
    else:
        _add_consumption_panel(fig, view, times)
    if chart_zones is not None:
        _add_zone_backgrounds(fig, chart_zones, axis, range_start=range_start)
    _add_marked_slots(fig, axis, slots, slot_qualities)
    if sun_markers is not None:
        _add_sun_markers(fig, sun_markers)
    _add_gap_labels(fig, view, times, so_far_name="Zeitraum" if period else "Bisher")
    _add_ledger_labels(fig, ledger, times, view, period=period)
    xaxis = _chart_xaxis_config(axis, range_start=range_start)
    if period:
        span_days = (times[-1] - times[0]).total_seconds() / 86400
        xaxis.update(
            title="Datum",
            # Plotly writes weekday names in English, so the date alone.
            tickformat="%d.%m.",
            dtick=86_400_000 * (1 if span_days <= 8 else 7),
        )
    fig.update_xaxes(**{key: value for key, value in xaxis.items() if key != "title"})
    fig.update_xaxes(title=xaxis["title"], row=2, col=1)
    fig.update_yaxes(title="Kontostand seit Fensterstart (€)", zeroline=True, row=1, col=1)
    fig.update_yaxes(title="€" if period else "kWh", row=2, col=1)
    fig.update_layout(
        height=520,
        **_collapsible_chart_layout(top_margin=30),
    )
    return fig


def _anchor_mode(view_has_past: bool, key_prefix: str) -> str:
    if not view_has_past:
        return ANCHOR_START
    key = f"{key_prefix}{SESSION_ANCHOR_MODE}"
    if st.session_state.get(key) not in ANCHOR_LABELS:
        st.session_state[key] = ANCHOR_NOW
    return st.radio(
        "Verankerung",
        options=list(ANCHOR_LABELS),
        format_func=ANCHOR_LABELS.__getitem__,
        key=key,
        horizontal=True,
        label_visibility="collapsed",
    )


def render_account_chart(
    df: pd.DataFrame,
    savings_view: dict,
    *,
    history_slot_count: int,
    chart_window: UiChartWindow | None,
    chart_zones=None,
    slot_qualities: tuple[str, ...] | None = None,
    sun_markers=None,
    chart_key: str | None = None,
    key_prefix: str = "",
) -> None:
    """Chart 2: money panel with the anchor switch, consumption control below (spec §§ 3–5)."""
    slots = account_slots(savings_view, history_slot_count=history_slot_count, slot_count=len(df))
    ledger_view = slots.anchor > 0
    render_title_with_help(
        CHART2_TITLE,
        # Only the Monitor has a ledger; the Scenario Explorer window compares two runs.
        CHART2_HELP if "ledger_savings" in savings_view else SE_CHART2_HELP,
        key=f"{key_prefix}chart2_help",
    )
    mode = _anchor_mode(ledger_view, key_prefix)
    view = build_account_view(slots, mode)
    ledger = savings_view.get("ledger_savings")
    fig = build_account_figure(
        df, slots, view, ledger=ledger, chart_window=chart_window, chart_zones=chart_zones,
        slot_qualities=slot_qualities, sun_markers=sun_markers,
    )
    inject_mobile_legend_css()
    kwargs: dict = {"width": "stretch"}
    if chart_key:
        kwargs["key"] = chart_key
    st.plotly_chart(localized_figure(fig), **kwargs)
    render_collapsible_legend_from_figure(fig)
    hint = energy_difference_hint(view)
    if hint:
        st.caption(hint)
    if ledger and ledger.get("hint"):
        st.caption(ledger["hint"])


PERIOD_TITLE = "Kontostand: mit und ohne Earnie"
PERIOD_HELP = (
    "Kontostand seit Fensterstart aus dem Ersparnis-Buch: gebuchte Stromkosten und "
    "Einspeiseerlöse mit Earnie und ohne Earnie (Batterie im Herstellermodus, gleicher "
    "Verbrauch, gleiche PV, gleiche Preise), ohne Grund- und Netzgebühren. Fällt die Linie, "
    "wird bezahlt. **Ist bei Jetzt** lässt beide Linien am Fensterende enden, der Abstand am "
    "Fensterstart ist die Ersparnis des Zeitraums; **Gemeinsamer Start** lässt beide bei 0 € "
    "beginnen. Das Panel darunter zeigt die Ersparnis seit Fensterstart allein, auf eigener "
    "Skala: grün gespart, rot mehr ausgegeben. Die SoC-Korrekturen der abgeschlossenen Tage "
    "stecken in keinem Abstand, die Zeile unter dem Chart nennt ihre Summe. Orange Slots hat "
    "das Buch nicht gezählt, sie zählen auf beiden Seiten null; unvollständige Tage sind "
    "markiert."
)
SESSION_PERIOD_PREFIX = "analysis_"


def period_soc_correction_eur(ledger: dict, window_start: datetime, window_end: datetime) -> tuple[float, int]:
    """SoC corrections of the closed days that lie fully in the window, and their count."""
    total = 0.0
    count = 0
    for day in ledger.get("closed_days") or []:
        if (
            datetime.fromisoformat(day["day_start"]) >= window_start
            and datetime.fromisoformat(day["day_end"]) <= window_end
        ):
            total += float(day["saving_adjusted_eur"]) - float(day["saving_eur"])
            count += 1
    return total, count


def period_account_slots(ledger: dict) -> AccountSlots:
    """A past window: every slot from the ledger, anchored at its end; no energy control."""
    count = len(ledger["slot_states"])
    return AccountSlots(
        with_eur=tuple(float(value) for value in ledger["slot_with_eur"]),
        without_eur=tuple(float(value) for value in ledger["slot_without_eur"]),
        baseline_kwh=(0.0,) * count,
        optimized_kwh=(0.0,) * count,
        states=tuple(ledger["slot_states"]),
        anchor=count,
    )


def render_period_account_chart(window_start: datetime, window_end: datetime) -> None:
    """Account view of a 7 / 28-day window on the analysis page (Account view P3)."""
    from runtime_store.history_timeline import quarter_hour_slots_between
    from ui.chart_ledger_savings import load_ledger_chart_savings

    render_title_with_help(PERIOD_TITLE, PERIOD_HELP, key=f"{SESSION_PERIOD_PREFIX}chart2_help")
    # The window's end is the start of its last log slot, which belongs to it.
    end_exclusive = window_end + timedelta(minutes=15)
    slot_starts = list(quarter_hour_slots_between(window_start, end_exclusive))
    if not slot_starts:
        st.info("Keine Viertelstunden in diesem Zeitraum.")
        return
    ledger = load_ledger_chart_savings(
        slot_starts, len(slot_starts), window_start=window_start, window_end=end_exclusive
    )
    slots = period_account_slots(ledger)
    mode = _anchor_mode(True, SESSION_PERIOD_PREFIX)
    view = build_account_view(slots, mode)
    df = pd.DataFrame({"slot_datetime": slot_starts})
    fig = build_account_figure(df, slots, view, ledger=ledger, chart_window=None, period=True)
    inject_mobile_legend_css()
    st.plotly_chart(localized_figure(fig), width="stretch", key=f"{SESSION_PERIOD_PREFIX}account_chart")
    render_collapsible_legend_from_figure(fig)
    correction, days = period_soc_correction_eur(ledger, window_start, end_exclusive)
    if days:
        st.caption(
            f"SoC-Korrekturen der {days} abgeschlossenen Tage im Zeitraum, nicht im Abstand "
            f"enthalten: {soc_correction_text(correction)}."
        )
    if ledger.get("hint"):
        st.caption(ledger["hint"])


__all__ = [
    "PERIOD_HELP",
    "PERIOD_TITLE",
    "period_account_slots",
    "period_soc_correction_eur",
    "render_period_account_chart",
    "ANCHOR_LABELS",
    "CHART2_HELP",
    "CHART2_TITLE",
    "SESSION_ANCHOR_MODE",
    "account_slots",
    "build_account_figure",
    "energy_difference_hint",
    "render_account_chart",
    "saving_color",
]
