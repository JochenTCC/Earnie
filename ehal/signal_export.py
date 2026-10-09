"""Build a ZIP of Loxone VO/VI pilot templates from the Signal list (2.7.q Q7)."""
from __future__ import annotations

import csv
import io
import zipfile
from typing import Literal

from ehal.push_signals import Signal
from ehal.signal_list import signals_for_export
from scripts.pilot_vi_template_gen import render_template as render_vi
from scripts.pilot_vo_template_gen import TOKEN_PLACEHOLDER
from scripts.pilot_vo_template_gen import render_template as render_vo

ExportMode = Literal["needed", "all"]

_README = """Earnie Signal-list export (VO / VI)

1. Copy VO_Pilot_*.xml into Loxone Config Virtual Output templates.
2. Copy VI_Pilot_*.xml into Virtual Input templates.
3. Replace PILOT_TOKEN_HIER_ERSETZEN in VO addresses with EARNIE_PILOT_PUSH_TOKEN.
4. Wire VO sources to real measurements; VI Checks poll status.json on Earnie.

Mode: {mode}
Host: {host}:{port}
"""


def build_export_zip(
    house: dict,
    components: dict,
    *,
    host: str,
    port: int,
    mode: ExportMode = "needed",
    token: str = TOKEN_PLACEHOLDER,
) -> bytes:
    """Return ZIP bytes with VO/VI XML, CSV lists, and a short README."""
    reads, writes = signals_for_export(house, components, mode=mode)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        _write_vo_group(zf, reads, host=host, port=port, token=token)
        _write_vi_group(zf, writes, host=host, port=port)
        zf.writestr(
            "README.txt",
            _README.format(mode=mode, host=host, port=port),
        )
    return buf.getvalue()


def _group_signals(signals: list[Signal]) -> dict[str, list[Signal]]:
    groups: dict[str, list[Signal]] = {}
    for sig in signals:
        groups.setdefault(sig.group, []).append(sig)
    return groups


def _bom(text: str) -> bytes:
    return b"\xef\xbb\xbf" + text.encode("utf-8")


def _write_vo_group(
    zf: zipfile.ZipFile,
    signals: list[Signal],
    *,
    host: str,
    port: int,
    token: str,
) -> None:
    rows: list[list[str]] = []
    for group, items in _group_signals(signals).items():
        name = f"VO_Pilot_{group}.xml"
        zf.writestr(
            name,
            _bom(render_vo(group, items, host=host, port=port, token=token)),
        )
        for sig in items:
            rows.append(
                [
                    name,
                    sig.title,
                    sig.ehal_id,
                    sig.old_name,
                    "digital" if sig.digital else "analog",
                ]
            )
    csv_buf = io.StringIO()
    writer = csv.writer(csv_buf, delimiter=";")
    writer.writerow(["Datei", "VO-Cmd-Titel", "EHAL-ID", "Bisheriger Name", "Typ"])
    writer.writerows(rows)
    zf.writestr("Pilot-VO-Signalliste.csv", "\ufeff" + csv_buf.getvalue())


def _write_vi_group(
    zf: zipfile.ZipFile,
    signals: list[Signal],
    *,
    host: str,
    port: int,
) -> None:
    rows: list[list[str]] = []
    for group, items in _group_signals(signals).items():
        name = f"VI_Pilot_{group}.xml"
        zf.writestr(name, _bom(render_vi(group, items, host=host, port=port)))
        for sig in items:
            rows.append([name, sig.title, sig.ehal_id, sig.old_name, "analog"])
    csv_buf = io.StringIO()
    writer = csv.writer(csv_buf, delimiter=";")
    writer.writerow(["Datei", "VI-Cmd-Titel", "EHAL-ID", "Bisheriger Name", "Typ"])
    writer.writerows(rows)
    zf.writestr("Pilot-VI-Signalliste.csv", "\ufeff" + csv_buf.getvalue())
