"""Render the German setup checklist for the operator (no webhook ids in it)."""
from __future__ import annotations

from .mapping import HA_TO_LOXONE, BridgeMapping
from .loxone_xml import outgoing_points


def render_checklist(mapping: BridgeMapping, *, package_file: str, xml_file: str | None) -> str:
    inputs = [p for p in mapping.points if p.direction == HA_TO_LOXONE]
    outputs = outgoing_points(mapping)
    lines = [
        f"# Checkliste HA ↔ Loxone: {mapping.title}",
        "",
        "Erzeugt von `tools.ha_loxone_bridge`. Die Entity-IDs im Mapping müssen mit den echten IDs in HA",
        "übereinstimmen (Entwicklerwerkzeuge → Zustände).",
        "",
        "## Home Assistant",
        "",
        f"1. `secrets.yaml`: `{mapping.loxone_user_secret}` und `{mapping.loxone_pass_secret}` "
        "(Miniserver-Benutzer mit Schreibrecht auf die Virtuellen Eingänge).",
        f"2. `{package_file}` als Package ablegen (`homeassistant: packages: !include_dir_named packages`).",
        "   Bestehende `rest_command`-Einträge und Automationen mit gleichem Namen vorher entfernen.",
        "3. Konfiguration prüfen, HA neu starten.",
        "",
        "## Loxone Config",
        "",
    ]
    if inputs:
        lines += [
            "### Virtuelle Eingänge (analog), HA schreibt per `rest_command`",
            "",
            "| Name (exakt, Groß-/Kleinschreibung) | HA-Quelle |",
            "|---|---|",
            *[f"| `{p.loxone_name}` | `{p.ha_entity}` |" for p in inputs],
            "",
            "Ins Programm ziehen, speichern, übertragen. Kein Virtueller HTTP-Eingang.",
            "",
        ]
    if outputs and xml_file:
        lines += [
            f"### Virtueller Ausgang (`{xml_file}`)",
            "",
            f"Vorlage importieren. Adresse: `http://{mapping.ha_host}:{mapping.ha_port}` "
            "(IP, kein Hostname). Jeden Befehl an die passende Programmlogik hängen:",
            "",
            "| Befehl | Typ | setzt in HA | Verhalten |",
            "|---|---|---|---|",
        ]
        for p in outputs:
            kind = "digital" if p.is_switch else "analog"
            if p.is_switch:
                behaviour = "1 → an, 0 → aus"
            else:
                parts = []
                if p.minimum is not None or p.maximum is not None:
                    parts.append(f"begrenzt auf {p.minimum if p.minimum is not None else '−∞'}…"
                                 f"{p.maximum if p.maximum is not None else '∞'}")
                if p.step is not None:
                    parts.append(f"Raster {p.step:g}")
                behaviour = ", ".join(parts) or "Wert direkt"
            lines.append(f"| `{p.loxone_name}` | {kind} | `{p.ha_entity}` | {behaviour} |")
        lines += [
            "",
            "- Die Webhook-IDs stehen in der XML-Datei und sind der einzige Zugriffsschutz: Datei nicht committen.",
            "- Wiederholung (Repeat) wirkt als Resync nach einem HA-Neustart. HA schaltet nur, wenn der Zielwert "
            "vom aktuellen Zustand abweicht, die EcoFlow-Cloud bekommt also keine Dauer-Schreibzugriffe.",
            "- Ein analoger Ausgang sendet bei Wert 0 nichts (kein Off-Befehl); die Untergrenze des Mappings "
            "greift also nur bei Werten ≠ 0.",
            "",
        ]
    return "\n".join(lines)
