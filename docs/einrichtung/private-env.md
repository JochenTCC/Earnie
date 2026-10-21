# Private Haus-Konfiguration (Earnie-env-home)

Hausbezogene Dateien unter `earnie_env/config/` gehören **nicht** ins öffentliche Earnie-Repository. Vorlagen und der veröffentlichte Tarifkatalog liegen unter `share/config/`.

## Trennung

| Ort | Inhalt |
|-----|--------|
| `share/config/` (öffentlich) | `*.minimal.json`, `*.example.json`, `*.schema.json`, **`tariffs.json`** |
| Privates Repo `Earnie-env-home` | `config.json`, Szenarien, `house_profiles.json`, `components.json`, `deviation_rules.json`, `uploads/`, optional **`vscode/launch.json`** |
| `earnie_env/config/` (lokal) | Windows-**Junction** auf das private `config/` |
| `.vscode/launch.json` (lokal) | Maschinenspezifisch, im öffentlichen Repo per gitignore ausgeschlossen. Optional aus dem privaten `vscode/launch.json` (Hardlink oder Kopie über das Link-Skript) |
| `earnie_env/runtime/` | Laufzeitdaten, lokal (per gitignore ausgeschlossen) |

Die Datei `.env` (Loxone) wird nirgends versioniert.

## Einrichtung (Windows)

1. Privates Repo neben dem Earnie-Clone ablegen, z. B. `..\Earnie-env-home` (auf GitHub als privates Repo).
2. Im Earnie-Root das Link-Skript ausführen:

```powershell
.\scripts\link_private_env.ps1
```

Existiert beim ersten Aufruf bereits ein echter Ordner `earnie_env\config`, ist `-Force` nötig. Das Skript legt dann ein Backup `config.bak-…` an.

Enthält das private Repo eine `vscode/launch.json`, installiert das Skript sie außerdem als `.vscode/launch.json` (als Hardlink, wenn möglich, sonst als Kopie). Fehlt sie, überspringt es diesen Schritt. So lässt sich die Launch-Konfiguration nach dem Wechsel von Branch oder Tag wiederherstellen, ohne sie im öffentlichen Repo zu versionieren.

Fehlt `tariffs.json` im Link-Ziel, kopiert das Skript sie aus `share/config/tariffs.json`. Diese Kopie bleibt lokal und gehört nicht ins private Repo.

## Bootstrap / Community Cloud

Ohne privates Repo und ohne Junction genügen ein leeres `earnie_env/config/` und die Vorlagen in `share/config/`. Der Bootstrap legt dann minimale Haus-Dateien an. Tarifkatalog und Netzentgeltkatalog übernimmt er aus `share/config/tariffs.json` bzw. `share/config/grid_fees.json`. Sinnvoll ist das zusammen mit `EARNIE_OFFLINE=1` und ggf. `EARNIE_UI_MODES=scenario_explorer`.

Für die öffentliche Demo auf Streamlit Community Cloud kommt **`EARNIE_CLOUD_DEMO=1`** hinzu. In diesem Modus gilt:

- **Eigener Workspace:** Jede Browser-Sitzung erhält einen eigenen temporären Greenfield-Workspace mit leerer Minimal-Config.
- **Start:** Die Sitzung beginnt im **Hauskonfigurator** und zeigt einen kurzen Willkommenshinweis.
- **Bewertung:** Wurde im Szenario-Explorer eine Berechnung gestartet, kann beim Verlassen der Seite einmalig ein anonymer Bewertungsdialog mit Sternen erscheinen. **Senden** überträgt die Bewertung an den fest hinterlegten Earnie-Server. **Abbrechen** beendet die Abfrage ebenfalls, ohne etwas zu senden.
- **Kein Offline-Seed:** Der Offline-Demo-Seed der Live-Szenario-IDs entfällt.

Empfohlene Secrets: `EARNIE_CLOUD_DEMO=1`, `EARNIE_OFFLINE=1`, `EARNIE_UI_MODES=scenario_explorer`.

## Tarifkatalog veröffentlichen

Die Oberfläche schreibt per Auto-Save nach `earnie_env/config/tariffs.json` (Junction). Den öffentlichen Stand aktualisiert dieser Befehl:

```powershell
Copy-Item earnie_env\config\tariffs.json share\config\tariffs.json -Force
```

Danach die Änderung im Earnie-Repo committen. Vor dem Deploy prüft dieser Befehl den Katalog: `python -m scripts.validate_tariffs --tariffs share/config/tariffs.json --check-catalog`.

## ZIP speichern/laden

Das ZIP aus der Sidebar bleibt der portable Weg, die Laufzeit-Config zwischen Installationen zu übertragen. Details: [Speichern / Laden](../konfiguration/speichern-laden.md).

## Private Regression-Fälle (Earnie-regression-private)

Kundendaten für die Release-Regression liegen im privaten Nachbar-Repo `Earnie-regression-private` (Ordner `cases/`) und **nicht** im öffentlichen Repo.

| Einstellung | Bedeutung |
|-------------|-----------|
| Standardpfad | `..\Earnie-regression-private\cases` neben dem Earnie-Clone |
| `$EARNIE_REGRESSION_PRIVATE_DIR` | Überschreibt den Cases-Root (keine Junction nötig) |

Fehlt der private Root, überspringt `python -m scripts.run_regression` die privaten Fälle. Der Report vermerkt das als `private-root-missing`, die Fälle fallen also nicht stillschweigend weg. Neuen Fall aufnehmen (Intake):

```powershell
.venv\Scripts\python.exe -m scripts.run_regression --intake DUMP.zip `
  --id REG-142-eauto-deadline --private --seed-anchor "2026-06-26T18:00:00"
```

Details: [`docs/workflow/regression-suite.md`](../workflow/regression-suite.md) §4 / §9.
