# Konfiguration speichern und laden

Earnie speichert die Haus- und Szenario-Konfiguration unter `earnie_env/config/`, Laufzeitdaten unter `earnie_env/runtime/`. Für neue Setups gilt `earnie_env/`. Ältere Installationen mit `./config` und `./runtime` bleiben über Umgebungsvariablen oder die bisherigen Pfade (Legacy-Pfade) nutzbar.

Hausbezogene JSON- und CSV-Dateien sind **nicht** Teil des öffentlichen Earnie-Repos; sie liegen in einem privaten Repo oder werden per Junction eingebunden. Der veröffentlichte Tarifkatalog liegt unter `share/config/tariffs.json`. Details: [Private Haus-Config](../einrichtung/private-env.md). Für den Transfer zwischen Installationen dient weiterhin das ZIP aus der Sidebar.

## Auto-Speichern

Im **Hauskonfigurator** und im **Szenarienkonfigurator** schreibt Earnie gültige Änderungen automatisch auf die Festplatte. Einen eigenen Speichern-Button gibt es nicht. Unvollständige Formulare (z. B. mit leerer Bezeichnung) speichert Earnie nicht.

Im Szenarienkonfigurator lassen sich gespeicherte Szenarien mit **Szenario entfernen** löschen. Das aktuelle Live-Szenario ist davon ausgenommen.

## ZIP-Export / -Import (Sidebar)

Die Streamlit-Seitenleiste bietet unter **„Konfiguration speichern / laden“** zwei Aktionen:

- **ZIP herunterladen:** Packt die aktuellen JSON-Dateien und alle CSV-Dateien unter `uploads/` in ein ZIP.
- **ZIP importieren:** Ersetzt nach einer Versionsprüfung dieselben Dateien durch die Inhalte des ZIP.

Enthaltene Dateien:

| Inhalt | Hinweis |
|--------|---------|
| `config.json` | Live-/Systemkonfiguration |
| `backtesting_scenarios.json` | Szenarien |
| `components.json` | PV / Batterie |
| `house_profiles.json` | Hausprofile |
| `tariffs.json` | Tarifkatalog |
| `grid_fees.json` | Netzentgeltkatalog |
| `deviation_rules.json` | Soll/Ist-Regeln |
| `uploads/*` | Profil-CSVs |

**Nicht** enthalten ist `config/.env`. Die Zugangsdaten für Loxone und Home Assistant bleiben damit lokal.

### Datenmodell-Version

Das Manifest des ZIP (`earnie_config_pack.json`) und die JSON-Dateien tragen das Feld `earnie_data_model` (aktuell `4`). Ausgenommen ist `grid_fees.json`: Earnie schreibt das Feld dort weder beim Export noch beim Import. Beim Import entscheidet die Version im Manifest:

- **Version `4`:** Earnie übernimmt die Dateien. Beim Schreiben setzt Earnie das Feld in den Dateien auf `4`.
- **Version `3`:** Earnie hebt die Dateien automatisch auf Version `4` an. Dieselbe Migrationskette läuft auch im [Migrations-Assistenten](../einrichtung/betrieb.md#update-und-migration) für die Konfiguration im Betrieb.
- **Ältere oder fehlende Versionen** (`1`, `2`, fehlendes Feld im Manifest): Earnie lehnt den Import ab und ändert die Version nicht stillschweigend.

**Hintergrund zu früheren Umstellungen:**

- Gemeinsame Referenzkurven (`oemag_monthly_feed_in_rates`, `monthly_float_reference_cent_kwh`, `econtrol_referenzmarktwert_pv_monthly`) liegen in `tariffs.json`.
- Monatskonstante Einspeisetarife nutzen den Typ `monthly_table` mit eigenen `monthly_rates`.
- In `config.json` heißt der frühere Block `file_paths_battery_simulation` jetzt `scenario_explorer_conf`. Den alten Schlüssel lehnt Earnie ab.

## Migration von `./config` + `./runtime`

Bestehende Daten lassen sich einmalig verschieben:

```powershell
mkdir earnie_env
Move-Item config earnie_env\config
Move-Item runtime earnie_env\runtime
```

Alternativ bleiben die bisherigen Pfade über Umgebungsvariablen erhalten, z. B. `EARNIE_CONFIG_PATH=config` und `EARNIE_RUNTIME_PATH=runtime`. Ebenso möglich ist `EARNIE_ENV_PATH=.` mit den Unterordnern `config/` und `runtime/`.

Docker Compose (Dev und Prod) bindet die Host-Ordner `./earnie_env/config` und `./earnie_env/runtime` weiterhin als `/app/config` und `/app/runtime` in den Container ein und setzt `EARNIE_ENV_PATH=.`.
