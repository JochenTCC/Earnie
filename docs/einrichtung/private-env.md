# Private Haus-Konfiguration (Earnie-env-home)

Hausbezogene Dateien unter `earnie_env/config/` gehören **nicht** ins öffentliche Earnie-Repository. Vorlagen und der veröffentlichte Tarifkatalog liegen unter `share/config/`.

## Trennung

| Ort | Inhalt |
|-----|--------|
| `share/config/` (öffentlich) | `*.minimal.json`, `*.example.json`, `*.schema.json`, **`tariffs.json`** |
| Privates Repo `Earnie-env-home` | `config.json`, Szenarien, `house_profiles.json`, `components.json`, `deviation_rules.json`, `uploads/`, **`vscode/launch.json`** |
| `earnie_env/config/` (lokal) | Windows-**Junction** auf das private `config/` |
| `.vscode/launch.json` (lokal) | Aus privatem `vscode/launch.json` (Hardlink/Kopie via Link-Skript); im öffentlichen Repo gitignored |
| `earnie_env/runtime/` | Laufzeitdaten (gitignored), lokal |

`.env` (Loxone) wird nirgends versioniert.

## Einrichtung (Windows)

1. Privates Repo neben dem Earnie-Clone ablegen, z. B. `..\Earnie-env-home` (GitHub: privat).
2. Im Earnie-Root:

```powershell
.\scripts\link_private_env.ps1
```

Beim ersten Mal mit vorhandenem echtem `earnie_env\config`-Ordner: `-Force` (legt ein Backup `config.bak-…` an).

Das Skript installiert außerdem `.vscode/launch.json` aus dem privaten `vscode/launch.json` (Hardlink wenn möglich, sonst Kopie). So bleibt die Launch-Config nach Branch-/Tag-Syncs wiederherstellbar, ohne sie im öffentlichen Repo zu versionieren.

Fehlendes `tariffs.json` im Link-Ziel wird aus `share/config/tariffs.json` kopiert (lokal; nicht ins private Repo committen).

## Bootstrap / Community Cloud

Ohne privates Repo und ohne Junction: leeres `earnie_env/config/` + Vorlagen in `share/config/` → Bootstrap legt minimale Haus-Dateien an und seeded den Tarifkatalog aus `share/config/tariffs.json`. Sinnvoll mit `EARNIE_OFFLINE=1` und ggf. `EARNIE_UI_MODES=scenario_explorer`.

Für die öffentliche Demo auf Streamlit Community Cloud zusätzlich **`EARNIE_CLOUD_DEMO=1`**: jede Browser-Sitzung erhält einen eigenen temporären Greenfield-Workspace (leere Minimal-Config), startet im **Hauskonfigurator** und zeigt eine kurze Willkommenshinweis. Nach dem Start einer Szenario-Explorer-Berechnung erscheint ein Feedback-Hinweis mit vorbereitetem **GitHub-Issue** (Label `cloud-demo`; optional Konfigurations-ZIP nur lokal herunterladen — nicht in öffentliche Issues; bei Bedarf privat an `support@earnie-hems.com`). Offline-Demo-Seed der Live-Szenario-IDs entfällt in diesem Modus. Empfohlene Secrets: `EARNIE_CLOUD_DEMO=1`, `EARNIE_OFFLINE=1`, `EARNIE_UI_MODES=scenario_explorer`.

## Tarifkatalog veröffentlichen

UI/Auto-Save schreibt `earnie_env/config/tariffs.json` (Junction). Öffentlichen Stand aktualisieren:

```powershell
Copy-Item earnie_env\config\tariffs.json share\config\tariffs.json -Force
```

Danach im Earnie-Repo committen. Deploy-Gate: `python -m scripts.validate_tariffs --tariffs share/config/tariffs.json --check-catalog`.

## ZIP speichern/laden

Sidebar-ZIP bleibt der portable Transfer der Laufzeit-Config; siehe [Speichern / Laden](../konfiguration/speichern-laden.md).
