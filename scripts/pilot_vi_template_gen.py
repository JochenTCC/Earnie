"""Generate Loxone Virtual Input templates with qualified Check keys (2.7.q Q4).

Reads the *write* bindings (``set_*``) of an Earnie config dir and writes one
``VI_Pilot_*.xml`` per entity group plus ``Pilot-VI-Signalliste.csv``. Every Cmd
polls ``/ehal/loxone/status.json`` and extracts the value with
``Check="\"<qualified-id>\":\\v"``. Titles come from the qualified ID.

Usage:
    python -m scripts.pilot_vi_template_gen --config-dir <earnie_env/config> \
        --host 192.168.178.137 --port 8541 --out-dir <dir>
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from ehal.push_signals import (  # noqa: F401 — re-exported for callers and tests
    Signal,
    heartbeat_write_signal,
    vi_title_from_qualified_id,
    write_signals_from_docs,
)
from ehal.qualified_ids import field_kind

INFO_ATTRS = {"templateType": "2", "minVersion": "17010630"}

# Ranges / units aligned with share/loxone/templates/VirtualIn/VI_Earnie_*.xml
_ENABLE_RANGE = {
    "SourceValLow": "0",
    "DestValLow": "0",
    "SourceValHigh": "1",
    "DestValHigh": "1",
    "DefVal": "0",
    "MinVal": "0",
    "MaxVal": "1",
    "Unit": "<v>",
}
_EV_CURRENT_RANGE = {
    "SourceValLow": "0",
    "DestValLow": "0",
    "SourceValHigh": "32",
    "DestValHigh": "32",
    "DefVal": "0",
    "MinVal": "0",
    "MaxVal": "63",
    "Unit": "<v> A",
}
_EV_MODE_RANGE = {
    "SourceValLow": "0",
    "DestValLow": "0",
    "SourceValHigh": "10",
    "DestValHigh": "10",
    "DefVal": "0",
    "MinVal": "0",
    "MaxVal": "10",
    "Unit": "<v>",
}
_HEARTBEAT_RANGE = {
    "SourceValLow": "0",
    "DestValLow": "0",
    "SourceValHigh": "100",
    "DestValHigh": "100",
    "DefVal": "0",
    "MinVal": "-2147483647",
    "MaxVal": "2147483647",
    "Unit": "<v>",
}
_KW_RANGE = {
    "SourceValLow": "0",
    "DestValLow": "0",
    "SourceValHigh": "100",
    "DestValHigh": "100",
    "DefVal": "0",
    "MinVal": "-2147483647",
    "MaxVal": "2147483647",
    "Unit": "<v.3> kW",
}
_MODE_RANGE = {
    "SourceValLow": "0",
    "DestValLow": "0",
    "SourceValHigh": "100",
    "DestValHigh": "100",
    "DefVal": "0",
    "MinVal": "-2147483647",
    "MaxVal": "2147483647",
    "Unit": "<v>",
}
_EXPORT_LIMIT_RANGE = {
    **_KW_RANGE,
    "DefVal": "1000",
}
_SOURCE_SELECT_RANGE = {
    "SourceValLow": "0",
    "DestValLow": "0",
    "SourceValHigh": "1",
    "DestValHigh": "1",
    "DefVal": "0",
    "MinVal": "0",
    "MaxVal": "1",
    "Unit": "<v>",
}


def collect_write_signals(config_dir: Path) -> list[Signal]:
    house = json.loads((config_dir / "house_profiles.json").read_text(encoding="utf-8"))
    components = json.loads((config_dir / "components.json").read_text(encoding="utf-8"))
    return write_signals_from_docs(house, components)


def _cmd_range(ehal_id: str) -> dict[str, str]:
    kind = field_kind(ehal_id)
    if ehal_id == "heartbeat_ts" or kind == "heartbeat_ts":
        return dict(_HEARTBEAT_RANGE)
    if kind == "set_enable":
        return dict(_ENABLE_RANGE)
    if kind == "set_evcs_max_current":
        return dict(_EV_CURRENT_RANGE)
    if kind == "set_evcs_mode":
        return dict(_EV_MODE_RANGE)
    if kind == "set_ess_source_select":
        return dict(_SOURCE_SELECT_RANGE)
    if kind == "set_grid_export_power_limit":
        return dict(_EXPORT_LIMIT_RANGE)
    if kind in (
        "set_ess_active_power",
        "set_ess_charge_power_limit",
        "set_ess_discharge_power_limit",
    ):
        return dict(_KW_RANGE)
    if kind.startswith("set_ess_"):
        return dict(_MODE_RANGE)
    return dict(_MODE_RANGE)


def _cmd_attrs(sig: Signal) -> dict[str, str]:
    attrs = {
        "Title": sig.title,
        "Comment": sig.ehal_id,
        "Check": f'"{sig.ehal_id}":\\v',
        "Signed": "true",
        "Analog": "true",
    }
    attrs.update(_cmd_range(sig.ehal_id))
    attrs["HintText"] = ""
    return attrs


def render_template(
    group: str,
    signals: list[Signal],
    *,
    host: str,
    port: int,
    polling_time: str = "10",
) -> str:
    """Template text in the shape Loxone Config exports (without the BOM)."""
    address = f"http://{host}:{port}/ehal/loxone/status.json"
    root = ET.Element(
        "VirtualInHttp",
        {
            "HintText": "",
            "Title": f"Earnie Status Pilot - {group}",
            "Comment": "Qualified Check keys from Earnie status.json (2.7.q Q4)",
            "Address": address,
            "PollingTime": polling_time,
        },
    )
    ET.SubElement(root, "Info", INFO_ATTRS)
    for sig in signals:
        ET.SubElement(root, "VirtualInHttpCmd", _cmd_attrs(sig))
    ET.indent(root, space="\t")
    body = ET.tostring(root, encoding="unicode").replace(" />", "/>")
    return '<?xml version="1.0" encoding="utf-8"?>\n' + body + "\n"


def write_template(path: Path, text: str) -> None:
    path.write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--config-dir", required=True, type=Path)
    parser.add_argument("--host", required=True, help="IP of the Earnie host (not a hostname)")
    parser.add_argument("--port", type=int, default=8541)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--polling-time", default="10", help="VI PollingTime seconds (default 10)")
    args = parser.parse_args()

    signals = collect_write_signals(args.config_dir) + [heartbeat_write_signal()]
    args.out_dir.mkdir(parents=True, exist_ok=True)
    groups: dict[str, list[Signal]] = {}
    for sig in signals:
        groups.setdefault(sig.group, []).append(sig)
    for group, items in groups.items():
        path = args.out_dir / f"VI_Pilot_{group}.xml"
        write_template(
            path,
            render_template(
                group, items, host=args.host, port=args.port, polling_time=args.polling_time
            ),
        )
        print(f"{path.name}: {len(items)} Cmds")
    with open(args.out_dir / "Pilot-VI-Signalliste.csv", "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(["Datei", "VI-Cmd-Titel", "EHAL-ID", "Bisheriger Name (Merker)", "Typ"])
        for group, items in groups.items():
            for sig in items:
                writer.writerow(
                    [
                        f"VI_Pilot_{group}.xml",
                        sig.title,
                        sig.ehal_id,
                        sig.old_name,
                        "analog",
                    ]
                )
    print(f"{len(signals)} signals in {len(groups)} files -> {args.out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
