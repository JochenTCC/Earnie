# Shadow-Betrieb (Entwickler)

Nur für Entwicklung und Test, **nicht** Teil der Anwender-Einrichtung. Spec: [`docs/dev/shadow-mode.md`](../dev/shadow-mode.md). Anwender-Betrieb: [betrieb.md](../einrichtung/betrieb.md).

### Shadow-Feed (Prod-Recorder, optional)

Für eine spätere Dev-/Shadow-Instanz kann die Produktivinstanz Rohantworten der Backend-Reads in ein Feed-Verzeichnis schreiben (Spec: [`docs/dev/shadow-mode.md`](../dev/shadow-mode.md)).

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

Eine Entwicklungsinstanz kann parallel zur Produktivinstanz laufen und Eingänge aus dem Shadow-Feed lesen — ohne Backend-Schreibzugriffe und ohne Änderungen an der gemeinsamen Konfiguration (Ausnahme: EHAL-Mapping kann in `{Runtime}/shadow_ehal_bindings.json` landen und wird beim Laden der Hausprofile nur in Shadow gemerged). Spec: [`docs/dev/shadow-mode.md`](../dev/shadow-mode.md).

Voraussetzungen:

1. Prod mit `shadow_feed_enabled: true` (siehe Abschnitt Shadow-Feed).
2. Eigenes Runtime-Verzeichnis (`EARNIE_RUNTIME_PATH` oder `EARNIE_ENV_PATH` — Pflicht).
3. Gemeinsames Config-Verzeichnis (z. B. SMB-Share der HA-Add-on-Config) bzw. `EARNIE_SHADOW_FEED_PATH`.
4. Bei **Loxone**-Backend: Prod muss `loxone_feed: "push"` in `shadow_feed/meta.json` schreiben (VO-Push in den Feed). Ältere Prod-Builds ohne diese Capability lehnt Shadow beim Start ab — es gibt keinen Fallback auf die Prod-Datei `loxone_push_inbox.json`.

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

Die Streamlit-UI zeigt ein dauerhaftes Shadow-Banner; unter EHAL-Com erscheint die Tabelle der blockierten Schreibvorgänge (`shadow_writes.jsonl`).

- **Geteilte Prod-Config** (Feed liegt unter dem Config-Verzeichnis): Config schreibgeschützt; EHAL-Mapping „Speichern“ schreibt nur das Runtime-Overlay `shadow_ehal_bindings.json`.
- **Private lokale Config** (`EARNIE_SHADOW_FEED_PATH` zeigt auf den Prod-Feed außerhalb der lokalen Config): Hauskonfigurator, `.env` und EHAL-Mapping schreiben in die lokale `earnie_env` — Backend-Schreibzugriffe bleiben blockiert.


## Umgebungsvariablen

| Variable | Wirkung |
| --- | --- |
| `EARNIE_SHADOW_FEED_PATH` | Optional: Verzeichnis für den Prod-Shadow-Feed (sonst `{Config}/shadow_feed/`). Siehe Abschnitt Shadow-Feed. |
| `EARNIE_SHADOW` | `1` = Shadow-Modus (Dev-Client): Eingänge aus Feed, keine Backend-Schreibzugriffe. Config schreibgeschützt nur bei geteilter Prod-Config; private lokale Config (externer Feed) ist schreibbar. Siehe Abschnitt Shadow-Modus. |
| `EARNIE_SHADOW_MAX_AGE_SEC` | Max. Alter eines Feed-Eintrags relativ zur Prod-`cycle_ts` (Fallback: Heartbeat; Standard 120). |
