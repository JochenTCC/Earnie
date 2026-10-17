# Shadow-Betrieb (Entwickler)

Diese Seite richtet sich an Entwicklung und Test und gehört **nicht** zur Anwender-Einrichtung. Die technische Spezifikation steht in [`docs/dev/shadow-mode.md`](../dev/shadow-mode.md), den regulären Betrieb beschreibt [betrieb.md](../einrichtung/betrieb.md).

## Shadow-Feed (Prod-Recorder, optional)

Die Produktivinstanz kann die Rohantworten ihrer Backend-Reads in ein Feed-Verzeichnis schreiben. Eine spätere Dev- oder Shadow-Instanz liest diesen Feed als Eingang.

Die Einstellung gehört in `runtime/local_settings.json` (nicht in die gemeinsame `config.json`):

```json
{
  "shadow_feed_enabled": true,
  "shadow_feed_retention_days": 14
}
```

- **Standard:** Der Recorder ist aus (`false` oder Schlüssel fehlt). Das Verhalten der Instanz ändert sich dann nicht.
- **Feed-Pfad:** `{Config-Verzeichnis}/shadow_feed/` mit den Dateien `meta.json`, `latest.json` und `feed-YYYY-MM-DD.jsonl`. Die Umgebungsvariable `EARNIE_SHADOW_FEED_PATH` überschreibt den Pfad.
- **Nur auf der Produktivinstanz aktivieren:** Mit `EARNIE_SHADOW=1` ignoriert Earnie den Recorder.

## Shadow-Modus (Dev-Client)

Eine Entwicklungsinstanz kann parallel zur Produktivinstanz laufen und ihre Eingänge aus dem Shadow-Feed lesen. Sie schreibt dabei nicht ins Backend und ändert die gemeinsame Konfiguration nicht.

Einzige Ausnahme ist das EHAL-Mapping: Es kann in `{Runtime}/shadow_ehal_bindings.json` landen. Earnie führt diese Datei nur im Shadow-Modus beim Laden der Hausprofile mit der Konfiguration zusammen.

### Voraussetzungen

1. Die Produktivinstanz läuft mit `shadow_feed_enabled: true` (siehe [Shadow-Feed](#shadow-feed-prod-recorder-optional)).
2. Die Shadow-Instanz hat ein eigenes Runtime-Verzeichnis (`EARNIE_RUNTIME_PATH` oder `EARNIE_ENV_PATH`, Pflicht).
3. Beide Instanzen nutzen ein gemeinsames Config-Verzeichnis (z. B. SMB-Share der HA-Add-on-Config), alternativ zeigt `EARNIE_SHADOW_FEED_PATH` auf den Feed.
4. Bei **Loxone**-Backend muss die Produktivinstanz `loxone_feed: "push"` in `shadow_feed/meta.json` schreiben (VO-Push in den Feed). Ältere Prod-Builds ohne diese Fähigkeit lehnt der Shadow-Modus beim Start ab. Einen Fallback auf die Prod-Datei `loxone_push_inbox.json` gibt es nicht.

### Start

Beispiel (PowerShell):

```powershell
$env:EARNIE_SHADOW='1'
$env:EARNIE_CONFIG_PATH='\\HOMEASSISTANT\addon_configs\<prod-slug>'
$env:EARNIE_RUNTIME_PATH='C:\earnie-shadow\runtime'
$env:EARNIE_UI_STREAMLIT_PORT='8532'   # bei gleicher Host-Maschine wie Prod
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'
.venv\Scripts\python.exe main.py
```

Optional lässt sich das Runtime-Verzeichnis aus der Produktivinstanz vorbelegen. Das Skript kopiert den gelernten Zustand ohne Logs, Locks und `local_settings.json`:

```powershell
.venv\Scripts\python.exe -m scripts.shadow_seed_runtime --from <prod-runtime> --to <shadow-runtime>
```

### Verhalten im Shadow-Modus

Die Streamlit-UI zeigt dauerhaft ein Shadow-Banner. Die Seite EHAL-Com listet die blockierten Schreibvorgänge (`shadow_writes.jsonl`) in einer Tabelle.

Was die Shadow-Instanz schreiben darf, hängt von der Lage der Config ab:

- **Geteilte Prod-Config** (der Feed liegt unter dem Config-Verzeichnis): Die Config ist schreibgeschützt. „Speichern“ im EHAL-Mapping schreibt nur das Runtime-Overlay `shadow_ehal_bindings.json`.
- **Private lokale Config** (`EARNIE_SHADOW_FEED_PATH` zeigt auf den Prod-Feed außerhalb der lokalen Config): Hauskonfigurator, `.env` und EHAL-Mapping schreiben in die lokale `earnie_env`. Backend-Schreibzugriffe bleiben auch hier blockiert.

## Umgebungsvariablen

| Variable | Wirkung |
| --- | --- |
| `EARNIE_SHADOW_FEED_PATH` | Optional: Verzeichnis für den Prod-Shadow-Feed (sonst `{Config}/shadow_feed/`). Siehe [Shadow-Feed](#shadow-feed-prod-recorder-optional). |
| `EARNIE_SHADOW` | `1` = Shadow-Modus (Dev-Client): Eingänge aus dem Feed, keine Backend-Schreibzugriffe. Schreibgeschützt ist die Config nur bei geteilter Prod-Config; eine private lokale Config (externer Feed) bleibt schreibbar. Siehe [Shadow-Modus](#shadow-modus-dev-client). |
| `EARNIE_SHADOW_MAX_AGE_SEC` | Maximales Alter eines Feed-Eintrags relativ zur Prod-`cycle_ts` (Fallback: Heartbeat; Standard 120). |
