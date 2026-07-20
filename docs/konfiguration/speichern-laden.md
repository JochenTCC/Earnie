# Konfiguration speichern und laden

Earnie speichert die Haus- und Szenario-Konfiguration unter `earnie_env/config/` (Laufzeitdaten unter `earnie_env/runtime/`). Ältere Installationen mit `./config` und `./runtime` bleiben über Umgebungsvariablen oder Legacy-Pfade nutzbar — für neue Setups gilt `earnie_env/`.

Hausbezogene JSON/CSVs sind **nicht** Teil des öffentlichen Earnie-Repos (privates Repo / Junction); der veröffentlichte Tarifkatalog liegt unter `share/config/tariffs.json`. Details: [Private Haus-Config](../einrichtung/private-env.md). Das Sidebar-ZIP bleibt der portable Transfer zwischen Installationen.

## Auto-Speichern

Im **Hauskonfigurator** und **Szenarieneditor** werden gültige Änderungen automatisch auf die Festplatte geschrieben (kein separater Speichern-Button). Unvollständige Formulare (z. B. leere Bezeichnung) werden nicht persistiert. Im Szenarieneditor können gespeicherte Nicht-Live-Szenarien mit **Szenario entfernen** gelöscht werden (das aktuelle Live-Szenario ist geschützt).

## ZIP-Export / -Import (Sidebar)

In der Streamlit-Seitenleiste unter **„Konfiguration speichern / laden“**:

- **ZIP herunterladen** — packt die aktuellen JSON-Dateien und alle CSV unter `uploads/`
- **ZIP importieren** — ersetzt die gleichen Dateien nach Versionsprüfung

Enthaltene Dateien:

| Inhalt | Hinweis |
|--------|---------|
| `config.json` | Live-/Systemkonfiguration |
| `backtesting_scenarios.json` | Szenarien |
| `components.json` | PV / Batterie |
| `house_profiles.json` | Hausprofile |
| `tariffs.json` | Tarifkatalog |
| `deviation_rules.json` | Soll/Ist-Regeln |
| `uploads/*` | Profil-CSVs |

**Nicht** enthalten: `config/.env` (Loxone-Zugangsdaten bleiben lokal).

Jedes JSON trägt das Feld `earnie_data_model` (aktuell `1`). Beim Import prüft Earnie die Kompatibilität; unbekannte Versionen werden abgelehnt (Konverter folgen später).

## Migration von `./config` + `./runtime`

Bestehende Daten einmalig verschieben:

```powershell
mkdir earnie_env
Move-Item config earnie_env\config
Move-Item runtime earnie_env\runtime
```

Oder die bisherigen Pfade per Env belassen, z. B. `EARNIE_CONFIG_PATH=config` und `EARNIE_RUNTIME_PATH=runtime` (bzw. `EARNIE_ENV_PATH=.` mit Unterordnern `config/` und `runtime/`).

Docker-Compose (Dev/Prod) mountet Host-`./earnie_env/config` bzw. `./earnie_env/runtime` weiterhin als `/app/config` und `/app/runtime` im Container.
