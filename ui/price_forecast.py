"""UI: Preisprognose vs. Ist vs. Spiegelung (Dev, Phase 3)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from data.price_forecast_model import peak_regression_metrics
from data.price_forecast_viz import (
    DEFAULT_MODEL_PATH,
    build_forecast_evaluation,
    hourly_error_summary,
    list_training_datasets,
    load_model_or_fit,
    split_train_test,
)
from ui.help_hint import render_title_with_help


@st.cache_data(ttl=120, show_spinner="Lade Preis-Dataset …")
def _load_dataset(path_str: str) -> pd.DataFrame:
    from data.price_forecast_model import (
        FEATURE_VARIANT_BASE,
        load_training_dataset,
        resolve_feature_variant,
    )

    path = Path(path_str)
    peek = load_training_dataset(path, feature_variant=FEATURE_VARIANT_BASE)
    if resolve_feature_variant(peek) == FEATURE_VARIANT_BASE:
        return peek
    return load_training_dataset(path)


def _render_sidebar_controls() -> tuple[Path, float, Path | None]:
    st.sidebar.markdown("---")
    st.sidebar.subheader("Preis-Prognose (Dev)")
    datasets = list_training_datasets()
    if not datasets:
        st.sidebar.warning(
            "Kein Dataset in data/cache/. "
            "Zuerst `python -m scripts.build_price_training_dataset` ausführen."
        )
        st.stop()

    labels = [p.name for p in datasets]
    selected_name = st.sidebar.selectbox("Training-Dataset", labels, index=len(labels) - 1)
    dataset_path = next(p for p in datasets if p.name == selected_name)

    train_ratio = st.sidebar.slider(
        "Train-Anteil (chronologisch)",
        min_value=0.5,
        max_value=0.95,
        value=0.8,
        step=0.05,
    )
    use_saved_model = st.sidebar.checkbox(
        "Gespeichertes Modell verwenden",
        value=DEFAULT_MODEL_PATH.exists(),
    )
    model_path = DEFAULT_MODEL_PATH if use_saved_model else None
    if use_saved_model and not DEFAULT_MODEL_PATH.exists():
        st.sidebar.info("Kein Modell unter data/cache/price_model_coefficients.json")
    return dataset_path, train_ratio, model_path


def _metric_columns(model_metrics: dict, mirror_metrics: dict, test: pd.DataFrame) -> None:
    actual = test["actual_cent_kwh"].to_numpy(dtype=float)
    model_peak = peak_regression_metrics(actual, test["model_cent_kwh"].to_numpy(dtype=float))
    mirror_peak = peak_regression_metrics(actual, test["mirror_cent_kwh"].to_numpy(dtype=float))
    cols = st.columns(4)
    cols[0].metric(
        "Modell MAE",
        f"{model_metrics['mae_cent_kwh']:.2f} Cent/kWh",
        delta=f"{mirror_metrics['mae_cent_kwh'] - model_metrics['mae_cent_kwh']:+.2f} vs Spiegel",
        delta_color="normal",
    )
    cols[1].metric("Spiegel MAE", f"{mirror_metrics['mae_cent_kwh']:.2f} Cent/kWh")
    cols[2].metric(
        "Peak-MAE Modell",
        f"{model_peak['mae_cent_kwh']:.2f} Cent/kWh",
        help=f"Obere {model_peak['peak_percentile']:.0f} % der Ist-Preise (≥ {model_peak['peak_threshold_cent_kwh']:.1f} Cent/kWh)",
    )
    cols[3].metric(
        "Peak-MAE Spiegel",
        f"{mirror_peak['mae_cent_kwh']:.2f} Cent/kWh",
    )


def _price_timeseries_chart(test: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    x = test.index
    fig.add_trace(
        go.Scatter(x=x, y=test["actual_cent_kwh"], name="Ist (AT Day-Ahead)", line=dict(color="#1f77b4"))
    )
    fig.add_trace(
        go.Scatter(x=x, y=test["model_cent_kwh"], name="Prognose (OLS)", line=dict(color="#2ca02c"))
    )
    fig.add_trace(
        go.Scatter(x=x, y=test["mirror_cent_kwh"], name="Spiegelung", line=dict(color="#ff7f0e", dash="dot"))
    )
    fig.update_layout(
        title="Holdout: Preis je Stunde",
        xaxis_title="Zeit",
        yaxis_title="EPEX Cent/kWh",
        height=420,
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        margin=dict(t=60, b=40),
    )
    return fig


def _scatter_chart(test: pd.DataFrame) -> go.Figure:
    fig = make_subplots(cols=2, subplot_titles=("Modell vs. Ist", "Spiegel vs. Ist"))
    fig.add_trace(
        go.Scatter(
            x=test["actual_cent_kwh"],
            y=test["model_cent_kwh"],
            mode="markers",
            name="Modell",
            marker=dict(color="#2ca02c", size=6, opacity=0.7),
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=test["actual_cent_kwh"],
            y=test["mirror_cent_kwh"],
            mode="markers",
            name="Spiegel",
            marker=dict(color="#ff7f0e", size=6, opacity=0.7),
        ),
        row=1,
        col=2,
    )
    min_val = float(test["actual_cent_kwh"].min())
    max_val = float(test["actual_cent_kwh"].max())
    for col in (1, 2):
        fig.add_trace(
            go.Scatter(
                x=[min_val, max_val],
                y=[min_val, max_val],
                mode="lines",
                line=dict(color="#888", dash="dash"),
                showlegend=False,
            ),
            row=1,
            col=col,
        )
    fig.update_xaxes(title_text="Ist Cent/kWh")
    fig.update_yaxes(title_text="Prognose Cent/kWh")
    fig.update_layout(height=380, showlegend=False, margin=dict(t=50, b=40))
    return fig


def _hourly_mae_chart(summary: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Bar(x=summary["hour"], y=summary["model_mae"], name="Modell MAE"))
    fig.add_trace(go.Bar(x=summary["hour"], y=summary["mirror_mae"], name="Spiegel MAE"))
    fig.update_layout(
        barmode="group",
        title="Mittlerer absoluter Fehler je Tagesstunde (Holdout)",
        xaxis_title="Stunde",
        yaxis_title="MAE Cent/kWh",
        height=360,
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    return fig


def render_price_forecast_block() -> None:
    dataset_path, train_ratio, model_path = _render_sidebar_controls()
    render_title_with_help(
        "Preis-Prognose (EU-Wetter & Last)",
        (
            "Vergleicht **Ist-Preise** (AT Day-Ahead) mit **OLS-Prognose** "
            "(EU-Wind/Solar/Wetter + optional Last/Residuallast) und **Spiegelung** "
            "auf dem Holdout-Anteil. Spec: docs/spec/price-forecast-renewables.md."
        ),
        key="price_forecast_help",
    )

    try:
        frame = _load_dataset(str(dataset_path.resolve()))
        train, _ = split_train_test(frame, train_ratio=train_ratio)
        model = load_model_or_fit(train, model_path)
        evaluation = build_forecast_evaluation(frame, train_ratio=train_ratio, model=model)
    except (OSError, ValueError) as exc:
        st.error(str(exc))
        return

    st.caption(
        f"Dataset: `{dataset_path.name}` · {len(frame)} h gesamt · "
        f"Holdout: {len(evaluation.test)} h · Modell: {evaluation.model.feature_variant} "
        f"({evaluation.model.training_rows} Trainingszeilen) · "
        f"Bias-Korrektur: {evaluation.model.bias_correction_cent_kwh:+.3f} Cent/kWh "
        f"(Nicht-Peak < P{evaluation.model.bias_correction_peak_percentile:.0f})"
    )
    _metric_columns(evaluation.model_metrics, evaluation.mirror_metrics, evaluation.test)

    st.plotly_chart(_price_timeseries_chart(evaluation.test), use_container_width=True)
    left, right = st.columns(2)
    with left:
        st.plotly_chart(_scatter_chart(evaluation.test), use_container_width=True)
    with right:
        st.plotly_chart(_hourly_mae_chart(hourly_error_summary(evaluation.test)), use_container_width=True)

    with st.expander("Holdout-Tabelle"):
        show = evaluation.test[
            ["actual_cent_kwh", "model_cent_kwh", "mirror_cent_kwh", "model_error", "mirror_error"]
        ].copy()
        show.index = show.index.strftime("%Y-%m-%d %H:%M")
        st.dataframe(show.round(3), use_container_width=True)
