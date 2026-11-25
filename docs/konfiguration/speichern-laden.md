# Konfiguration speichern und laden

Earnie speichert die Haus- und Szenario-Konfiguration unter `earnie_env/config/`, Laufzeitdaten unter `earnie_env/runtime/`. Gibt es `earnie_env/` nicht, aber die Ordner `config/` und `runtime/` direkt im Earnie-Ordner, nutzt Earnie diese. Andere Orte lassen sich über Umgebungsvariablen festlegen (siehe unten).

Diese Dateien liegen nur in der eigenen Installation. Für den Transfer zwischen Installationen dient das ZIP aus der Seitenleiste (**Sichern & Übertragen**).

## Auto-Speichern

Im **Hauskonfigurator** und im **Szenarienkonfigurator** schreibt Earnie gültige Änderungen automatisch auf die Festplatte. Einen eigenen Speichern-Button gibt es nicht. Unvollständige Formulare (z. B. mit leerer Bezeichnung) speichert Earnie nicht.

Im Szenarienkonfigurator lassen sich gespeicherte Szenarien mit **Szenario entfernen …** löschen. Earnie fragt vorher nach; das Löschen lässt sich nicht rückgängig machen. Das aktuelle Live-Szenario lässt sich nicht löschen.

## ZIP-Export / -Import (Sidebar)

Die Streamlit-Seitenleiste bündelt unter **„Sichern & Übertragen“** alles, was Daten aus Earnie heraus oder hinein bringt. Der Abschnitt **Konfiguration sichern / laden** bietet zwei Aktionen:

- **Konfigurations-ZIP erstellen**, dann **Konfiguration herunterladen:** Packt die aktuellen JSON-Dateien und alle CSV-Dateien unter `uploads/` in ein ZIP. Earnie baut das ZIP erst auf Knopfdruck, damit nicht jeder Seitenaufbau alle CSV-Dateien neu packt.
- **Konfiguration importieren (ZIP):** Ersetzt nach einer Versionsprüfung dieselben Dateien durch die Inhalte des ZIP.

Enthaltene Dateien:

| Inhalt | Hinweis |
|--------|---------|
| `config.json` | Live-/Systemkonfiguration |
| `backtesting_scenarios.json` | Szenarien |
| `components.json` | PV / Batterie |
| `house_profiles.json` | Hausprofile |
| `tariffs.json` | Tarifkatalog |
| `user_tariffs.json` | Benutzertarife von der Seite **Tarife** (nur wenn vorhanden) |
| `grid_fees.json` | Netzentgeltkatalog |
| `user_grid_fees.json` | Benutzer-Netzbereiche, z. B. eigener Arbeitspreis eines Hausprofils (nur wenn vorhanden) |
| `deviation_rules.json` | Soll/Ist-Regeln |
| `uploads/*` | Profil-CSVs |

**Nicht** enthalten ist `config/.env`. Die Zugangsdaten für Loxone und Home Assistant bleiben damit lokal.

Darunter liegt im selben Menü das **Support-Paket** für Support-Anfragen (Konfiguration + Anhänge, oder vollständig mit Historie, Recorder und Logs) – siehe [Betrieb → Support-Paket](../einrichtung/betrieb.md#support-paket-debug-dump).

### Datenmodell-Version

Die Dateien gehören zu einem von zwei Versions-Tracks:

- **Earnie-Datenmodell** (`earnie_data_model`, aktuell `6`): Manifest (`earnie_config_pack.json`), `config.json`, `backtesting_scenarios.json`, `components.json`, `house_profiles.json`, `deviation_rules.json`.
- **Tarifformat** (`tariff_format`, aktuell `1`, Format der Tarifdateien): `tariffs.json`, `user_tariffs.json`, `grid_fees.json`, `user_grid_fees.json`. Diese Dateien tragen nie `earnie_data_model`.

Beim Import prüft Earnie Manifest und jede Datei:

- **Datenmodell `6` und Tarifformat `1`:** Earnie übernimmt die Dateien. Beim Schreiben setzt Earnie `earnie_data_model` in den Earnie-Track-Dateien auf `6`.
- **Datenmodell `3` bis `5`, Tarifdateien ohne `tariff_format`:** Earnie hebt die Dateien mit derselben Migrationskette wie der [Migrations-Assistent](../einrichtung/betrieb.md#update-und-migration) an. Braucht die Kette eine Antwort (z. B. Netzbereich eines Hausprofils ohne Netzentgelt, USt-Satz eines Benutzertarifs), lehnt Earnie den Import mit Hinweis ab; dann die Dateien zuerst im Assistenten migrieren.
- **Ältere oder fehlende Versionen** (`1`, `2`, fehlendes `earnie_data_model`) in Manifest oder Earnie-Track-Datei, oder ein unbekanntes `tariff_format`: Earnie lehnt den Import ab und ändert die Version nicht stillschweigend.

## Speicherort ändern

Liegen `config/` und `runtime/` direkt im Earnie-Ordner, lassen sie sich so nach `earnie_env/` verschieben:

```powershell
mkdir earnie_env
Move-Item config earnie_env\config
Move-Item runtime earnie_env\runtime
```

Andere Orte legen Umgebungsvariablen fest: `EARNIE_ENV_PATH` für einen Ordner mit den Unterordnern `config/` und `runtime/` (z. B. `EARNIE_ENV_PATH=.`), oder einzeln `EARNIE_CONFIG_PATH` und `EARNIE_RUNTIME_PATH`.

Die Docker-Compose-Dateien für den Produktivbetrieb binden die Host-Ordner `./earnie_env/config` und `./earnie_env/runtime` als `/app/config` und `/app/runtime` ein und setzen `EARNIE_ENV_PATH=.`.
