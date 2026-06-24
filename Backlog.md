🗺️ Projekt-Roadmap & Backlog

- [x] Lineare Programmireung in optimizer.py einbauen (forecast_pv und forecast_consumption berücksichtigen)
- [x] Deployment auf Synology NAS einrichten
- [x] Aktuellen Ladezustand in Sankey-Diagramm verschieben (oben rausnehmen)
- [x] Versionsnummer einführen und anzeigen (Github-Release-Nr?)
- [x] Umgang mit historischen Verbrauchsdaten nochmal prüfen (wie funktioniert das genau, wie sollte mit Großverbrauchern umgegangen werden, wie gehen neue Daten ein) 
- [x] E-Auto / Swim-Spa / Wärmepumpe in die Optimierung mit reinnehmen mit Empfehlung, wann der beste Startzeitpunkt wäre bzw. autonomes Starten. 
- [x] Fiktive Simulation der historischen Daten mit einer größeren Batterie
- [x] Zulässigen Maximalstrom für E-Auto Laden für Ernie bereitstellen
- [x] Optimierung von main.py wird in App nicht richtig übernommen (kleinen Zeitversatz einbauen?) 
- [x] Vergangene Optimierungen anzeigbar Machen im Live Modus (debugging) 
- [x] Testsuite für 24h-Optimierung mit historischen Daten aufbauen
- [x] Dateistruktur aufräumen
- [x] Dateigrößen prüfen und ggf. refaktorieren
- [x] Ladeenergie für E-Auto anpassen (ist derzeit zu klein)
- [x] Ansicht Produktiv-Durchlauf wird nicht korrekt aktualisiert
- [x] Bei E-Auto wahrscheinliche Abwesenheite implementieren
- [x] Prüfen, ob ältere Programm-Logs noch benötigt werden *(2026-06: siehe unten)*
- [x] Steuersignale von main.py scheinen in Loxone wieder auf andere Werte gesetzt zu werden - Debug-Tool erstellen und Verhalten prüfen.
  — Da hat wohl eine alte noch laufende Instant von main.py regelmäßig dazwischengefunkt.
- [x] Chart für Ersparnis separat unter die anderen Zeitverläufe (kleiner?) packen. Vielleicht gemeinsam mit den stündlichen Kosten.  
  - die Balken müssen bei Einspeisung noch richtig dargestellt werden.
- [x] Simulation hat immer ein 24h-Zeithorizont - wenn nötig, mit gespiegelten Kosten des Vortags
- [ ] Nutzung des Swim-Spa Filters reviewen (läuft derzeit ständig?)
- [ ] Logik und UI für E-Auto verbessern
  - Logik zum Zurücksetzen des Rest-SOC ist in Loxone implementiert - muss aber noch getestet werden. Rest-SOC wird beim Abstecken des Autos zurückgesetzt (auf 10%)
  - Optimierung ausserplanmäßig anstoßen, wenn E-Auto angeschlossen wurde?
- [ ] Verbrauchshistorie anzeigbar Machen im Live Modus (ist nur unzulänglich implementiert)
- [ ] Erinnerung am Monatsanfang für Einspeisepreis
- [ ] Empfehlungsmodus für Waschmaschine und Geschirrspüler (Input: Laufzeit, mittlere Leistung / Output: Zeithorizont 6h: Güte des Startzeitpunkts)
- [ ] **Adaptives PV-Tuning wieder aktivieren** (`pv_accuracy_log.csv` / `log_pv_comparison`)
  - Lesen + Anwenden des Korrekturfaktors läuft noch (`calculate_tuning_factor`, `pv_forecast`, Sidebar)
  - Schreiben ist unterbrochen: `log_pv_comparison()` wird nirgends aufgerufen → Faktor bleibt praktisch bei 1,0
  - `get_pv_delta_and_update()` (Zähler-Delta) nutzen, aber Regel für Vergleich mit Prognose klären (15-Min-Takt vs. Stunden-kW)
  - Akzeptanz: CSV wächst wieder; Sidebar-Faktor ≠ 1,0 bei messbarer Abweichung; Synology-Mount für Log ggf. zurück in Compose

### Log-Dateien (Review 2026-06)

| Datei | Status | Aktion |
|-------|--------|--------|
| `runtime/optimization_history.jsonl` | **kanonisch** | Produktiv-Historie (main + App-Panel) |
| `energy_optimizer.log` | **aktiv** | Python-Logging (rotierend, 5×5 MB) |
| `runtime/optimizer_run_state.json` | **aktiv** | Letzter main-Durchlauf für App |
| `runtime/live_optimization_debug.json` | **aktiv** | App-24h-Debug-Snapshot |
| `system_history_log.csv` | **Legacy, nur Lesen** | Schreiben in main.py entfernt; App liest alte Einträge noch mit |
| `pv_accuracy_log.csv` | **Lesen aktiv, Schreiben aus** | `log_pv_comparison` in main anbinden (siehe Backlog); Mount optional wieder für NAS |
| `backtesting_log.json` | **nur Dev** | Backtesting-Modus, nicht für Prod-NAS |

Offen: Legacy-CSV irgendwann archivieren und `_load_legacy_csv_history` entfernen, wenn JSONL die komplette Historie abdeckt.

## Packaging & Deployment

Ziel: reproduzierbares Build/Deploy und weniger manuelle Schritte — ohne Änderungen an der Optimierungslogik.

Empfohlene Reihenfolge: 7b → 7c → 7a → 7d → 7e → 7f

- [ ] **7b — Container-Bootstrap automatisieren**
  - Beim ersten Start fehlende `runtime/`-JSONs, leere History und cons_data-Pfade anlegen
  - Entrypoint-Skript statt nur `CMD ["python", "main.py"]`
  - Akzeptanz: frischer Container startet ohne manuelles Anlegen von Dateien
- [ ] **7c — Build-Pipeline vereinheitlichen**
  - `containers.build` wiederherstellen oder README/Dockerfile als kanonischen Weg festhalten
  - Synology-Compose (`docker-compose-synology.yml`) mit 7b abgleichen
  - Akzeptanz: ein dokumentierter Build-Befehl, Synology-Deploy weiter möglich
- [ ] **7a — Projekt-Metadaten (`pyproject.toml`)**
  - Version aus `version.py` als Single Source of Truth
  - Dependencies mit `requirements.txt` konsolidieren
  - Optional: `[project.scripts]` für main/streamlit/scripts
  - Akzeptanz: `pip install -e .` im Repo, `pytest` weiter grün
- [ ] **7d — Streamlit extern bereitstellen**
  - Separater Service/Port im Compose (main + app)
  - In diesem Schritt nur erreichbare URL — kein Loxone-Embed
  - Akzeptanz: App von außerhalb des NAS erreichbar (Netzwerk/VPN vorausgesetzt)
- [ ] **7e — Prod/Dev-Datensync**
  - Skript für `runtime/`, relevante CSVs, optional config-Template hin und zurück
  - Akzeptanz: dokumentierter Ablauf Dev ↔ Produktiv ohne Copy-Paste
- [ ] **7f — Loxberry-Container evaluieren**
  - Erst nach 7b/7c; separates Compose oder Anleitung
  - Akzeptanz: Go/No-Go mit kurzer Notiz im README
