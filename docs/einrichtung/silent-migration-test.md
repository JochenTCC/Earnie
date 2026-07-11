# Silent Migration Test Stack (2.0 P6)

Lokaler Abnahme-Stack für die **vollständige Config-Migration** (1.26.0 P5 + 2.0 P6) mit **Silent-Modus**: Loxone lesen, keine Schreibbefehle an Miniserver/Verbraucher. **Alles läuft lokal** unter `silent-migration-test/` — kein Schreibzugriff auf die NAS (Streamlit kann `.env` speichern).

Getrennt von Greenfield (`greenfield/`) und vom produktiven NAS-Deploy.

## Voraussetzungen

- Projekt-Checkout mit `.venv`
- NAS-Freigabe **lesbar** (`\\DS-KO-DO-2\docker\earnie\`) — nur zum einmaligen Kopieren beim Setup
- Prod-Worker auf der NAS **darf laufen** — dieser Stack nutzt ein **lokales** `runtime/`

## Stack erzeugen (einmalig / nach Config-Änderung auf NAS)

```powershell
.venv\Scripts\python.exe -m scripts.setup_silent_migration_test `
  --nas-config "\\DS-KO-DO-2\docker\earnie\config\config.json" `
  --nas-runtime "\\DS-KO-DO-2\docker\earnie\runtime" `
  --output-dir silent-migration-test `
  --force
```

Das Skript:

1. Liest NAS-`config.json` + Sidecars
2. **P5:** `migrate_runtime_entities` — flache `runtime_settings` → Entitäts-IDs
3. **P6 / 2.0:** `finalize_migration_for_2_0` — Live-Szenario, Legacy-Blöcke entfernen
4. Schreibt migrierte Dateien nach `silent-migration-test/config/`
5. **Kopiert** `config/.env` von der NAS → `silent-migration-test/config/.env` (lokal beschreibbar)
6. **Kopiert** Runtime-Dateien (`cons_data_hourly.csv`, State-JSONs, Profile-CSVs) → `silent-migration-test/runtime/`
7. Legt `runtime/local_settings.json` mit `loxone_silent_mode: true` an

Ergebnis prüfen: `silent-migration-test/config/MIGRATION_REVIEW.md`

Der Ordner `silent-migration-test/` ist in `.gitignore`.

## Ordnerlayout

| Pfad | Inhalt |
|------|--------|
| `silent-migration-test/config/config.json` | 2.0-ready (`live_scenario_id`, kein `runtime_settings`) |
| `silent-migration-test/config/.env` | Loxone-Zugangsdaten (Kopie von NAS, lokal editierbar) |
| `silent-migration-test/config/backtesting_scenarios.json` | Live-Szenario + ggf. NAS-What-if-Szenarien |
| `silent-migration-test/runtime/cons_data_hourly.csv` | Kopie von NAS-runtime |
| `silent-migration-test/runtime/local_settings.json` | `{"loxone_silent_mode": true}` |

## Worker / UI starten

### VS Code (empfohlen)

- **main.py (Silent Migration Test)**
- **main.py + Streamlit (Silent Migration :8512)**

Alle `EARNIE_*`-Pfade zeigen auf `silent-migration-test/` — keine UNC-Pfade.

### PowerShell

```powershell
$root = "C:\Users\joche\Documents\Smarthome\Python\Energy-Optimizer"
$env:EARNIE_CONFIG_PATH = "$root\silent-migration-test\config\config.json"
$env:EARNIE_RUNTIME_DIR = "$root\silent-migration-test\runtime"
$env:EARNIE_DOTENV_PATH = "$root\silent-migration-test\config\.env"
$env:EARNIE_LOCAL_SETTINGS_PATH = "$root\silent-migration-test\runtime\local_settings.json"
$env:EARNIE_HOUSE_PROFILES_PATH = "$root\silent-migration-test\config\house_profiles.json"
$env:EARNIE_TARIFFS_PATH = "$root\silent-migration-test\config\tariffs.json"
$env:EARNIE_BACKTESTING_SCENARIOS_PATH = "$root\silent-migration-test\config\backtesting_scenarios.json"
$env:EARNIE_VERIFY_LOXONE_ON_START = "1"
$env:EARNIE_STRICT_TARIFF_VALIDATE = "1"

.venv\Scripts\python.exe -m scripts.validate_tariffs --check-catalog
.venv\Scripts\python.exe -m scripts.startup_checks
.venv\Scripts\python.exe main.py
```

## Abnahme-Checkliste (2.0 P6 lokal)

| Schritt | Erwartung |
|---------|-----------|
| Setup | `.env` und `cons_data_hourly.csv` unter `silent-migration-test/` vorhanden |
| `validate_tariffs --check-catalog` | Exit 0 |
| `startup_checks` | Tarif-Plausibilität OK; Loxone-Reads OK |
| `main.py` | Log: „Loxone Silent-Modus aktiv“ |
| Loxone | **Keine** Schreibbefehle an Miniserver |

## Sicherheitshinweise

- **Silent-Modus** unterdrückt Loxone/Huawei/Verbraucher-Schreiben; **lokales** `runtime/` wird trotzdem beschrieben (`cons_data`, Logs).
- NAS-Prod bleibt unberührt — nur Loxone-**Lesen** über das Netzwerk.
- Nach erfolgreicher Abnahme: NAS-Cutover (Backlog **2.0 P6** Prod) — siehe [Konfiguration — Überblick](../konfiguration/ueberblick.md).

## Stack zurücksetzen

```powershell
Remove-Item -Recurse -Force silent-migration-test
.venv\Scripts\python.exe -m scripts.setup_silent_migration_test --force
```
