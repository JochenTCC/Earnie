# Betrieb

## Einstiegspunkte


| Komponente           | Befehl                            | Rolle                                                                                         |
| -------------------- | --------------------------------- | --------------------------------------------------------------------------------------------- |
| **Streamlit-App**    | `python -m scripts.run_streamlit` | Cockpit, Konfiguration, Analyse — und Steuerung des Optimierer-Dienstes                       |
| **Produktiv-Daemon** | `python main.py`                  | Liest Loxone, optimiert, schreibt Steuerwerte — läuft dauerhaft (auch als Kind der Streamlit-App) |


Nur `main.py` steuert die Anlage im Produktivbetrieb (Loxone-/EHAL-Schreibvorgänge). Die App **zeigt** den berechneten 24–48-Stunden-Horizont (`live_optimization_debug.json`) und kann den Daemon unter **Daemon Control → Optimierer-Dienst** starten, stoppen und neu starten. Vor dem Start prüft Earnie `runtime/main.lock` (bereits laufende Instanz).

Beim Daemon-Start schreibt Earnie **einmal** sichere Sollwerte (ESS Automatik / Freigabe und EVCS aus), bevor der erste Optimierungslauf läuft — auf allen EHAL-Backends (Loxone, HA, OpenEMS). Im Silent-Modus entfällt dieser Schreibvorgang. Silent/Loud stellt ihr unter **Daemon Control → Optimierer-Dienst** um (gespeichert in `runtime/local_settings.json` → `silent_mode`); ein Neustart von `main.py` ist dafür nicht nötig. Zum Überspringen der Safe-Setpoints: `EARNIE_SKIP_SAFE_SETPOINTS_ON_START=1`.

Unter **Optimierer-Dienst → Dienst-Log** zeigt die App den Schluss (Tail) von `runtime/earnie.log` in einem Expander. Die Anzeige aktualisiert sich automatisch alle 10 Sekunden; **Aktualisieren** oben und unten am Log lädt sofort neu. Unten daneben bringt **Gehe nach Oben** zurück zum Anfang des Log-Bereichs. Log-Level (`INFO` / `WARNING` / …) sind filterbar; Standard ist INFO und höher. Bei jedem erfolgreichen Start von `main.py` schreibt Earnie einen klaren Trennstreifen (Separator) mit PID und Version in `earnie.log`, damit Läufe leichter unterscheidbar sind. Startet die UI den Daemon (`EARNIE_AUTO_START_MAIN` oder Neustart-Button), landet die Konsolen-Ausgabe zusätzlich in `runtime/main_stdio.log` (nicht `DEVNULL`) — hilfreich, wenn `earnie.log` ausbleibt.

**Docker (empfohlen):** Ein Container (`earnie`). Die UI startet `main.py` automatisch, wenn `EARNIE_AUTO_START_MAIN=1` gesetzt ist (Standard in den Compose-Dateien).

**Lokal (venv / VS Code):** `main.py` und Streamlit können getrennt laufen. Auto-Start ist aus, solange `EARNIE_AUTO_START_MAIN` nicht auf `1` steht — so bleibt Debugging von `main.py` exklusiv.

Konfiguration wird über die Planungs- und Echtzeit-Seiten geschrieben (Hauskonfigurator, Szenarienkonfigurator, Manuelle Geräte). Hausbezogene Persistenz lokal bzw. im privaten Repo: [Private Haus-Config](private-env.md).

## Optimierungs-Takt

- Auslösung an **Viertelstunden-Grenzen** (`:00`, `:15`, `:30`, `:45`)
- Zusätzlich **sofort**, wenn Loxone Virtual Out **`Earnie_Request_Optimize`** den Daemon-HTTP trifft (`POST /ehal/loxone/request_optimize`)
- Port: `system.ehal_loxone_http_port` in `config.json` bzw. `EARNIE_EHAL_LOXONE_HTTP_PORT` (Standard **8541**); Vorlage `VO_Earnie_Status.xml` → `http://EARNIE_HOST:8541`
- Alive-Check am selben Port: `GET /ehal/loxone/alive`
- Pattern B Virtual In Status am selben Port: `GET /ehal/loxone/status.json`
- `system.loop_timeout` in `config.json`: maximale Wartezeit zwischen Durchläufen in Sekunden (Standard 900 = 15 Min.)
- Die App lädt den Cockpit-Snapshot nach dem Viertelstunden-Wechsel, sobald `main.py` den aktuellen Slot abgeschlossen hat (typisch wenige Sekunden)

Countdown und letzter Lauf werden unten in der App angezeigt (siehe [Charts & Panels](../ui/charts.md)).

## Laufzeitdateien (`runtime/`)

Standardverzeichnis: `earnie_env/runtime/` (überschreibbar mit `EARNIE_RUNTIME_PATH` bzw. abgeleitet aus `EARNIE_ENV_PATH`).


| Datei                           | Inhalt                                                                                       |
| ------------------------------- | -------------------------------------------------------------------------------------------- |
| `cons_data.csv`          | Stündliche Verbrauchs- und PV-Basis (von `main.py` gepflegt)                                 |
| `flexible_consumers_state.json` | Tagesenergie je Flex-Verbraucher                                                             |
| `pv_counter_state.json`         | PV-Zählerstand für Stunden-Delta                                                             |
| `power_interval_sampler_state.json` | Zwischenpuffer der Leistungsproben (≤ 60 s) für Viertelstunden-Mittel im Produktiv-Log; optional Energie-Anker (`energy_anchors`) für Loxone-Zähler ΔkWh → mittlere Slot-Leistung |
| `cons_data_pending.json`        | Pending-Puffer für cons_data-Samples                                                         |
| `consumption_profiles.csv`      | Berechnete Grundlast-Profile                                                                 |
| `earnie.log`                    | Rotierendes Python-Log von main.py (absoluter Pfad; monatlich; max. 12 Archive `earnie.log.YYYY-MM-DD_HH-MM-SS`) |
| `main_stdio.log`                | stdout/stderr des per UI/Auto-Start gestarteten `main.py` (Diagnose, wenn File-Logging fehlt) |
| `main.lock` / `main.pid`        | Single-Instance-Sperre des Produktiv-Daemons (`main.lock` gehalten; PID zusätzlich in `main.pid` für Status/Stop unter Windows) |
| `optimizer_run_state.json`      | Letzter erfolgreicher `main.py`-Durchlauf (SoC, Modus, Soll-Leistungen, Flex-Soll)           |
| `optimization_history.jsonl`    | Historie aller Produktiv-Durchläufe (eine Zeile JSON pro Lauf; monatlich rotiert, max. 12 Archive; u. a. `consumption_snapshot`, optional `closed_interval`) |
| `live_optimization_debug.json`  | Anzeige-Snapshot des Optimierungs-Horizonts (von `main.py` geschrieben, von der App gelesen) |
| `live_day_ahead_<zone>.json` | Cache der letzten erfolgreichen Live-Day-Ahead-Serie (QH; Zone z. B. `AT`; `source` ENTSO-E oder Energy-Charts); Live nutzt ihn statt erneutem API-Abruf bzw. vor aWATTar-Fallback |
| `local_settings.json`           | Lokale Betriebseinstellungen (z. B. `silent_mode` — auch UI **Optimierer-Dienst**, `chart_debug_capture_enabled`, optional `shadow_feed_enabled`)     |
| `appliance_schedules.json`      | Geplante Laufzeiten manueller Geräte                                                         |
| `backtesting_log.json`          | Ergebnis von Szenario-Explorer / `run_backtesting`                                        |


Die App liest diese Dateien **read-only** für Panels und Abgleich.

### Shadow-Feed (Prod-Recorder, optional)

Für eine spätere Dev-/Shadow-Instanz kann die Produktivinstanz Rohantworten der Backend-Reads in ein Feed-Verzeichnis schreiben (Spec: [`docs/spec/shadow-mode.md`](../spec/shadow-mode.md)).

In `runtime/local_settings.json` (nicht in der gemeinsamen `config.json`):

```json
{
  "shadow_feed_enabled": true,
  "shadow_feed_retention_days": 14
}
```

- Standard: aus (`false` / Schlüssel fehlt) — kein Verhaltensunterschied.
- Feed-Pfad: `{Config-Verzeichnis}/shadow_feed/` (`meta.json`, `latest.json`, `feed-YYYY-MM-DD.jsonl`). Überschreiben: Umgebungsvariable `EARNIE_SHADOW_FEED_PATH`.
- Nur auf der Produktivinstanz aktivieren. Mit `EARNIE_SHADOW=1` wird der Recorder ignoriert.

### Shadow-Modus (Dev-Client)

Eine Entwicklungsinstanz kann parallel zur Produktivinstanz laufen und Eingänge aus dem Shadow-Feed lesen — ohne Backend-Schreibzugriffe und ohne Änderungen an der gemeinsamen Konfiguration (Ausnahme: EHAL-Mapping kann in `{Runtime}/shadow_ehal_bindings.json` landen und wird beim Laden der Hausprofile nur in Shadow gemerged). Spec: [`docs/spec/shadow-mode.md`](../spec/shadow-mode.md).

Voraussetzungen:

1. Prod mit `shadow_feed_enabled: true` (siehe oben).
2. Eigenes Runtime-Verzeichnis (`EARNIE_RUNTIME_PATH` oder `EARNIE_ENV_PATH` — Pflicht).
3. Gemeinsames Config-Verzeichnis (z. B. SMB-Share der HA-Add-on-Config) bzw. `EARNIE_SHADOW_FEED_PATH`.

Beispiel (PowerShell):

```powershell
$env:EARNIE_SHADOW='1'
$env:EARNIE_CONFIG_PATH='\\HOMEASSISTANT\addon_configs\<prod-slug>'
$env:EARNIE_RUNTIME_PATH='C:\earnie-shadow\runtime'
$env:EARNIE_UI_STREAMLIT_PORT='8532'   # bei gleicher Host-Maschine wie Prod
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'
.venv\Scripts\python.exe main.py
```

Optional: Runtime aus Prod vorbelegen (gelernten Zustand kopieren, ohne Logs/Locks/`local_settings.json`):

```powershell
.venv\Scripts\python.exe -m scripts.shadow_seed_runtime --from <prod-runtime> --to <shadow-runtime>
```

Die Streamlit-UI zeigt ein dauerhaftes Shadow-Banner; unter EHAL-Com erscheint die Tabelle der blockierten Schreibvorgänge (`shadow_writes.jsonl`). EHAL-Mapping „Speichern“ schreibt im Shadow-Modus nur das Runtime-Overlay `shadow_ehal_bindings.json`.

### Log- und Historiendateien

Betriebsstatus der wichtigsten Log-, Historien- und Debug-Dateien (Review 2026-06):


| Datei                                | Status                         | Hinweis                                                       |
| ------------------------------------ | ------------------------------ | ------------------------------------------------------------- |
| `optimization_history.jsonl`         | **kanonisch**                  | Produktiv-Historie (eine JSON-Zeile pro Optimierungslauf; monatlich, max. 12 Archive `optimization_history.jsonl.YYYY-MM-DD_HH-MM-SS`) |
| `earnie.log`                         | **aktiv**                      | Rotierendes Python-Log von `main.py` (monatlich, max. 12 Archive) |
| `main_stdio.log`                     | **aktiv**                      | stdout/stderr bei UI-/Auto-Start von `main.py`                    |
| `optimizer_run_state.json`           | **aktiv**                      | Letzter erfolgreicher `main.py`-Durchlauf                     |
| `live_optimization_debug.json`       | **aktiv**                      | 24h-Anzeige-Snapshot für die Streamlit-App                    |
| `backtesting_log.json`               | **nur Dev/Backtesting**        | Ergebnis von Szenario-Explorer — nicht für Produktiv-NAS   |


## Umgebungsvariablen (optional)


| Variable                                | Wirkung                                                                                                                                                                                                                              |
| --------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `EARNIE_ENV_PATH`                       | Wurzelverzeichnis für Persistenz (Standard: `earnie_env`). Daraus leiten sich `…/config` und `…/runtime` ab, sofern nicht separat gesetzt. |
| `EARNIE_CONFIG_PATH`                    | Pfad zum **Config-Verzeichnis** (Standard: `earnie_env/config`; ältere Ordner: `config/`). Enthält `config.json`, Sidecars, `.env`, `uploads/`. (Ältere Setups mit Pfad zur `config.json`-Datei werden weiterhin akzeptiert.) |
| `EARNIE_RUNTIME_PATH`                   | Verzeichnis für Laufzeitdaten (Standard: `earnie_env/runtime`; ältere Ordner: `runtime`). |
| `EARNIE_SHADOW_FEED_PATH`               | Optional: Verzeichnis für den Prod-Shadow-Feed (sonst `{Config}/shadow_feed/`). Siehe [Shadow-Feed](#shadow-feed-prod-recorder-optional). |
| `EARNIE_SHADOW`                         | `1` = Shadow-Modus (Dev-Client): Eingänge aus Feed, keine Backend-/Config-Schreibzugriffe. Siehe [Shadow-Modus](#shadow-modus-dev-client). |
| `EARNIE_SHADOW_MAX_AGE_SEC`             | Max. Alter eines Feed-Eintrags relativ zur Prod-`cycle_ts` (Fallback: Heartbeat; Standard 120). |
| `EARNIE_UI_MODES`                       | Kommagetrennt: `sunset2sunset` (Live-Cockpit), `scenario_explorer`, `live_environment` (Daemon Control / Analyse Verbrauch & Kosten), `price_forecast`. Ohne Variable: `sunset2sunset,scenario_explorer,live_environment` (`price_forecast` nur bei `ui.price_forecast_page_enabled=true`). Prod-Compose setzt oft `sunset2sunset,live_environment`; Cloud: `scenario_explorer` — siehe [Betriebsmodi](../ui/betriebsmodi.md). |
| `EARNIE_UI_STREAMLIT_PORT`              | TCP-Port für Streamlit (überschreibt `ui.streamlit_port`; siehe [Streamlit-Ports](../referenz/streamlit-ports.md))                                                                                                                   |
| `EARNIE_EHAL_LOXONE_HTTP_PORT`          | TCP-Port für Daemon-HTTP (`Earnie_Request_Optimize` / `/alive`; überschreibt `system.ehal_loxone_http_port`, Standard **8541**)                                                                                                       |
| `EARNIE_UI_CHART_DEBUG_CAPTURE_ENABLED` | `1` = Button „Debug-Dump speichern“ im Cockpit (überschreibt `ui.chart_debug_capture_enabled`; ZIP unter `runtime/chart_debug/`). |
| `EARNIE_AUTO_START_MAIN`                | `1` = beim Start von `scripts.run_streamlit` automatisch `main.py` starten, falls nicht schon laufend (Docker-Compose setzt das). Ohne Variable / lokal aus.                                                                              |
| `EARNIE_OFFLINE`                        | `1` = kein Loxone-/Live-Zwang; Bootstrap füllt leere Live-Szenario-Entitäts-IDs aus den Katalogen (sinnvoll für Streamlit Community Cloud). |
| `EARNIE_CLOUD_DEMO`                     | `1` = Streamlit Community Cloud: pro Browser-Sitzung leerer Greenfield-Workspace (Temp-Verzeichnis), Start im Hauskonfigurator, Willkommenshinweis; nach Szenario-Explorer-Start Feedback-Banner mit GitHub-Issue (`cloud-demo`); optional lokale Config-ZIP; kein Offline-Demo-Seed. Typisch zusammen mit `EARNIE_OFFLINE=1`. |


Streamlit-Port-Übersicht (Stacks, Plattformen): [streamlit-ports.md](../referenz/streamlit-ports.md).

## Debug-Dump

Zum Nachvollziehen von Anzeige- oder Optimizer-Problemen ohne erneutes Durchsuchen der Produktivdateien. Aktivierung wie oben (`ui.chart_debug_capture_enabled`, `local_settings.json` oder Env-Variable). Im Live-Cockpit: „Debug-Dump speichern“ → Dialog mit optionalem Titel/Symptom → „ZIP erstellen“ (nur speichern) oder „ZIP erstellen und herunterladen“ (speichern und Browser-Download in einem Schritt).

Ein Dump enthält immer die volle Optimierungshistorie und die aktiven Inputs. Die Chart-UI-Payload wird mitgeschrieben, wenn die Live-Anzeige (Display-Bundle) vorhanden ist; sonst nur Historie/Inputs (Hinweis in der UI).

| Inhalt | Pflicht / optional |
| ------ | ------------------ |
| `runtime/optimization_history.jsonl` | Pflicht (vollständig) |
| `optimizer_run_state.json`, `live_optimization_debug.json`, `flexible_consumers_state.json`, `pv_counter_state.json` | Optional, falls vorhanden |
| `manifest.chart` | Optional (nur mit Live-Anzeige) |
| Titel / Symptom | Optional (`manifest.meta`) |

Gemeinsam in jedem ZIP:

- `manifest.json` — `schema_version: 3`, `dump_type: debug`, App-Version, Env-Overrides, aufgelöste Pfade; optional `chart`, immer `meta` (Titel/Symptom/case_id)
- `inputs/*` — aktive `config.json`, Sidecars, optional Preis-Modell und `cons_data.csv`
- `README.txt` — Kurzbeschreibung der Struktur

Dateiname: `debug_dump_YYYYMMDD_HHMMSS.zip` unter `runtime/chart_debug/` (oder `ui.chart_debug_capture_dir`).

### Replay (teilautomatisch)

```bash
python -m scripts.replay_debug_dump path/to/debug_dump_….zip
python -m scripts.replay_debug_dump path/to/debug_dump_….zip --html-out /tmp/chart1.html
```

Prüft Pflichtdateien und führt einen Smoke-Pfad aus (Historie parsen; bei vorhandenem `chart.display_rows` zusätzlich Chart-1-Neuaufbau). Es werden nur Dumps mit `schema_version: 3` und `dump_type: debug` akzeptiert.

### Prod-Dump als Regression-Fixture

Ein gespeichertes Debug-ZIP kann nach `tests/fixtures/prod_dumps/<id>/` übernommen werden:

```bash
python scripts/archive_prod_dump.py \
  --id mein_fall_2026-07-16 \
  --title "Kurzbeschreibung" \
  --symptom "Beobachtetes Fehlerbild" \
  --source runtime/chart_debug/debug_dump_….zip
```

Details: `tests/fixtures/prod_dumps/README.md`.

## Typische Betriebsfehler

- **App zeigt alte Werte:** `optimizer_run_state.json` fehlt oder `main.py` läuft nicht — Kopfzeile im Sankey „Energiefluss (Live)“ prüfen.
- **Keine aWATTar-Preise:** Simulation bricht in der App mit Fehlermeldung ab; Netzwerk oder API prüfen.

