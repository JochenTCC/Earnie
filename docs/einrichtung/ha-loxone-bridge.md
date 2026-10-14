# HA ↔ Loxone Bridge-Generator (POC: EcoFlow Delta 3)

> **Status:** Proof of Concept. Generator und Tests sind fertig, der Live-Test am echten Miniserver und an
> der Delta 3 steht noch aus. Bis dahin bleibt die [EcoFlow-Anleitung](ecoflow-delta3-loxone.md) die
> Referenz für die Logik im Miniserver (Schritt 8).

Der Generator unter `tools/ha_loxone_bridge/` erzeugt aus **einer** Mapping-Datei die komplette Brücke
zwischen Home Assistant und dem Loxone Miniserver:

- ein **HA-Package** (`rest_command`, Template-Sensor, Automationen),
- eine **Loxone-Vorlage** für einen Virtuellen Ausgang (`VO_HA_Bridge.xml`),
- eine **Checkliste** mit allem, was in Loxone Config von Hand anzulegen ist.

Er schreibt nichts in ein laufendes HA oder in den Miniserver – es entstehen nur Dateien. Earnie selbst
ist nicht beteiligt (`ehal.backend=loxone` bleibt unverändert).

## Warum ein neuer Weg?

Die bisherige Brücke Loxone → HA (EcoFlow-Anleitung, Schritt 5/6, Variante A) läuft über einen Umweg:
Der Miniserver beschreibt per Virtuellem Ausgang seinen eigenen Virtuellen Eingang, die
Loxone-Integration (PyLoxone) spiegelt ihn nach HA, und eine Automation setzt daraus den EcoFlow-Wert.
Dabei wurde der Eingang zwischendurch mit fremden Werten überschrieben (Ursache noch offen).

Der Generator baut diese Richtung ohne PyLoxone und ohne Virtuellen Eingang:

| Richtung | Weg | Werte (Delta 3) |
|---|---|---|
| HA → Loxone | HA-`rest_command` schreibt einen **Virtuellen Eingang** (`/jdev/sps/io/<Name>/<Wert>`) | SoC, Netto-Leistung, SOC-Max, SOC-Min |
| Loxone → HA | Loxone-**Virtueller Ausgang** ruft einen **HA-Webhook** auf (`/api/webhook/<id>?v=<v>`) | AC-Ladeleistung, Grid-Bypass |

Jeder Wert hat damit genau **einen** Schreiber.

## Schritt für Schritt

### 1. Mapping-Datei anlegen

1. Beispiel kopieren, am besten in den privaten (nicht versionierten) Config-Ordner:

   ```powershell
   New-Item -ItemType Directory -Force earnie_env\config\ha_loxone_bridge
   Copy-Item tools\ha_loxone_bridge\examples\delta3.mapping.json earnie_env\config\ha_loxone_bridge\
   ```

2. Anpassen:
   - `loxone.host` / `ha.host`: **IP-Adressen** (keine Hostnamen, siehe EcoFlow-Anleitung Schritt 4).
   - `ha.port`: der Port, unter dem ihr die HA-Oberfläche im Browser öffnet – Standard `8123`, bei
     manchen Installationen `80`. Gegenprobe: `http://<HA-IP>:<Port>/api/` meldet „401: Unauthorized“;
     `ERR_CONNECTION_REFUSED` heißt falscher Port (Details: EcoFlow-Anleitung, Schritt 5, Variante B).
   - `ha_entity`: die echten Entity-IDs eurer Delta 3 (Entwicklerwerkzeuge → Zustände, Gerätename statt
     `delta_3`).
   - `loxone_input`: Namen der Virtuellen Eingänge im Miniserver (exakte Groß-/Kleinschreibung).
   - `webhook_id`: je Webhook eine **zufällige** ID. Die ID ist der einzige Zugriffsschutz des Webhooks;
     der Generator verweigert IDs mit `CHANGE_ME`. Erzeugen z.B. mit:

     ```powershell
     .venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(18))"
     ```

### 2. Generieren

```powershell
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'
.venv\Scripts\python.exe -m tools.ha_loxone_bridge --mapping earnie_env\config\ha_loxone_bridge\delta3.mapping.json --out-dir earnie_env\config\ha_loxone_bridge\out
```

Ergebnis im Ausgabeordner: `ha_loxone_bridge.yaml`, `VO_HA_Bridge.xml`, `Checkliste.md`. Die XML-Datei
enthält die Webhook-IDs – nicht committen (der Ordner oben ist bereits per `.gitignore` ausgeschlossen).

### 3. Home Assistant

1. In `secrets.yaml` `loxone_user` und `loxone_pass` eintragen (Miniserver-Benutzer mit Schreibrecht auf
   die Virtuellen Eingänge).
2. Packages aktivieren, falls noch nicht geschehen – in `configuration.yaml`:

   ```yaml
   homeassistant:
     packages: !include_dir_named packages
   ```

   und den Ordner `packages/` neben `configuration.yaml` anlegen.
3. `ha_loxone_bridge.yaml` nach `packages/` kopieren.
4. **Alte Brücke entfernen**, sonst gibt es doppelte Namen oder zwei Schreiber:
   - die bisherigen Einträge `loxone_push_ess_soc`, `loxone_push_ess_power`, `loxone_push_ess_soc_max`,
     `loxone_push_ess_soc_min` aus `rest_command.yaml`,
   - den Template-Sensor `Ecoflow ESS Power EHAL` aus `configuration.yaml`,
   - die UI-Automationen aus der EcoFlow-Anleitung (Schritt 4 bis 6) – vor allem die beiden, die auf die
     PyLoxone-Entitäten `…delta3_grid_bypass` / `…delta3_p_chargelimit` reagieren.
5. Konfiguration prüfen, HA **neu starten** (Packages werden nur beim Start eingelesen).

Die Automationen erscheinen danach unter Einstellungen → Automatisierungen mit dem Präfix
`EcoFlow Delta 3:`. Sie kommen aus der YAML-Datei und lassen sich in der UI nicht bearbeiten – Änderungen
immer über die Mapping-Datei und neu generieren.

### 4. Loxone Config

1. Die Virtuellen Eingänge aus der `Checkliste.md` anlegen (analog, kein Virtueller HTTP-Eingang). Für
   die Telemetrie sind das dieselben Eingänge wie bisher.
2. `VO_HA_Bridge.xml` als Vorlage für einen Virtuellen Ausgang importieren. Die Adresse zeigt auf HA.
3. Die beiden Befehle an die Logik aus der EcoFlow-Anleitung (Schritt 8) hängen:
   - `HA_Delta3_AcChargeLimit` (analog) an den Ausgang von **F2** (Ladeleistung in W),
   - `HA_Delta3_GridBypass` (digital, Ein `?v=1`, Aus `?v=0`) an den Ausgang von **F3**.

   Die Wiederholung am Bypass-Befehl muss eingeschaltet sein (Beispiel: 10 s). HA wertet ein
   ausbleibendes „Ein“ als „Aus“, siehe „Verhalten im Detail“.
4. Die alte Strecke abbauen: die Virtuellen Ausgangsbefehle, mit denen der Miniserver
   `Delta3_Grid_ByPass` und `Delta3_P_ChargeLimit` selbst beschrieben hat, und diese beiden Eingänge.
5. Speichern und übertragen.

### 5. Testen

- **Webhook direkt:** Im Browser (aus dem Heimnetz) `http://<HA-IP>:<Port>/api/webhook/<id>?v=800` aufrufen.
  `number.<device>_ac_charging_power` muss auf 800 gehen. Werte werden auf 100 bis 1500 W begrenzt und
  auf 50 W gerundet (`812.000` → 800).
- **Bypass:** in Loxone Config F3 im Online-Monitor zwischen 0 und 1 wechseln, `switch.<device>_grid_bypass`
  muss mitziehen (1 = an = Batteriebetrieb, siehe Polarität in der EcoFlow-Anleitung).
- **Telemetrie:** der SoC-Eingang in Loxone zeigt spätestens nach dem Refresh-Intervall (Beispiel: 5 min)
  den Wert aus HA.
- Fehler stehen in HA unter Einstellungen → System → Protokolle (Filter `rest_command` bzw.
  `webhook`).

## Verhalten im Detail

- **Wiederholung:** Der Virtuelle Ausgang wiederholt jeden Befehl im Intervall `repeat_seconds`
  (Standard 30 s, Beispiel-Bypass 10 s, 0 = aus). Damit kommt HA nach einem Neustart wieder auf den
  Sollwert. HA schaltet aber nur, wenn der Zielwert vom
  aktuellen Zustand abweicht – die EcoFlow-Cloud bekommt also keine Dauer-Schreibzugriffe.
- **HA → Loxone** pusht bei jeder Änderung, beim HA-Start und optional alle `refresh_minutes` Minuten
  (z.B. nach einem Miniserver-Neustart). Nicht-numerische Zustände (`unavailable`, `unknown`) werden nicht
  gesendet.
- **Netto-Leistung:** Der Template-Sensor wird `unavailable`, sobald einer der beiden EcoFlow-Sensoren
  fehlt – es wird also keine falsche 0 an Loxone gemeldet (die alte Vorlage rechnete mit `float(0)`).
- **Schalter (Bypass): fehlendes „Ein“ gilt als „Aus“.** Ein digitaler Ausgang wiederholt „Ein“, sendet
  „Aus“ aber nur einmal bei der Flanke (am Miniserver getestet). Die Automation läuft deshalb mit
  `mode: restart`: Jedes „Ein“ startet eine Wartezeit neu (`off_after_seconds`, Standard 3 ×
  Wiederholung, Beispiel 30 s). Läuft sie ab, schaltet HA aus (beim Bypass: Netz, der sichere Zustand) und
  schreibt eine Warnung ins Protokoll (Logger `ha_loxone_bridge`). Nach einem HA-Start läuft die Wartezeit
  sofort an, ein während des Neustarts verpasstes „Aus“ greift also trotzdem. Das ist dieselbe Regel wie
  bei Earnies Push-Signalen.
- **`local_only: true`:** Der Webhook nimmt nur Aufrufe aus dem lokalen Netz an. Soll er auch von außen
  erreichbar sein (nicht empfohlen), `ha.webhook_local_only` auf `false` setzen.

## Grenzen (POC)

- Ein **analoger** Virtueller Ausgang sendet bei Wert 0 nichts (kein Off-Befehl). Für die Ladeleistung der
  Delta 3 egal (Minimum 100 W), für andere Werte relevant.
- Ein Schalter braucht eine Wiederholung > 0 und eine Wartezeit größer als die Wiederholung, sonst bricht
  der Generator ab. Fällt die Verbindung zu HA kurz aus, schaltet der Bypass nach der Wartezeit auf Netz
  und mit dem nächsten „Ein“ wieder zurück.
- Kein Scan von HA oder Loxone und keine Namensvorschläge – die Mapping-Datei wird von Hand gepflegt.
- Unterstützte HA-Domains: `sensor`, `number`, `input_number` (beide Richtungen numerisch) sowie `switch`,
  `input_boolean` (nur Loxone → HA).

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
| `points[].refresh_minutes` | nur `ha_to_loxone`: zusätzlicher Push alle N Minuten (1–59) |
| `points[].webhook_id` | nur `loxone_to_ha`: zufällige Webhook-ID |
| `points[].loxone_cmd_title` | nur `loxone_to_ha`: Titel des Befehls im Virtuellen Ausgang (Standard `HA_<name>`) |
| `points[].min`, `max`, `step` | nur `loxone_to_ha`, numerisch: Begrenzung und Raster |
| `points[].repeat_seconds` | nur `loxone_to_ha`: Wiederholung des Befehls (Standard 30, 0 = aus; Schalter: > 0) |
| `points[].off_after_seconds` | nur Schalter: Wartezeit ohne „Ein“, danach schaltet HA aus (Standard 3 × `repeat_seconds`) |

Unbekannte Schlüssel, doppelte Namen oder Webhook-IDs und nicht unterstützte Domains brechen mit einer
Fehlermeldung ab.
