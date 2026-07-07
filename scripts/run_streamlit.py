#!/usr/bin/env python3
"""Startet Streamlit mit Port aus config.json (ui.streamlit_port)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ui.streamlit_server import streamlit_port

_APP_PATH = Path(__file__).resolve().parent.parent / "app.py"


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Streamlit-Cockpit starten (Port: ui.streamlit_port in config.json)"
    )
    parser.add_argument(
        "extra",
        nargs=argparse.REMAINDER,
        help="Zusätzliche streamlit-Argumente nach --",
    )
    return parser.parse_args(argv)


def _streamlit_argv(port: int, extra: list[str]) -> list[str]:
    if extra and extra[0] == "--":
        extra = extra[1:]
    return [
        "streamlit",
        "run",
        str(_APP_PATH),
        "--server.port",
        str(port),
        "--server.address",
        "0.0.0.0",
        *extra,
    ]


def _run_streamlit_cli(argv: list[str]) -> int:
    """Streamlit im aktuellen Prozess starten (kompatibel mit VS-Code-Debugger)."""
    from streamlit.web import cli as stcli

    sys.argv = argv
    try:
        stcli.main()
    except SystemExit as exc:
        code = exc.code
        if code is None:
            return 0
        if isinstance(code, int):
            return code
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    import logger_config

    logger_config.configure_utf8_stdio()

    args = _parse_args(argv)
    port = streamlit_port()
    print(
        f"Streamlit Port {port} (ui.streamlit_port / ENERGY_OPTIMIZER_UI_STREAMLIT_PORT)",
        flush=True,
    )
    return _run_streamlit_cli(_streamlit_argv(port, args.extra))


if __name__ == "__main__":
    raise SystemExit(main())
