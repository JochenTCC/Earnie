🗺️ Projekt-Roadmap & Backlog

## Offene Todos
- [ ] E-Auto wurde am 29.06. nicht richtig aufgeladen - Verhalten prüfen
- [ ] PWM für E-Auto-Laden nur noch benutzen für Ströme < A_min, ansonsten ersetzen durch Mindestlademenge pro h (Zähler, der runterzählt und bei jedem Ladevorgang wieder geresettet wird -> Wenn Null, dann fünf Minuten laden mit Mindest-Strom)
- [ ] Erinnerung am Monatsanfang für Einspeisepreis (E-Mail von Loxone!)
- [ ] Bessere Verbrauchsoptimierung mit Geräten zur Temperaturkontrolle
  - [ ] Generell: Temperaturregelung bleibt eine "interne Logik"
  - [ ] Generell: Ernie soll ein Prognose-Modell für Energiebedarf erstellen (mit der Zeit) - Einfaches Knotenmodell mit angenommener Wärmekapazität und Wärmeleitfähigkeit nach aussen.
  - [ ] Generell: Folgende Temperaturen werden zur Verfügung gestellt: Soll- / Ist-Temperatur / Umgebungstemperatur (für Prognosemodell) / Erlaubte Differenz (bzw. Min- / Max Temp)
  - [ ] Swim-Spa (Prio1) Hat großes Potenzial, da derzeit oft Energie vorgesehen wird, die gar nicht gebraucht wird - kann aber auch andersrum sein
    - [ ] Für Temperaturvorhersage des Pools werden auch Außentemp-Vorhersagen benötigt
  - [ ] Gefrierschrank (Prio2)
  - [ ] Wärmepumpe (Prio3) - Nur indirekte Steuerung über Anpassung der Solltemperaturen
- [ ] Nutzung des Swim-Spa Filters reviewen (läuft derzeit ständig?)
  - Es gibt ein Signal "Ernie_Swimspa_Filter_Sollstunden", das angibt, wie lange der Filter laufen soll in den nächsten 24 Stunden
  - Es gibt ein Steuersignal "Ernie_Filter_Freigabe", mit dem der Filter ein- und ausgeschaltet werden kann
  - Ernie muss dafür sorgen, dass die Sollstunden in den nächsten 24 wieder auf Null kommen
  - Der Filter braucht eine bestimmte Leistung
  - In Loxone werden die Laufzeiten auf- und runter-integriert
- [ ] **urgent-Regel auf Notwendigkeit prüfen** (Review bis ca. **2026-07-12**, zwei Wochen nach Einführung der Observability)
  - Auswertung: `urgent_rule_observability` in `energy_optimizer.log` und `optimization_history.jsonl` (`role`: `redundant` / `nachholen` / `nur_urgent_fenster`)
  - Akzeptanz: Wenn durchgehend nur `redundant` → Nebenbedingung entfernen (reicht Gesamt-Deadline + Kostenminimierung); sonst behalten und kurz begründen
- [ ] Verbrauchshistorie anzeigbar Machen im Live Modus (ist nur unzulänglich implementiert)
  - [x] Erster Schritt ist erledigt
  - [ ] Es muss noch ein Weg gefunden werden, wie die tatsächlichen Verläufe angezeigt werden können, um Diskrepanzen zu erkennen
  - [ ] Der neue Modus muss noch mit dem alten Verfahren (Historischer Tag) vereinheitlicht werden. Eine Idee wäre, den Betriebsmodus links zu entfernen und bei Offline-Anzeige zwischen geloggten und neu optimierten Daten umschalten zu können - dann könnte ein Vergleich früherer Optimierungen mit aktueller angeschaut werden - ähnlich wie Vergleich Soll <> Ist
- [ ] Empfehlungsmodus für Waschmaschine und Geschirrspüler (Input: Laufzeit, mittlere Leistung / Output: Zeithorizont 6h: Güte des Startzeitpunkts)
- [ ] **Adaptives PV-Tuning wieder aktivieren** (`pv_accuracy_log.csv` / `log_pv_comparison`)
  - Lesen + Anwenden des Korrekturfaktors läuft noch (`calculate_tuning_factor`, `pv_forecast`, Sidebar)
  - Schreiben ist unterbrochen: `log_pv_comparison()` wird nirgends aufgerufen → Faktor bleibt praktisch bei 1,0
  - `get_pv_delta_and_update()` (Zähler-Delta) nutzen, aber Regel für Vergleich mit Prognose klären (15-Min-Takt vs. Stunden-kW)
  - Akzeptanz: CSV wächst wieder; Sidebar-Faktor ≠ 1,0 bei messbarer Abweichung; Synology-Mount für Log ggf. zurück in Compose
     
## Erledigte Punkte
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
- [x] "Silent-Modus" einführen, damit Tests in der Dev-Umgebung laufen können, während Produktiv-Variante läuft
- [x] Kostenchart fix skalieren (nicht flexibel)
- [x] Möglichkeit prüfen, ob variable Leistung bei E-Auto möglich und sinnvoll wäre
- [x] Prüfen, ob sich PV-Überschuss-Modus bei E-Auto sinnvoll einsetzen lässt. --> Ja ist möglich und sinnvoll
- [x] PV_Follow Modus in Loxone implementieren und beides testen
- [x] Zusätzliche Balken im Chart einfügen, die eingespeiste Energie anzeigen (ist als Linienverlau implementiert)
- [x] Kommunikation mit Bew-Meldern (Hue) prüfen (war ein Programmierfehler in loxone_publish)
- [x] Logik und UI für E-Auto verbessern
  - [x]Logik zum Zurücksetzen des Rest-SOC ist in Loxone implementiert - muss aber noch getestet werden. Rest-SOC wird beim Abstecken des Autos zurückgesetzt (auf 10%)
  - [x] Optimierung ausserplanmäßig anstoßen, wenn E-Auto angeschlossen wurde? --> umgesetzt (event_trigger in main.py)
  - [x] Ernie darüber Bescheid geben, wenn E-Auto SOFORT LADEN umgeschalten wird (als Event) und zur Berücksichtigung in der Optimierung
- [x] Ergebnisse des Produktivlaufs in Sankey-Diagramm integrieren und getrennte Anzeige entfernen.
- [x] Anzeige Plausibilität entfernen

### Log-Dateien (Review 2026-06)

| Datei | Status | Aktion |
|-------|--------|--------|
| `runtime/optimization_history.jsonl` | **kanonisch** | Produktiv-Historie (main + App-Panel) |
| `runtime/energy_optimizer.log` | **aktiv** | Python-Logging (rotierend, 5×5 MB) |
| `runtime/optimizer_run_state.json` | **aktiv** | Letzter main-Durchlauf für App |
| `runtime/live_optimization_debug.json` | **aktiv** | App-24h-Debug-Snapshot |
| `runtime/system_history_log.csv` | **Legacy, nur Lesen** | Schreiben in main.py entfernt; App liest alte Einträge noch mit |
| `runtime/pv_accuracy_log.csv` | **Lesen aktiv, Schreiben aus** | `log_pv_comparison` in main anbinden (siehe Backlog) |
| `backtesting_log.json` | **nur Dev** | Backtesting-Modus, nicht für Prod-NAS |

Offen: Legacy-CSV irgendwann archivieren und `_load_legacy_csv_history` entfernen, wenn JSONL die komplette Historie abdeckt.

## Packaging & Deployment

Ziel: reproduzierbares Build/Deploy und weniger manuelle Schritte — ohne Änderungen an der Optimierungslogik.

Empfohlene Reihenfolge: 7b → 7c → 7a → 7d → 7e → 7f

- [x] **7b — Container-Bootstrap automatisieren**
  - Entrypoint + `scripts/bootstrap_runtime` (legt fehlende Dateien an, überschreibt nie)
  - Persistenz unter `config/` und `runtime/` (vereinfachte Compose-Mounts)
  - Config-Drift-Hinweise (`config/config.example.json` vs. Anwender-config, kein Auto-Merge)
  - Migration: `scripts/migrate_persist_layout.py`; Doku: [docs/einrichtung/container.md](docs/einrichtung/container.md)
  - Akzeptanz: frischer Container startet ohne manuelles Anlegen von Dateien
- [x] **7c — Build-Pipeline vereinheitlichen**
  - Kanonisch: `python -m scripts.build_container` / `build-container.ps1` (linux/amd64, Tags latest + Version)
  - Synology-Compose mit 7b abgeglichen; Deploy per `pull` + `up`
  - Doku: [docs/einrichtung/container.md](docs/einrichtung/container.md), [README.md](README.md)
- [x] **7a — Projekt-Metadaten (`pyproject.toml`)**
  - Version aus `version.py` (`[tool.setuptools.dynamic]`)
  - Abhängigkeiten in `pyproject.toml`; `requirements.txt` → `pip install .`
  - `[project.scripts]`: ernie-bootstrap, ernie-build-image, ernie-verify-loxone, …
  - Akzeptanz: `pip install -e .[dev]`, `pytest` grün
- [x] **7d — Streamlit extern bereitstellen**
  - Separater Service/Port im Compose (`optimizer-worker` + `optimizer-ui`)
  - Synology Reverse Proxy (HTTPS, Let's Encrypt) → `127.0.0.1:8501`; WebSocket-Header in der DSM
  - Fritzbox: 80 + 443 → NAS (8501 nur intern); Doku: [docs/einrichtung/container.md](docs/einrichtung/container.md)
  - Akzeptanz: App von außerhalb des NAS erreichbar (Netzwerk/VPN vorausgesetzt)
- [ ] **7e — Prod/Dev-Datensync**
  - Skript für `runtime/`, relevante CSVs, optional config-Template hin und zurück
  - Akzeptanz: dokumentierter Ablauf Dev ↔ Produktiv ohne Copy-Paste
- [ ] **7f — Loxberry-Container evaluieren (erst wenn auf Loxberry 4 umgestellt wurde) **
  - Erst nach 7b/7c; separates Compose oder Anleitung
  - Akzeptanz: Go/No-Go mit kurzer Notiz im README
