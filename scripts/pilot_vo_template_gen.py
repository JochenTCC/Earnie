"""Pilot (spike/vo-push-pilot): generate Loxone Virtual Output templates for the push pilot.

Reads the *read* bindings (``sens_*`` / ``get_*``) of an Earnie config dir and writes
one ``VO_Pilot_*.xml`` per entity group plus ``Pilot-VO-Signalliste.csv``. Every new VO
Cmd pushes its value to ``/ehal/loxone/telemetry/<EHAL-ID>/<v>?t=<token>`` (digital signals: fixed 1 for On, 0 for Off; analog outputs have no Off command) and is
titled ``Push_<old name>`` so it can run in parallel to the existing signal.

Without ``--env-file`` the XML carries the placeholder ``PILOT_TOKEN_HIER_ERSETZEN`` — replace it
with a text editor before copying the files to Loxone. With ``--env-file`` the token
(``EARNIE_PILOT_PUSH_TOKEN``) is written into the XML; keep such output out of the repository.

Usage:
    python -m scripts.pilot_vo_template_gen --config-dir <earnie_env/config> \
        --host 192.168.178.137 --port 8542 --env-file greenfield/config/.env --out-dir <dir>
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

from ehal.push_signals import (  # noqa: F401 — re-exported for callers and tests
    Signal,
    ascii_title,
    heartbeat_signal,
    pilot_id,
    read_signals_from_docs,
)

TOKEN_ENV = "EARNIE_PILOT_PUSH_TOKEN"
TOKEN_PLACEHOLDER = "PILOT_TOKEN_HIER_ERSETZEN"
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{8,}$")

def collect_read_signals(config_dir: Path) -> list[Signal]:
    house = json.loads((config_dir / "house_profiles.json").read_text(encoding="utf-8"))
    components = json.loads((config_dir / "components.json").read_text(encoding="utf-8"))
    return read_signals_from_docs(house, components)


# Shape copied from a template exported by Loxone Config ("Als Vorlage speichern",
# VO_Earnie Plant Telemetry-30s-Replay.xml, 2026-10-07): Info element first, extra Cmd
# attributes (CmdAnswer, Source/DestVal*, HintText), UTF-8 with BOM, tab indent.
INFO_ATTRS = {"templateType": "3", "minVersion": "17010630"}


def _cmd_attrs(sig: Signal, token: str, repeat: str, repeat_rate: str) -> dict[str, str]:
    base = f"/ehal/loxone/telemetry/{sig.ehal_id}/"
    if sig.digital:
        # Digital output: fixed values for On / Off (the value placeholder is for analog outputs).
        on_cmd, off_cmd = f"{base}1?t={token}", f"{base}0?t={token}"
        comment = f"{sig.ehal_id} 0/1; parallel to {sig.old_name}"
    else:
        on_cmd, off_cmd = f"{base}<v>?t={token}", ""
        comment = f"{sig.ehal_id}; parallel to {sig.old_name}"
    attrs = {
        "Title": sig.title,
        "Comment": comment,
        "CmdOnMethod": "GET",
        "CmdOffMethod": "GET",
        "CmdOn": on_cmd,
        "CmdOnHTTP": "",
        "CmdOnPost": "",
        "CmdOff": off_cmd,
        "CmdOffHTTP": "",
        "CmdOffPost": "",
        "CmdAnswer": "",
        "Analog": "false" if sig.digital else "true",
        "Repeat": repeat,
        "RepeatRate": repeat_rate,
    }
    if not sig.digital:
        attrs.update({"SourceValLow": "0", "DestValLow": "0", "SourceValHigh": "0", "DestValHigh": "0"})
    attrs["HintText"] = ""
    return attrs


def render_template(group: str, signals: list[Signal], *, host: str, port: int, token: str,
                    repeat: str = "30", repeat_rate: str = "30") -> str:
    """Template text in the shape Loxone Config exports (without the BOM)."""
    root = ET.Element(
        "VirtualOut",
        {
            "HintText": "",
            "Title": f"Earnie Push Pilot - {group}",
            "Comment": "Pilot push to Earnie (spike/vo-push-pilot); parallel to the poll signals",
            "Address": f"http://{host}:{port}",
            "CmdInit": "",
            "CloseAfterSend": "true",
            "CmdSep": "",
        },
    )
    ET.SubElement(root, "Info", INFO_ATTRS)
    for sig in signals:
        ET.SubElement(root, "VirtualOutCmd", _cmd_attrs(sig, token, repeat, repeat_rate))
    ET.indent(root, space="\t")
    body = ET.tostring(root, encoding="unicode").replace(" />", "/>")
    return '<?xml version="1.0" encoding="utf-8"?>\n' + body + "\n"


def write_template(path: Path, text: str) -> None:
    path.write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))  # BOM like Loxone Config


def read_token(env_file: Path) -> str:
    token = str(dotenv_values(env_file).get(TOKEN_ENV) or "").strip()
    if not _TOKEN_RE.match(token):
        raise ValueError(f"{TOKEN_ENV} missing or not URL-safe (>= 8 chars of A-Z a-z 0-9 _ -) in {env_file}")
    return token


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--config-dir", required=True, type=Path)
    parser.add_argument("--host", required=True, help="IP of the pilot Earnie host (not a hostname)")
    parser.add_argument("--port", type=int, default=8542)
    parser.add_argument("--env-file", type=Path, default=None,
                        help=f"optional .env containing {TOKEN_ENV}; default: write a placeholder")
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--repeat", default="30", help="Repeat attribute (Config export: 30 for a 30 s repeat)")
    parser.add_argument("--repeat-rate", default="30", help="RepeatRate attribute (Config export: 30)")
    args = parser.parse_args()

    token = read_token(args.env_file) if args.env_file else TOKEN_PLACEHOLDER
    signals = collect_read_signals(args.config_dir) + [heartbeat_signal()]
    args.out_dir.mkdir(parents=True, exist_ok=True)
    groups: dict[str, list[Signal]] = {}
    for sig in signals:
        groups.setdefault(sig.group, []).append(sig)
    for group, items in groups.items():
        path = args.out_dir / f"VO_Pilot_{group}.xml"
        write_template(path, render_template(group, items, host=args.host, port=args.port, token=token,
                                             repeat=args.repeat, repeat_rate=args.repeat_rate))
        print(f"{path.name}: {len(items)} Cmds")
    with open(args.out_dir / "Pilot-VO-Signalliste.csv", "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(["Datei", "VO-Cmd-Titel", "EHAL-ID", "Bisheriger Name (Poll)", "Typ"])
        for group, items in groups.items():
            for sig in items:
                writer.writerow([f"VO_Pilot_{group}.xml", sig.title, sig.ehal_id, sig.old_name,
                                 "digital" if sig.digital else "analog"])
    print(f"{len(signals)} signals in {len(groups)} files -> {args.out_dir}")
    if token == TOKEN_PLACEHOLDER:
        print(f"Token placeholder in the XML: replace {TOKEN_PLACEHOLDER} with your token before use.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
