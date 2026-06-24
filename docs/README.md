# Energy Optimizer — Anwender-Dokumentation

Diese Dokumentation richtet sich an Betreiber des Energy Optimizers (Ernie): Einrichtung, Konfiguration, Streamlit-Oberfläche und die Schnittstelle zum Loxone Miniserver.

Für Entwickler (Projektstruktur, Tests, Container) siehe [README.md](../README.md) im Projektroot.

## Erste Schritte

1. **Vorlage kopieren:** `config.example.json` → `config.json` (lokal, nicht ins Repository committen).
2. **Loxone-Zugang:** `.env.example` → `.env` mit `LOXONE_IP`, `LOXONE_USER`, `LOXONE_PASS`.
3. **Merker-Namen** in `config.json` unter `loxone_blocks` und `flexible_consumers` an die eigenen virtuellen Eingänge/Merker anpassen (siehe [Loxone-Signale](referenz/loxone-signale.md)).
4. **Verbindung prüfen:**
   ```powershell
   python -m scripts.verify_loxone_setup
   python -m scripts.verify_loxone_setup --ftp --roundtrip
   ```
5. **Produktivbetrieb starten:** `python main.py` (Optimierung im 15-Minuten-Takt).
6. **Cockpit öffnen:** `streamlit run app.py` (Modus **Echtzeit**).

Parameter-Beschreibungen erscheinen in Cursor/VS Code als Hover-Hilfe, wenn in `config.json` `"$schema": "./config.schema.json"` gesetzt ist.

## Inhaltsverzeichnis

### Einrichtung

- [Loxone-Anbindung](einrichtung/loxone-anbindung.md) — HTTP-Schnittstelle, FTP-Log, Prüfskript
- [Betrieb](einrichtung/betrieb.md) — `main.py` vs. App, Laufzeitdateien, Optimierungs-Takt

### Konfiguration (`config.json`)

- [Überblick](konfiguration/ueberblick.md) — Aufbau der Datei, Szenarien, Dateipfade
- [PV & Batterie](konfiguration/batterie-pv.md) — `runtime_settings`
- [Flexible Verbraucher](konfiguration/flexible-verbraucher.md) — SwimSpa, E-Auto, Wärmepumpe
- [Preise & aWATTar](konfiguration/preise.md) — Bezugspreis, Einspeisevergütung, Steuern

### Benutzeroberfläche (Streamlit)

- [Betriebsmodi](ui/betriebsmodi.md) — Echtzeit, Historischer Tag, Backtesting
- [Charts & Panels](ui/charts.md) — Diagramme, Metriken, Sankey, Historie

### Referenz

- [Loxone-Signale](referenz/loxone-signale.md) — Tabelle aller Lesen-/Schreib-Signale
