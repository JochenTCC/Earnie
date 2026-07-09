"""JSON-Lese- und Schreib-Hilfen für Konfigurationsdateien."""
from __future__ import annotations

import json


def read_json_dict(path: str) -> dict:
    """Liest JSON mit UTF-8; Fallback cp1252 (häufig bei manueller Bearbeitung auf Windows/Synology)."""
    last_decode_error: UnicodeDecodeError | None = None
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            with open(path, "r", encoding=encoding) as f:
                return json.load(f)
        except UnicodeDecodeError as e:
            last_decode_error = e
        except json.JSONDecodeError:
            raise
    raise ValueError(
        f"Konfigurationsdatei '{path}' ist weder UTF-8 noch cp1252 "
        f"(z. B. Umlaute wie in 'Wärmepumpe'). Bitte als UTF-8 speichern."
    ) from last_decode_error


def write_json_dict(path: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
        f.write("\n")
