# HA ↔ Loxone Bridge-Generator (POC: EcoFlow Delta 3)

> **Status:** Proof of Concept. Generator und Tests sind fertig, der Live-Test am echten Miniserver und an
> der Delta 3 steht noch aus. Bis dahin bleibt die [EcoFlow-Anleitung](ecoflow-delta3-loxone.md) die
> Referenz für die Logik im Miniserver (Schritt 8).

Der Generator unter `tools/ha_loxone_bridge/` erzeugt aus **einer** Mapping-Datei die komplette Brücke
zwischen Home Assistant und dem Loxone Miniserver:

- ein **HA-Package** (`rest_command`, Template-Sensor, Automationen),
- eine **Loxone-Vorlage** für einen Virtuellen Ausgang (`VO_HA_Bridge.xml`),
- eine **Checkliste** mit allem, was in Loxone Config von Hand anzulegen ist.

Der Generator erzeugt nur Dateien. Er schreibt nichts in ein laufendes HA oder in den Miniserver. Earnie
selbst ist nicht beteiligt (`ehal.backend=loxone` bleibt unverändert).

## Warum ein neuer Weg?

Die bisherige Brücke Loxone → HA (EcoFlow-Anleitung, Schritt 5/6, Variante A) läuft über einen Umweg:

1. Der Miniserver beschreibt per Virtuellem Ausgang seinen eigenen Virtuellen Eingang.
2. Die Loxone-Integration (PyLoxone) spiegelt diesen Eingang nach HA.
3. Eine Automation setzt daraus den EcoFlow-Wert.

Dabei wurde der Eingang zwischendurch mit fremden Werten überschrieben (Ursache noch offen).

Der Generator baut diese Richtung ohne PyLoxone und ohne Virtuellen Eingang:

| Richtung | Weg | Werte (Delta 3) |
|---|---|---|
| HA → Loxone | HA-`rest_command` schreibt einen **Virtuellen Eingang** (`/jdev/sps/io/<Name>/<Wert>`) | SoC, Netto-Leistung, SOC-Max, SOC-Min |
| Loxone → HA | Loxone-**Virtueller Ausgang** ruft einen **HA-Webhook** auf (`/api/webhook/<id>?v=<v>`) | AC-Ladeleistung, Grid-Bypass |

Damit hat jeder Wert genau **einen** Schreiber.

## Schritt für Schritt

### 1. Mapping-Datei anlegen

1. Beispiel kopieren, am besten in den privaten (nicht versionierten) Config-Ordner:

   ```powershell
   New-Item -ItemType Directory -Force earnie_env\config\ha_loxone_bridge
   Copy-Item tools\ha_loxone_bridge\examples\delta3.mapping.json earnie_env\config\ha_loxone_bridge\
   ```

2. Folgende Einträge anpassen:
   - **`loxone.host` / `ha.host`:** **IP-Adressen** eintragen, keine Hostnamen (siehe EcoFlow-Anleitung,
     Schritt 4).
   - **`ha.port`:** der Port, unter dem die HA-Oberfläche im Browser erreichbar ist. Standard ist `8123`,
     manche Installationen nutzen `80`. Zur Gegenprobe `http://<HA-IP>:<Port>/api/` aufrufen: Die Antwort
     „401: Unauthorized“ bestätigt den Port, `ERR_CONNECTION_REFUSED` bedeutet einen falschen Port
     (Details: EcoFlow-Anleitung, Schritt 5, Variante B).
   - **`ha_entity`:** die echten Entity-IDs der eigenen Delta 3 (Entwicklerwerkzeuge → Zustände,
     Gerätename statt `delta_3`).
   - **`loxone_input`:** die Namen der Virtuellen Eingänge im Miniserver (exakte Groß-/Kleinschreibung).
   - **`webhook_id`:** je Webhook eine **zufällige** ID. Die ID ist der einzige Zugriffsschutz des
     Webhooks, deshalb verweigert der Generator IDs mit `CHANGE_ME`. Eine ID lässt sich z. B. so erzeugen:

     ```powershell
     .venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(18))"
     ```

### 2. Generieren

```powershell
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'
.venv\Scripts\python.exe -m tools.ha_loxone_bridge --mapping earnie_env\config\ha_loxone_bridge\delta3.mapping.json --out-dir earnie_env\config\ha_loxone_bridge\out
```

Im Ausgabeordner entstehen `ha_loxone_bridge.yaml`, `VO_HA_Bridge.xml` und `Checkliste.md`.

> **Hinweis:** Die XML-Datei enthält die Webhook-IDs und gehört nicht in ein Git-Repository. Der oben
> verwendete Ordner ist bereits per `.gitignore` ausgeschlossen.

### 3. Home Assistant

1. In `secrets.yaml` die Einträge `loxone_user` und `loxone_pass` ergänzen. Gemeint ist ein
   Miniserver-Benutzer mit Schreibrecht auf die Virtuellen Eingänge.
2. Packages aktivieren, falls noch nicht geschehen. Dazu in `configuration.yaml` eintragen:

   ```yaml
   homeassistant:
     packages: !include_dir_named packages
   ```

   Anschließend den Ordner `packages/` neben `configuration.yaml` anlegen.
3. `ha_loxone_bridge.yaml` nach `packages/` kopieren.
4. **Alte Brücke entfernen**, sonst entstehen doppelte Namen oder zwei Schreiber für denselben Wert:
   - die bisherigen Einträge `loxone_push_ess_soc`, `loxone_push_ess_power`, `loxone_push_ess_soc_max`
     und `loxone_push_ess_soc_min` aus `rest_command.yaml`,
   - den Template-Sensor `Ecoflow ESS Power EHAL` aus `configuration.yaml`,
   - die UI-Automationen aus der EcoFlow-Anleitung (Schritt 4 bis 6), vor allem die beiden, die auf die
     PyLoxone-Entitäten `…delta3_grid_bypass` / `…delta3_p_chargelimit` reagieren.
5. Konfiguration prüfen und HA **neu starten**. HA liest Packages nur beim Start ein.

Die Automationen erscheinen danach unter Einstellungen → Automatisierungen mit dem Präfix
`EcoFlow Delta 3:`. Sie stammen aus der YAML-Datei und lassen sich in der UI nicht bearbeiten.
Änderungen erfolgen immer in der Mapping-Datei, danach wird neu generiert.

### 4. Loxone Config

1. Die Virtuellen Eingänge aus der `Checkliste.md` anlegen (analog, kein Virtueller HTTP-Eingang). Für
   die Telemetrie sind das dieselben Eingänge wie bisher.
2. `VO_HA_Bridge.xml` als Vorlage für einen Virtuellen Ausgang importieren. Die Adresse zeigt auf HA.
3. Die beiden Befehle an die Logik aus der EcoFlow-Anleitung (Schritt 8) anschließen:
   - `HA_Delta3_AcChargeLimit` (analog) an den Ausgang von **F2** (Ladeleistung in W),
   - `HA_Delta3_GridBypass` (digital, Ein `?v=1`, Aus `?v=0`) an den Ausgang von **F3**.

   Am Bypass-Befehl muss die Wiederholung eingeschaltet sein (Beispiel: 10 s). HA wertet ein
   ausbleibendes „Ein“ als „Aus“, siehe [Verhalten im Detail](#verhalten-im-detail).
4. Die alte Strecke abbauen: die Virtuellen Ausgangsbefehle, mit denen der Miniserver
   `Delta3_Grid_ByPass` und `Delta3_P_ChargeLimit` selbst beschrieben hat, sowie diese beiden Eingänge.
5. Speichern und übertragen.

### 5. Testen

- **Webhook direkt:** Im Browser (aus dem Heimnetz) `http://<HA-IP>:<Port>/api/webhook/<id>?v=800`
  aufrufen. `number.<device>_ac_charging_power` muss danach auf 800 stehen. HA begrenzt die Werte auf
  100 bis 1500 W und rundet auf 50 W (`812.000` → 800).
- **Bypass:** In Loxone Config F3 im Online-Monitor zwischen 0 und 1 wechseln.
  `switch.<device>_grid_bypass` muss mitziehen (1 = an = Batteriebetrieb, siehe Polarität in der
  EcoFlow-Anleitung).
- **Telemetrie:** Der SoC-Eingang in Loxone zeigt spätestens nach dem Refresh-Intervall (Beispiel: 5 min)
  den Wert aus HA.
- **Fehlersuche:** Fehler stehen in HA unter Einstellungen → System → Protokolle (Filter `rest_command`
  bzw. `webhook`).

## Verhalten im Detail

- **Wiederholung:** Der Virtuelle Ausgang wiederholt jeden Befehl im Intervall `repeat_seconds`
  (Standard 30 s, Beispiel-Bypass 10 s, 0 = aus). So erreicht HA nach einem Neustart wieder den Sollwert.
  HA schaltet allerdings nur, wenn der Zielwert vom aktuellen Zustand abweicht. Die EcoFlow-Cloud erhält
  also keine Dauer-Schreibzugriffe.
- **HA → Loxone:** HA sendet bei jeder Änderung, beim HA-Start und optional alle `refresh_minutes`
  Minuten (z. B. nach einem Miniserver-Neustart). Nicht-numerische Zustände (`unavailable`, `unknown`)
  sendet HA nicht.
- **Netto-Leistung:** Der Template-Sensor wird `unavailable`, sobald einer der beiden EcoFlow-Sensoren
  fehlt. Loxone erhält dadurch keine falsche 0 (die alte Vorlage rechnete mit `float(0)`).
- **Schalter (Bypass): Ein fehlendes „Ein“ gilt als „Aus“.** Ein digitaler Ausgang wiederholt „Ein“,
  sendet „Aus“ aber nur einmal bei der Flanke (am Miniserver getestet). Die Automation läuft deshalb mit
  `mode: restart`:
  - Jedes „Ein“ startet eine Wartezeit neu (`off_after_seconds`, Standard 3 × Wiederholung,
    Beispiel 30 s).
  - Läuft die Wartezeit ab, schaltet HA aus (beim Bypass: Netz, der sichere Zustand) und schreibt eine
    Warnung ins Protokoll (Logger `ha_loxone_bridge`).
  - Nach einem HA-Start läuft die Wartezeit sofort an. Ein während des Neustarts verpasstes „Aus“ greift
    also trotzdem.

  Earnies Push-Signale folgen derselben Regel.
- **`local_only: true`:** Der Webhook nimmt nur Aufrufe aus dem lokalen Netz an. Für Zugriff von außen
  (nicht empfohlen) `ha.webhook_local_only` auf `false` setzen.

## Grenzen (POC)

- **Analoger Ausgang bei 0:** Ein analoger Virtueller Ausgang sendet bei Wert 0 nichts (kein
  Off-Befehl). Für die Ladeleistung der Delta 3 spielt das keine Rolle (Minimum 100 W), für andere Werte
  schon.
- **Schalter:** Ein Schalter braucht eine Wiederholung > 0 und eine Wartezeit größer als die
  Wiederholung, sonst bricht der Generator ab. Fällt die Verbindung zu HA kurz aus, schaltet der Bypass
  nach der Wartezeit auf Netz und mit dem nächsten „Ein“ wieder zurück.
- **Keine Erkennung:** Der Generator durchsucht weder HA noch Loxone und macht keine Namensvorschläge.
  Die Mapping-Datei wird von Hand gepflegt.
- **HA-Domains:** Unterstützt werden `sensor`, `number`, `input_number` (beide Richtungen, numerisch)
  sowie `switch` und `input_boolean` (nur Loxone → HA).

## Mapping-Datei (Referenz)

| Schlüssel | Bedeutung |
|---|---|
| `title` | Anzeigename, Präfix der Automationen |
| `loxone.host`, `loxone.port` | Miniserver-IP, Port (Standard 80) |
| `loxone.user_secret`, `loxone.pass_secret` | Namen der Einträge in `secrets.yaml` (Standard `loxone_user` / `loxone_pass`) |
| `ha.host`, `ha.port` | HA-IP und Port für den Virtuellen Ausgang (Standard 8123) |
| `ha.webhook_local_only` | Webhooks nur aus dem lokalen Netz (Standard `true`) |
| `derived_sensors[]` | Template-Sensoren: `entity_id`, `name` (muss zur Entity-ID passen), `unit`, `plus[]`, `minus[]`, optional `device_class`, `state_class` |
| `points[].name` | eindeutiger Kurzname (`snake_case`) |
| `points[].direction` | `ha_to_loxone` oder `loxone_to_ha` |
| `points[].ha_entity` | HA-Entity |
| `points[].loxone_input` | nur `ha_to_loxone`: Name des Virtuellen Eingangs |
| `points[].refresh_minutes` | nur `ha_to_loxone`: zusätzliches Senden alle N Minuten (1–59) |
| `points[].webhook_id` | nur `loxone_to_ha`: zufällige Webhook-ID |
| `points[].loxone_cmd_title` | nur `loxone_to_ha`: Titel des Befehls im Virtuellen Ausgang (Standard `HA_<name>`) |
| `points[].min`, `max`, `step` | nur `loxone_to_ha`, numerisch: Begrenzung und Raster |
| `points[].repeat_seconds` | nur `loxone_to_ha`: Wiederholung des Befehls (Standard 30, 0 = aus; Schalter: > 0) |
| `points[].off_after_seconds` | nur Schalter: Wartezeit ohne „Ein“, danach schaltet HA aus (Standard 3 × `repeat_seconds`) |

Unbekannte Schlüssel, doppelte Namen oder Webhook-IDs und nicht unterstützte Domains führen zum Abbruch
mit einer Fehlermeldung.
