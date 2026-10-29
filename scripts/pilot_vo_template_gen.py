"""Generate Loxone Virtual Output templates for Earnie push telemetry.

Reads the *read* bindings (``sens_*`` / ``get_*``) of an Earnie config dir and writes
one ``VO_Earnie_*.xml`` per entity group plus ``Earnie-VO-Signalliste.csv``. Every new VO
Cmd pushes its value to ``/ehal/telemetry/<EHAL-ID>/<v>?t=<token>`` (digital signals: fixed 1 for On, 0 for Off; analog outputs have no Off command) and is
titled ``Push_<qualified-id>`` (dots → ``_``) so it can run in parallel to Merker Cmds.

Without ``--env-file`` the XML carries the placeholder ``PUSH_TOKEN_HIER_ERSETZEN`` — replace it
with a text editor before copying the files to Loxone, or omit the ``?t=`` query if no token
is needed. With ``--env-file`` the token (``EARNIE_PUSH_TOKEN``) is written into the XML;
keep such output out of the repository.

With ``--grid-phases`` (dev, device detection) it writes only ``VO_Earnie_Netz_Phasen.xml``
for the grid meter per-phase values of ``ehal.grid_phase_fields``; no config dir is needed
because these fields are not bindings. Earnie logs them only with ``EARNIE_UI_MODES``
containing ``device_detection``.

Usage:
    python -m scripts.pilot_vo_template_gen --config-dir <earnie_env/config> \
        --host 192.168.178.137 --port 8542 --env-file greenfield/config/.env --out-dir <dir>
    python -m scripts.pilot_vo_template_gen --grid-phases --host 192.168.178.137 --out-dir <dir>
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

from ehal.grid_phase_fields import GRID_PHASE_KINDS
from ehal.qualified_ids import qualified_grid_id
from ehal.push_signals import (  # noqa: F401 — re-exported for callers and tests
    REQUEST_OPTIMIZE_TITLE,
    Signal,
    heartbeat_signal,
    pilot_id,
    read_signals_from_docs,
    title_from_qualified_id,
)
from integrations.ehal_request_http import REQUEST_OPTIMIZE_PATH

TOKEN_ENV = "EARNIE_PUSH_TOKEN"
TOKEN_ENV_LEGACY = "EARNIE_PILOT_PUSH_TOKEN"
TOKEN_PLACEHOLDER = "PUSH_TOKEN_HIER_ERSETZEN"
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{8,}$")

def collect_read_signals(config_dir: Path) -> list[Signal]:
    house = json.loads((config_dir / "house_profiles.json").read_text(encoding="utf-8"))
    components = json.loads((config_dir / "components.json").read_text(encoding="utf-8"))
    return read_signals_from_docs(house, components)


GRID_PHASE_GROUP = "Netz_Phasen"
_GRID_PHASE_LABELS = {
    "sens_grid_voltage_l1": "Spannung L1 [V]",
    "sens_grid_voltage_l2": "Spannung L2 [V]",
    "sens_grid_voltage_l3": "Spannung L3 [V]",
    "sens_grid_current_l1": "Strom L1 [A]",
    "sens_grid_current_l2": "Strom L2 [A]",
    "sens_grid_current_l3": "Strom L3 [A]",
    "sens_grid_power_active_l1": "Wirkleistung L1 [kW, + = Bezug]",
    "sens_grid_power_active_l2": "Wirkleistung L2 [kW, + = Bezug]",
    "sens_grid_power_active_l3": "Wirkleistung L3 [kW, + = Bezug]",
    "sens_grid_power_reactive": "Blindleistung gesamt [kvar]",
    "sens_grid_power_factor": "Leistungsfaktor",
}


def grid_phase_signals() -> list[Signal]:
    """Push signals for the grid meter per-phase values (device detection, dev only)."""
    signals = []
    for kind in GRID_PHASE_KINDS:
        ehal_id = qualified_grid_id(kind)
        signals.append(
            Signal(
                group=GRID_PHASE_GROUP,
                ehal_id=ehal_id,
                old_name=_GRID_PHASE_LABELS[kind],
                title=title_from_qualified_id(ehal_id),
                digital=False,
            )
        )
    return signals


# Shape copied from a template exported by Loxone Config ("Als Vorlage speichern",
# VO_Earnie Plant Telemetry-30s-Replay.xml, 2026-10-07): Info element first, extra Cmd
# attributes (CmdAnswer, Source/DestVal*, HintText), UTF-8 with BOM, tab indent.
INFO_ATTRS = {"templateType": "3", "minVersion": "17010630"}


def _cmd_attrs(
    sig: Signal, token: str, repeat: str, repeat_rate: str, token_in_address: bool = False
) -> dict[str, str]:
    base = f"/ehal/telemetry/{sig.ehal_id}/"
    use_token = bool(token) and not token_in_address
    query = f"?t={token}" if use_token else ""
    if sig.digital:
        # Digital output: fixed values for On / Off (the value placeholder is for analog outputs).
        on_cmd, off_cmd = f"{base}1{query}", f"{base}0{query}"
        comment = f"{sig.ehal_id} 0/1; parallel to {sig.old_name}"
    else:
        on_cmd, off_cmd = f"{base}<v>{query}", ""
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
                    repeat: str = "10", repeat_rate: str = "10",
                    token_in_address: bool = False) -> str:
    """Template text in the shape Loxone Config exports (without the BOM).

    ``token_in_address``: put the token into the device address (``http://host:port/t/<token>``)
    instead of ``?t=`` in every command, so rotating it touches one field per device.
    """
    address = (
        f"http://{host}:{port}"
        + (f"/t/{token}" if token_in_address and token else "")
    )
    root = ET.Element(
        "VirtualOut",
        {
            "HintText": "",
            "Title": f"Earnie Push - {group}",
            "Comment": "Push telemetry to Earnie; parallel to the poll signals",
            "Address": address,
            "CmdInit": "",
            "CloseAfterSend": "true",
            "CmdSep": "",
        },
    )
    ET.SubElement(root, "Info", INFO_ATTRS)
    for sig in signals:
        ET.SubElement(root, "VirtualOutCmd", _cmd_attrs(sig, token, repeat, repeat_rate, token_in_address))
    ET.indent(root, space="\t")
    body = ET.tostring(root, encoding="unicode").replace(" />", "/>")
    return '<?xml version="1.0" encoding="utf-8"?>\n' + body + "\n"


def render_status_template(*, host: str, port: int) -> str:
    """Status VO with the optional ``Earnie_Request_Optimize`` POST (without the BOM).

    The request-optimize route takes no push token, so the command carries none.
    """
    root = ET.Element(
        "VirtualOut",
        {
            "HintText": "",
            "Title": "Earnie Status Push",
            "Comment": "Optional Request Optimize to Earnie",
            "Address": f"http://{host}:{port}",
            "CmdInit": "",
            "CloseAfterSend": "true",
            "CmdSep": "",
        },
    )
    ET.SubElement(root, "Info", INFO_ATTRS)
    ET.SubElement(
        root,
        "VirtualOutCmd",
        {
            "Title": REQUEST_OPTIMIZE_TITLE,
            "Comment": "Optional: request out-of-band optimize",
            "CmdOnMethod": "POST",
            "CmdOffMethod": "GET",
            "CmdOn": REQUEST_OPTIMIZE_PATH,
            "CmdOnHTTP": "Content-Type: application/json",
            "CmdOnPost": "{}",
            "CmdOff": "",
            "CmdOffHTTP": "",
            "CmdOffPost": "",
            "CmdAnswer": "",
            "Analog": "false",
            "Repeat": "0",
            "RepeatRate": "0",
            "HintText": "",
        },
    )
    ET.indent(root, space="\t")
    body = ET.tostring(root, encoding="unicode").replace(" />", "/>")
    return '<?xml version="1.0" encoding="utf-8"?>\n' + body + "\n"


def write_template(path: Path, text: str) -> None:
    path.write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))  # BOM like Loxone Config


def read_token(env_file: Path) -> str:
    values = dotenv_values(env_file)
    token = str(
        values.get(TOKEN_ENV) or values.get(TOKEN_ENV_LEGACY) or ""
    ).strip()
    if not _TOKEN_RE.match(token):
        raise ValueError(
            f"{TOKEN_ENV} (or {TOKEN_ENV_LEGACY}) missing or not URL-safe "
            f"(>= 8 chars of A-Z a-z 0-9 _ -) in {env_file}"
        )
    return token


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--config-dir", type=Path, default=None,
                        help="Earnie config dir with house_profiles.json / components.json")
    parser.add_argument("--grid-phases", action="store_true",
                        help="dev: only the grid meter per-phase VO (device detection); no config dir")
    parser.add_argument("--host", required=True, help="IP of the Earnie host (not a hostname)")
    parser.add_argument("--port", type=int, default=8542)
    parser.add_argument("--env-file", type=Path, default=None,
                        help=f"optional .env containing {TOKEN_ENV}; default: write a placeholder")
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--repeat", default="10", help="Repeat attribute (Config export: 10 for a 10 s repeat)")
    parser.add_argument("--repeat-rate", default="10", help="RepeatRate attribute (Config export: 10)")
    parser.add_argument("--token-in-address", action="store_true",
                        help="put the token into the device address (/t/<token>) instead of ?t= per command; "
                             "check with scripts.pilot_vo_capture that Loxone joins address and command that way")
    args = parser.parse_args()

    if args.grid_phases == (args.config_dir is not None):
        parser.error("give exactly one of --config-dir or --grid-phases")
    token = read_token(args.env_file) if args.env_file else TOKEN_PLACEHOLDER
    if args.grid_phases:
        signals = grid_phase_signals()
    else:
        signals = collect_read_signals(args.config_dir) + [heartbeat_signal()]
    args.out_dir.mkdir(parents=True, exist_ok=True)
    groups: dict[str, list[Signal]] = {}
    for sig in signals:
        groups.setdefault(sig.group, []).append(sig)
    for group, items in groups.items():
        path = args.out_dir / f"VO_Earnie_{group}.xml"
        write_template(path, render_template(group, items, host=args.host, port=args.port, token=token,
                                             repeat=args.repeat, repeat_rate=args.repeat_rate,
                                             token_in_address=args.token_in_address))
        print(f"{path.name}: {len(items)} Cmds")
    with open(args.out_dir / "Earnie-VO-Signalliste.csv", "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(["Datei", "VO-Cmd-Titel", "EHAL-ID", "Bisheriger Name (Poll)", "Typ"])
        for group, items in groups.items():
            for sig in items:
                writer.writerow([f"VO_Earnie_{group}.xml", sig.title, sig.ehal_id, sig.old_name,
                                 "digital" if sig.digital else "analog"])
    print(f"{len(signals)} signals in {len(groups)} files -> {args.out_dir}")
    if token == TOKEN_PLACEHOLDER:
        print(f"Token placeholder in the XML: replace {TOKEN_PLACEHOLDER} with your token before use.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
