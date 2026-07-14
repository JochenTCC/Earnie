"""diag_single_window aus der SE-Detaillansicht (CLI + optionaler Subprocess-Lauf)."""
from __future__ import annotations

import subprocess
from datetime import datetime
from shlex import join as shlex_join

import pandas as pd
import streamlit as st

from ui.backtesting_runner import _subprocess_env, project_root, python_executable


def _period_month_bounds(meta: dict, anchor: datetime) -> tuple[int, int]:
    period = meta.get("period") or {}
    start_month = period.get("start_month")
    end_month = period.get("end_month")
    if start_month is not None and end_month is not None:
        return int(start_month), int(end_month)
    month = anchor.month
    return month, month


def build_diag_single_window_argv(
    window_anchor: str,
    scenario_id: str,
    meta: dict,
    *,
    initial_soc: float | None = None,
) -> list[str]:
    anchor_dt = pd.Timestamp(window_anchor).to_pydatetime()
    start_month, end_month = _period_month_bounds(meta, anchor_dt)
    argv = [
        python_executable(),
        str(project_root() / "scripts" / "diag_single_window.py"),
        "--anchor",
        anchor_dt.strftime("%Y-%m-%d %H:%M:%S"),
        "--scenario",
        scenario_id,
        "--start-month",
        str(start_month),
        "--end-month",
        str(end_month),
    ]
    if initial_soc is not None:
        argv.extend(["--initial-soc", str(round(float(initial_soc), 2))])
    return argv


def format_diag_single_window_command(argv: list[str]) -> str:
    return shlex_join(argv)


def run_diag_single_window(
    argv: list[str],
    *,
    timeout_sec: int = 180,
) -> tuple[int, str]:
    proc = subprocess.run(
        argv,
        cwd=str(project_root()),
        env=_subprocess_env(),
        capture_output=True,
        text=True,
        timeout=timeout_sec,
        check=False,
    )
    output = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, output.strip()


def render_diag_single_window_panel(
    window_anchor: str,
    scenario_id: str,
    meta: dict,
    hourly_df: pd.DataFrame,
) -> None:
    from simulation.backtesting_single_window import initial_soc_for_anchor

    anchor_dt = pd.Timestamp(window_anchor).to_pydatetime()
    initial_soc = initial_soc_for_anchor(anchor_dt, scenario_id, hourly_df)
    argv = build_diag_single_window_argv(
        window_anchor,
        scenario_id,
        meta,
        initial_soc=initial_soc,
    )
    command = format_diag_single_window_command(argv)

    with st.expander("Fenster-Diagnose (diag_single_window)"):
        st.caption(
            f"Einzelnes 24h-Fenster wie in der CLI — Start-SOC {initial_soc:.1f} % "
            "aus backtesting_hourly.csv."
        )
        st.code(command, language="powershell")
        if st.button(
            "Diagnose ausführen",
            key=f"diag_single_window_{window_anchor}_{scenario_id}",
        ):
            with st.spinner("diag_single_window läuft…"):
                exit_code, output = run_diag_single_window(argv)
            if exit_code == 0:
                st.success("Diagnose abgeschlossen.")
            else:
                st.error(f"Diagnose beendet mit Exit-Code {exit_code}.")
            if output:
                st.text(output)
