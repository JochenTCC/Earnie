# EcoFlow Delta 3 (HA `hassio-ecoflow-cloud`) über Loxone anbinden

Diese Anleitung koppelt eine EcoFlow Delta 3 Powerstation an Earnie. Die Delta 3 ist über die
Community-Integration [`hassio-ecoflow-cloud`](https://github.com/tolwi/hassio-ecoflow-cloud) in
Home Assistant eingebunden. Earnie erreicht sie **über den Umweg Loxone Miniserver**: Earnie
kommuniziert weiterhin ausschließlich mit dem Miniserver (`ehal.backend=loxone`, Default), der
Miniserver dient als Bridge zu Home Assistant / EcoFlow.

Weiterführende Seiten:

- Andere Hubs (HA+evcc direkt, OpenEMS): [Smarthome-Backend wählen](smarthome-backend-wahl.md)
- Grundlagen Merker-Namen / Virtual In-Out: [Loxone-Integration](loxone-anbindung.md) und
  [Loxone-Signale und Earnie-Library](../referenz/loxone-signals.md)
- EHAL-Feldkontrakt: [`docs/referenz/ehal.md`](../referenz/ehal.md)

## Einordnung: One-Way-Speicher, kein vollwertiger ESS

Die Delta 3 ist eine **portable Powerstation**, kein netzgekoppelter Hybrid-Wechselrichter. Ihr
AC-Ausgang hängt nicht am Hausstromkreis, sondern versorgt nur direkt angeschlossene Verbraucher.
Daran ändert sich nur mit einem kompatiblen EcoFlow Smart Home Panel etwas. Für die Delta 3 ist ein
solches Panel laut Herstellerangabe ohnehin nicht vorgesehen – kompatibel sind Delta Pro / Delta
Pro 3 / Delta Pro Ultra X.

Earnie führt die Delta 3 deshalb als **One-Way-Speicher** (`role: single_use` / Powerstation-Modell).
Die Delta 3 ist:

- **auf Kommando ladbar:** Die AC-Ladeleistung lässt sich begrenzen.
- **nicht auf Kommando entladbar:** Die HA-Integration bietet keine erzwingbare Entladeleistung.
- **ohne Rückspeisung:** Sie speist nicht ins Hausnetz zurück.
- **umschaltbar zwischen Netz und Batterie:** Angeschlossene Verbraucher laufen entweder im
  **Netz-Pass-Through** oder im **reinen Batteriebetrieb** (`switch.<device>_grid_bypass`).

### Was heute in Earnie nutzbar ist

| EHAL-Feld | Status |
|---|---|
| `ess.{id}.sens_ess_soc`, `sens_ess_power` | ✅ heute nutzbar (reine Telemetrie/Anzeige; SoC entity-scoped) |
| `set_ess_charge_power_limit` | ✅ heute nutzbar (bestehendes EHAL-Feld) |
| `ess.<id>.set_ess_source_select` | ✅ Earnie schreibt die Quellenwahl für physisches `role: standby_backup` (entity-scoped); Merker + Bridge zu `switch.<device>_grid_bypass` (nach dem ID-Umzug selbst verdrahten) |
| `set_ess_active_power`, `set_ess_discharge_power_limit`, `set_ess_mode` | ❌ nicht anlegen/mappen – für einen One-Way-Speicher grundsätzlich nicht zutreffend |

**Konsequenz für `components.json`:** Die Delta 3 ist eine Powerstation
(`type: powerstation`, `backing: physical`, `role: single_use` oder später `standby_backup`) und
**keine** Hausbatterie in Szenario-`battery_ids[]`.

- **Anbindung:** über ein manuelles Gerät mit `appliance_recommendation.mode: reserve` und
  `powerstation_id`.
- **Planung:** Die Optimierung (MILP) plant weder Entladen ins Hausnetz noch einen Entlade-Befehl.
- **Laden:** läuft über `ess.{slug}.set_ess_charge_power_limit`.
- **Telemetrie:** `sens_ess_power` kann als Zähler für die Energie pro Lauf dienen.

## Architektur

```
Earnie ◄──VO telemetry / status.json VI──► Loxone Miniserver ◄──HTTP push── Home Assistant ◄──EcoFlow Cloud MQTT── Delta 3
   ▲                                            │                                      │
   └────────── push inbox + status.json ────────┘                                      └── hassio-ecoflow-cloud Integration
```

Zwei neue, rein HTTP-basierte Bridge-Strecken kommen hinzu (kein zusätzlicher MQTT-Broker nötig):

- **HA → Loxone** (Telemetrie: SoC, Leistung): HA `rest_command` + Automationen schreiben in neue
  Loxone **Virtuelle Eingänge**.
- **Loxone → HA** (Sollwerte: Ladelimit, Quellenwahl): Ein Loxone **Virtual Output** ruft einen
  HA-**Webhook** auf, der den passenden HA-Service auf der Ecoflow-Entity aufruft. Für die
  Quellenwahl geht es alternativ ohne Webhook über die Loxone-Integration (PyLoxone) in HA
  (Schritt 6, Variante A).

Earnies eigene Anbindung bleibt unverändert auf `ehal.backend=loxone`.

> **Neu (POC):** Der [Bridge-Generator](ha-loxone-bridge.md) erzeugt Schritt 2 bis 6 aus einer
> Mapping-Datei. Die Richtung Loxone → HA läuft dabei per Webhook statt über PyLoxone und selbst
> beschriebene Virtuelle Eingänge (dort wurden Werte zwischendurch überschrieben). Die
> Webhook-Variante B in Schritt 5 und 6 entspricht dem, was der Generator erzeugt. Schritt 8
> (Logik im Miniserver) bleibt gültig.

## Mapping-Tabelle

| EHAL-Feld | Ecoflow-Entity (interner Key) | Loxone-Merker | Richtung | In Earnie mappen? |
|---|---|---|---|---|
| `ess.{id}.sens_ess_soc` | `sensor.<device>_main_battery_level` (`bms_batt_soc`) | `Earnie_Batterie_SoC` | HA → Loxone | ✅ (nur Anzeige) |
| `sens_ess_power` | Template-Sensor aus `pow_out_sum_w − pow_in_sum_w` | `Earnie_Batterie_Leistung` | HA → Loxone | ✅ (nur Anzeige) |
| `set_ess_charge_power_limit` | `number.<device>_ac_charging_power` (`plug_in_info_ac_in_chg_pow_max`, 100–1500 W) | `Earnie_LadeLeistungs-Limit` | Loxone → HA | ✅ |
| `get_ess_soc_max` (optional) | `number.<device>_max_charge_level` (50–100 %) | `Earnie_Batterie_SOC_Max` | HA → Loxone | optional |
| `get_ess_soc_min` (optional) | `number.<device>_min_discharge_level` (0–30 %) | `Earnie_Batterie_SOC_Min` | HA → Loxone | optional |
| `ess.<id>.set_ess_source_select` | `switch.<device>_grid_bypass` (`ban_bypass_en`) | Pattern-B-Merker (legacy oft `Earnie_Speicher_Quellenwahl`) | Loxone → HA | ✅ bei physischem `standby_backup` |
| `set_ess_discharge_power_limit`, `set_ess_active_power`, `set_ess_mode` | – | – | – | ❌ nicht anlegen |

**Polarität `ess.<id>.set_ess_source_select` ↔ `switch.<device>_grid_bypass`:** Die Abbildung ist
1:1, ein Invertieren ist nicht nötig.

- **EHAL `1` (battery):** Switch **ON** = „grid bypass disabled“. Der Speicher läuft standalone
  (kein AC-Laden, Verbraucher exklusiv aus der Batterie).
- **EHAL `0` (grid):** Switch **OFF** = „grid bypass enabled“. Der Speicher lädt aus dem
  AC-Eingang, die Verbraucher laufen im Pass-Through vom Netz.

Der interne EcoFlow-Feldname (`ban_bypass_en`, „Disable Grid Bypass“) ist selbst gegenläufig
benannt. Das ist nur eine Doku-Falle, kein Bug (verifiziert gegen `hassio-ecoflow-cloud`,
`switch.py::BypassBanScalarSwitch`).

## Vor dem Start: Home-Assistant-Grundlagen für diese Anleitung

Diese Anleitung setzt drei HA-Techniken ein, die über die normale Klick-Oberfläche hinausgehen.
Die folgende Kurzerklärung macht die späteren Schritte nachvollziehbar.

### Entity / `entity_id`

Jeder Sensor, Schalter, Zahlenwert usw. in HA ist eine „Entität“ mit einer eindeutigen ID der Form
`domain.name`, z. B. `sensor.delta_3_haupt_batteriestand` oder `switch.delta_3_grid_bypass`.

- `sensor.`, `number.`, `switch.` am Anfang zeigen den **Typ** (die „Domain“).
- Der Rest ist der **Gerätename**, den die Integration beim Einrichten vergeben hat. In der Praxis
  steht dort statt `<device>` meist z. B. `delta_3` oder ähnlich.

Diese IDs einmalig **selbst ablesen** (Schritt 1) und danach überall in dieser Anleitung anstelle
von `<device>` einsetzen.

### `configuration.yaml` bearbeiten

`configuration.yaml` ist die zentrale Textdatei, in der Home Assistant Dinge konfiguriert, die sich
nicht über die Oberfläche einrichten lassen. Hier landen nur der YAML-Block aus Schritt 2
(Template-Sensor) und aus Schritt 4 (`rest_command`). Zum **Bearbeiten** gibt es mehrere Wege:

- Am einfachsten über das Add-on **„File editor“** (Einstellungen → Add-ons → Add-on Store →
  „File editor“ installieren und starten; es erscheint danach als Icon in der linken Seitenleiste).
- Alternativ **„Studio Code Server“** (VS-Code im Browser) oder Zugriff per Samba/SSH, falls das
  schon im Einsatz ist.
- Wurde `configuration.yaml` bisher nie bearbeitet: Die Datei existiert bereits (HA legt sie beim
  Ersteinrichten an). Sie muss nur geöffnet und am Ende ergänzt werden, nicht neu angelegt.

### Automationen über die Oberfläche anlegen, nicht in `configuration.yaml`

Anders als Template-Sensor und `rest_command` kommen die Automationen dieser Anleitung **nicht**
händisch in `configuration.yaml`. Grund: In den meisten HA-Installationen existiert dort schon ein
`automation:`-Eintrag (Standard: `automation: !include automations.yaml`). Ein zweiter, von Hand
ergänzter `automation:`-Block führt schnell zu Konflikten (doppelte Schlüssel, Schema-Fehler wie
„not a valid option at 'automation'“).

Stattdessen so vorgehen:

1. **Einstellungen → Automatisierungen & Szenen** → Tab „Automatisierungen“ → **„+ Automatisierung
   erstellen“** → **„Leere Automatisierung erstellen“**.
2. Oben rechts die drei Punkte (⋮) → **„In YAML bearbeiten“**.
3. Den vorgeschlagenen Platzhalterinhalt löschen und den YAML-Block aus der jeweiligen
   Anleitungsstelle einfügen. Dabei **ohne** die umschließende `automation:`-Zeile und **ohne** den
   führenden Listenstrich (`- `) vor `alias:` arbeiten. Die Codeblöcke in dieser Anleitung haben
   absichtlich schon genau dieses einfügefertige Format.
4. Oben rechts speichern (Diskettensymbol). Ein Neustart oder Neu-Laden ist nicht nötig, die UI
   übernimmt die Automation sofort.
5. Für jede weitere Automation (Schritt 4 hat zwei, Schritt 5 und 6 je eine) denselben Ablauf
   wiederholen.

### Die Dateien `automations.yaml`, `scripts.yaml`, `scenes.yaml`

Diese drei Dateien binden die meisten HA-Installationen per `!include` in `configuration.yaml` ein
(z. B. `automation: !include automations.yaml`). Jede gehört fest zu genau einem Eintrag
(`automation:`, `script:`, `scene:`) und ist nur für dessen Inhalt gedacht.

- `rest_command:` und `template:` sind eigene Einträge und gehören **nicht** in diese Dateien.
- Die UI schreibt außerdem selbst in `automations.yaml`. Sie kann fremde Einträge dort
  überschreiben oder die Datei beschädigen (Fehler „response error: 500“ beim Speichern).
- Wer `rest_command` auslagern möchte, nimmt dafür eine eigene Datei (siehe Schritt 4).

### Änderungen übernehmen

Für Änderungen an `configuration.yaml` (Template-Sensor, `rest_command`):

1. **Entwicklerwerkzeuge → YAML** (oder **Einstellungen → System → Wartung**) → Button
   **„Konfiguration prüfen“**. Die Prüfung meldet Syntaxfehler, ohne etwas zu übernehmen.
2. Ist die Prüfung grün: gezielt **„REST-Befehle neu laden“** bzw. **„Vorlage neu laden“**. Bei
   Unsicherheit **Einstellungen → System → Neu starten** (wirkt immer, dauert aber länger).

Ein **Neustart ist nötig**, wenn `rest_command:` oder `template:` zum **ersten Mal** eingeführt
wird. Die Integration ist dann noch nicht geladen, der Neu-laden-Button fehlt oder wirkt nicht.
Spätere Änderungen an den Einträgen selbst lassen sich per Neu-laden übernehmen. Änderungen an
`secrets.yaml` greifen, sobald der Eintrag, der sie nutzt, neu geladen wird.

### Automation, `rest_command`, Webhook

- **Automation:** eine „Wenn X passiert, dann tue Y“-Regel.
- **`rest_command`:** eine wiederverwendbare, benannte HTTP-Anfrage, die eine Automation als „Y“
  aufrufen kann.
- **Webhook:** eine feste, geheime URL, unter der HA von außen (hier: vom Loxone Miniserver)
  angestoßen werden kann. Freischalten muss man dafür nichts, die Webhook-ID in der URL ist bereits
  der Zugriffsschutz.

### Schreibweise `triggers:` / `actions:`

Seit Home Assistant 2024.10 heißen die Automation-Schlüssel `triggers`/`actions`/`conditions`
(Mehrzahl) statt `trigger`/`action`/`condition`. Innerhalb eines Triggers heißt das frühere Feld
`platform:` jetzt `trigger:`, innerhalb einer Aktion heißt `service:` jetzt `action:`. Alle
Codeblöcke in dieser Anleitung nutzen bereits die neue Schreibweise.

Die Jinja-Variable `{{ trigger.to_state.state }}` innerhalb eines Templates bleibt davon unberührt.
Sie ist ein anderer `trigger` (die Laufzeit-Variable, nicht der Konfigurationsschlüssel).

## Schritt für Schritt

### 1. HA-Entity-IDs ermitteln

`<device>` ist in dieser Anleitung nur ein Platzhalter für den Gerätenamen, den die Delta 3 bei der
Ersteinrichtung von `hassio-ecoflow-cloud` bekommen hat. Den tatsächlichen Namen **selbst
nachschauen**. Dafür gibt es zwei gleichwertige Wege.

**Weg A – über die Geräteseite (übersichtlicher):**

1. **Einstellungen → Geräte & Dienste → Geräte** (oben in der Leiste).
2. Nach „Delta 3“ / „EcoFlow“ suchen und das Gerät anklicken.
3. Unten auf der Geräteseite erscheint eine Liste **„Entitäten“**. Jede Zeile zeigt den
   Anzeigenamen und in Klammern bzw. beim Anklicken die tatsächliche `entity_id`.

**Weg B – über die Entwicklerwerkzeuge (findet auch versteckte/deaktivierte Entitäten):**

1. Links in der Seitenleiste **Entwicklerwerkzeuge** (Symbol mit Schraubenschlüssel) öffnen, Tab
   **„Zustände“**.
2. Oben im Feld „Entität“ `ecoflow` oder den Gerätenamen eintippen. Die Tabelle filtert live.
3. In der Spalte **„Entität“** stehen die kompletten `entity_id`-Werte.

Diese vier suchen und notieren. Die tatsächlichen Namen ersetzen ab jetzt überall `<device>`:

| Gesucht | Erkennbar an (Anzeigename in HA) | Beispiel-`entity_id` |
|---|---|---|
| Battery-Level-Sensor | „… Main Battery Level“ / „Hauptbatteriestand“ | `sensor.delta_3_main_battery_level` |
| Total-In-Power-Sensor | „… Total In Power“ | `sensor.delta_3_total_in_power` |
| Total-Out-Power-Sensor | „… Total Out Power“ | `sensor.delta_3_total_out_power` |
| AC-Charging-Power (Zahlenfeld) | „… AC Charging Power“ | `number.delta_3_ac_charging_power` |
| Grid-Bypass-Schalter | „… Grid Bypass“ | `switch.delta_3_grid_bypass` |

Der Teil vor dem ersten `_` nach dem Punkt ist überall identisch. Statt `delta_3` kann dort ein
anderer Name stehen, je nachdem, wie das Gerät in HA benannt wurde. Mit diesem Teil lassen sich die
restlichen Entity-IDs meist direkt ableiten. Trotzdem jede ID einzeln in der Zustände-Tabelle
gegenprüfen, falls HA abweichende Bezeichnungen vergeben hat.

### 2. Template-Sensor für die Netto-Batterieleistung

**Wozu das gut ist:** EHAL erwartet ein einziges Leistungssignal `sens_ess_power` (positiv =
Entladung, negativ = Ladung). Die EcoFlow-Integration liefert dagegen **zwei getrennte** Sensoren:
„Total In Power“ (was hineinfließt) und „Total Out Power“ (was herausfließt). Einen fertigen
„Netto“-Wert gibt es nicht.

Ein **Template-Sensor** ist ein selbst definierter, virtueller Sensor. HA berechnet seinen Wert aus
einer Formel über andere Entitäten, hier „Out minus In“. Nach dem Einspielen erscheint er als ganz
normale neue Entität `sensor.ecoflow_ess_power_ehal` in HA (prüfbar über Entwicklerwerkzeuge →
Zustände). In Schritt 4 lässt er sich wie jeder andere Sensor weiterverwenden.

**Wo das hingehört:** in `configuration.yaml` (zum Bearbeiten und Übernehmen siehe
[Grundlagen](#vor-dem-start-home-assistant-grundlagen-für-diese-anleitung)). `<device>` durch den
in Schritt 1 ermittelten Gerätenamen ersetzen:

```yaml
template:
  - sensor:
      - name: "Ecoflow ESS Power EHAL"
        unique_id: ecoflow_ess_power_ehal
        unit_of_measurement: "W"
        state: >
          {{ (states('sensor.<device>_total_out_power') | float(0))
             - (states('sensor.<device>_total_in_power') | float(0)) }}
```

Danach: Konfiguration prüfen → **„Vorlage neu laden“** (Entwicklerwerkzeuge → YAML) oder HA neu
starten.

**Kontrolle:** `sensor.ecoflow_ess_power_ehal` muss danach in Entwicklerwerkzeuge → Zustände
auftauchen und einen Zahlenwert zeigen (0, solange nichts lädt oder entlädt).

### 3. Virtuelle Eingänge in Loxone Config anlegen

**Welcher Typ?** Pro Wert ist ein normaler **„Virtueller Eingang“** (analog) nötig, **nicht** der
„Virtuelle HTTP-Eingang“. Der Unterschied:

- **Virtueller HTTP-Eingang** (mit Adresse, Abfrageintervall und Befehlen darunter): Er holt sich
  Werte selbst, indem er periodisch eine Webseite oder URL abfragt. Das nutzen die Earnie-Vorlagen
  `VI_Earnie_*.xml`, mit denen Loxone den Status-JSON von Earnie abruft.
  - Für Home Assistant taugt das nicht: HAs REST-API verlangt einen
    `Authorization: Bearer <Token>`-Header, den Virtuelle HTTP-Eingänge nicht mitschicken können.
  - Außerdem sind die Befehle darunter dafür gedacht, Werte aus dem abgerufenen Dokument zu lesen.
    Ein Wert, den HA von außen hineinschreibt, kommt dort nicht an.
- **Virtueller Eingang:** ein reiner Speicherplatz, den ein anderes System per HTTP setzen kann
  (`/dev/sps/io/<Name>/<Wert>`). Genau das macht Home Assistant in Schritt 4 (und Earnie auf
  demselben Weg für seine eigenen Sollwerte).

**Schritte in Loxone Config:**

1. Im Peripherie-Baum unter **Virtuelle Eingänge** einen neuen **Virtuellen Eingang** hinzufügen
   (Rechtsklick auf „Virtuelle Eingänge“ → Virtuellen Eingang hinzufügen; der Menüpfad kann je
   nach Loxone-Config-Version leicht abweichen).
2. Einen Namen vergeben und die Option „Digitaler Eingang“ **deaktiviert** lassen (analoger Wert).
   Der Name ist später Teil der URL in Schritt 4 und muss dort **exakt** gleich geschrieben sein
   (Groß- und Kleinschreibung). Beispiele: `Earnie_Batterie_SoC` und `Earnie_Batterie_Leistung` (die
   Standardnamen aus [Loxone-Signale](../referenz/loxone-signals.md)) oder eigene Namen wie
   `Delta3_Bat_SoC_Act`.
3. Dasselbe für den zweiten Wert wiederholen, also je Wert ein eigener Virtueller Eingang.
4. Beide Eingänge in die Programmseite ziehen, damit sie im Programm vorhanden sind. Dann das
   Programm speichern und auf den Miniserver übertragen („Speichern und alle Programme
   übertragen“).
5. Der Loxone-Benutzer, den HA nutzt (Schritt 4), braucht Schreibrechte auf diese Eingänge.
6. **Kontrolle:** In Loxone Config zeigen die Eingänge im Online-Monitor den Wert 0. Sobald
   Schritt 4 läuft, ändert er sich mit jedem Push aus HA.

Soll Earnie die Werte später als Batterie-Telemetrie lesen, müssen die Namen zu den Merkern passen,
die auf der EHAL-Com-Seite zugeordnet werden (Schritt 7). Eigene Namen lassen sich dort einfach
auswählen.

### 4. HA `rest_command` + Automationen zum Pushen der Telemetrie

**Wozu das gut ist:** Die beiden Werte aus Schritt 1 und 2 (SoC, Netto-Leistung) sollen laufend zum
Loxone Miniserver gelangen, in die Virtuellen Eingänge aus Schritt 3. Das passiert in zwei Teilen,
die beide in dieselbe `configuration.yaml` kommen wie Schritt 2:

- **`rest_command`:** eine benannte „Vorlage“ für einen HTTP-Aufruf (URL + Zugangsdaten). Sie lässt
  sich später per Name aufrufen, ohne die URL jedes Mal neu zu schreiben.
- **`automation`:** die Regel „immer wenn sich der Sensorwert ändert, rufe den `rest_command` mit
  diesem Wert auf“.

**Vorbereitung – feste Werte statt Platzhalter einsetzen:**

- **IP-Adresse statt Hostname:** In den URLs unten die **IP-Adresse** des Miniservers eintragen,
  z. B. `192.168.178.10`, **nicht** seinen Hostnamen (z. B. `miniservergen2`). Läuft HA in einem
  Container, kennt es die Namen aus Router oder PC nicht. Der Aufruf scheitert dann mit
  `Cannot connect to host ...: Timeout while contacting DNS servers`.
- **Zugangsdaten über `secrets.yaml`:** `!secret loxone_user` / `!secret loxone_pass` lesen
  Benutzername und Passwort aus HAs eigener Geheimnis-Datei `secrets.yaml`. Sie liegt im selben
  Verzeichnis wie `configuration.yaml` und lässt sich mit dem gleichen Editor bearbeiten. Dort
  ergänzen:

  ```yaml
  loxone_user: "ha-earnie"
  loxone_pass: "euer-passwort"
  ```

  Alternativ lassen sich Benutzername und Passwort auch direkt in Anführungszeichen statt
  `!secret ...` eintragen. `secrets.yaml` ist nur die sauberere Variante, damit Zugangsdaten nicht
  offen in `configuration.yaml` stehen.
- **Eigener Benutzer:** Idealerweise eine eigene, eingeschränkte Miniserver-Benutzerkennung für HA
  nutzen statt der `LOXONE_USER`/`LOXONE_PASS`-Zugangsdaten aus Earnies `.env`.

**`rest_command` in eigene Datei auslagern:** Die Befehle gehören **nicht** in `automations.yaml`,
`scripts.yaml` oder `scenes.yaml` (siehe Grundlagen oben). Sie kommen in eine eigene Datei, die
`configuration.yaml` einbindet:

1. In `configuration.yaml` eintragen. Einen eventuell schon vorhandenen `rest_command:`-Eintrag
   vorher entfernen, sonst entsteht ein doppelter Schlüssel:

   ```yaml
   rest_command: !include rest_command.yaml
   ```

2. Neue Datei `rest_command.yaml` im selben Ordner wie `configuration.yaml` anlegen, mit diesem
   Inhalt. Die Zeile `rest_command:` entfällt hier, sie steht schon in `configuration.yaml`:

   ```yaml
   loxone_push_ess_soc:
     url: "http://192.168.178.10/jdev/sps/io/Earnie_Batterie_SoC/{{ value }}"
     username: !secret loxone_user
     password: !secret loxone_pass
   loxone_push_ess_power:
     url: "http://192.168.178.10/jdev/sps/io/Earnie_Batterie_Leistung/{{ value }}"
     username: !secret loxone_user
     password: !secret loxone_pass
   ```

3. Konfiguration prüfen → **„REST-Befehle neu laden“** (oder HA neu starten).

**Automationen anlegen:** über die HA-Oberfläche, wie in den Grundlagen oben beschrieben
(Automatisierung erstellen → „In YAML bearbeiten“). Das **zweimal** tun, einmal je Block. `<device>`
jeweils durch den echten Gerätenamen aus Schritt 1 ersetzen:

```yaml
alias: "Ecoflow SoC -> Loxone"
triggers:
  - trigger: state
    entity_id: sensor.<device>_main_battery_level
actions:
  - action: rest_command.loxone_push_ess_soc
    data:
      value: "{{ trigger.to_state.state }}"
```

```yaml
alias: "Ecoflow Leistung -> Loxone"
triggers:
  - trigger: state
    entity_id: sensor.ecoflow_ess_power_ehal
actions:
  - action: rest_command.loxone_push_ess_power
    data:
      value: "{{ trigger.to_state.state }}"
```

**Test:** In der Loxone-App oder per Browser
`http://<Miniserver-IP>/jdev/sps/io/Earnie_Batterie_SoC` aufrufen (Basic-Auth-Login mit den
Loxone-Zugangsdaten). Der Wert sollte kurz nach der nächsten SoC-Änderung in HA dort ankommen.

Schneller geht es ohne Warten auf eine echte Zustandsänderung:

1. In HA **Entwicklerwerkzeuge → Aktionen** öffnen und die Aktion
   `rest_command.loxone_push_ess_soc` auswählen.
2. Als Daten `value: 55` eingeben und ausführen.
3. Den Wert in Loxone kontrollieren (Online-Monitor in Loxone Config).

Die Automationen selbst nicht über „Ausführen“ testen: Ohne echte Zustandsänderung gibt es kein
`trigger.to_state`, und im Protokoll erscheint der harmlose Fehler `'dict object' has no attribute
'to_state'`.

**Fehlersuche:** Fehlermeldungen zu `rest_command` stehen unter **Einstellungen → System →
Protokolle** (Filter `rest_command`).

- `client_error` mit `Cannot connect to host` deutet auf Hostname statt IP oder einen nicht
  erreichbaren Miniserver hin.
- 401/403 deutet auf Benutzer oder Rechte hin.
- 404 deutet auf einen falsch geschriebenen Eingangsnamen hin.

#### Optional: SOC-Grenzen der Delta 3 nach Loxone

Die Delta 3 hat einstellbare Grenzen für den Ladestand (`number.<device>_max_charge_level`,
50 bis 100 %, und `number.<device>_min_discharge_level`, 0 bis 30 %). Earnie kann sie als
`get_ess_soc_max` und `get_ess_soc_min` lesen. Sie laufen wie die anderen Werte von HA nach Loxone:

1. In Loxone Config zwei weitere analoge Virtuelle Eingänge anlegen (Standardnamen
   `Earnie_Batterie_SOC_Max` und `Earnie_Batterie_SOC_Min`; der Name ist frei, z. B.
   `Delta3_SOC_Max`).
2. Zwei weitere Befehle in der `rest_command.yaml` ergänzen (Namen der Eingänge anpassen):

   ```yaml
   loxone_push_ess_soc_max:
     url: "http://192.168.178.10/jdev/sps/io/Earnie_Batterie_SOC_Max/{{ value }}"
     username: !secret loxone_user
     password: !secret loxone_pass
   loxone_push_ess_soc_min:
     url: "http://192.168.178.10/jdev/sps/io/Earnie_Batterie_SOC_Min/{{ value }}"
     username: !secret loxone_user
     password: !secret loxone_pass
   ```

3. Zwei Automationen über die Oberfläche anlegen. Unten steht die Automation für das Maximum, das
   Minimum funktioniert analog mit `min_discharge_level` und `loxone_push_ess_soc_min`. Der zweite
   Trigger sorgt dafür, dass Loxone den Wert auch nach einem HA-Neustart bekommt, ohne dass sich der
   Wert ändern muss:

   ```yaml
   alias: "Ecoflow SOC-Max -> Loxone"
   triggers:
     - trigger: state
       entity_id: number.<device>_max_charge_level
     - trigger: homeassistant
       event: start
   conditions:
     - condition: template
       value_template: "{{ states('number.<device>_max_charge_level') | is_number }}"
   actions:
     - action: rest_command.loxone_push_ess_soc_max
       data:
         value: "{{ states('number.<device>_max_charge_level') | float(0) | round(0) | int }}"
   ```

   Diese Automationen lesen den Wert direkt aus dem `number` und lassen sich deshalb auch über
   „Ausführen“ testen.

### 5. Ladelimit zurückschreiben: Loxone → HA

Wie bei Schritt 6 gibt es zwei Wege: Variante A über die Loxone-Integration (PyLoxone) und
Variante B über einen Webhook. Beide setzen `number.<device>_ac_charging_power`.

#### Variante A: über die Loxone-Integration (PyLoxone)

1. In Loxone Config einen **analogen Virtuellen Eingang** anlegen, z. B. `Delta3_P_ChargeLimit`
   (Wert in Watt). Ins Programm ziehen, speichern, übertragen.
2. Der Miniserver beschreibt diesen Eingang selbst (Umweg wie in Schritt 6). Dazu den Miniserver
   als Gerät für Virtuelle Ausgänge anlegen und darunter einen **analogen** Virtuellen
   Ausgangsbefehl ergänzen:
   - **Befehl bei Ein:** `/dev/sps/io/Delta3_P_ChargeLimit/<v>`.
   - **Platzhalter:** In einem Virtuellen **Ausgang** lautet er `<v>`. `\v` gilt nur im Virtuellen
     Eingang und kommt im Ausgang als Steuerzeichen (0x0B) statt als Wert an.
   - **Name:** Der Name im Befehl muss **exakt** dem Namen des Eingangs entsprechen. Sonst antwortet
     der Miniserver mit 404, und der Wert kommt nicht an.
   - **Zugang:** Das Ausgangs-Gerät braucht die Miniserver-Adresse und die Zugangsdaten eines
     Benutzers mit Schreibrecht.
3. In HA die Loxone-Integration neu laden. Der Eingang erscheint als
   `sensor.<raum>_<eingangsname>`. Hat der Eingang früher anders geheißen, behält die Entität den
   alten Namen (z. B. `sensor.zimmer_jochen_delta3_bat_p_chargelimit`). Maßgeblich ist, was unter
   Einstellungen → Entitäten steht.
4. Automation über die Oberfläche anlegen. Sie begrenzt auf 100 bis 1500 W und rundet auf
   50-W-Schritte (Schrittweite der Integration):

   ```yaml
   alias: "Loxone Ladeleistungs-Limit -> Ecoflow"
   triggers:
     - trigger: state
       entity_id: sensor.<raum>_<eingangsname>
   conditions:
     - condition: template
       value_template: "{{ trigger.to_state.state | is_number }}"
   actions:
     - action: number.set_value
       target:
         entity_id: number.<device>_ac_charging_power
       data:
         value: "{{ [ [ ((trigger.to_state.state | float(0)) / 50) | round(0) * 50, 100 ] | max, 1500 ] | min }}"
   ```

#### Variante B: über einen Webhook

Der Miniserver ruft per **Virtuellem Ausgang** direkt einen Webhook in HA auf. Es gibt keinen
Virtuellen Eingang, den der Miniserver selbst beschreibt, und keine PyLoxone-Verbindung
dazwischen. Der Wert hat also genau einen Schreiber.

**HA-Adresse und Port ermitteln:** Maßgeblich ist die Adresse, unter der sich die HA-Oberfläche im
Browser öffnen lässt. Dasselbe gilt für Schritt 6.

- **Standard:** Port `8123`, also `http://<HA-IP>:8123`.
- **Eigener Port:** Steht in `configuration.yaml` unter `http:` ein anderer `server_port` (z. B.
  `8124`), muss genau dieser Port in der Adresse stehen.
- **Port 80:** Manche Installationen laufen direkt auf Port `80`. Dann entfällt der Port:
  `http://<HA-IP>`.
- **Gegenprobe im Browser:** `http://<HA-IP>:<Port>/api/` muss „401: Unauthorized“ melden – dann
  antwortet die HA-API (ohne Token ist das hier richtig). `ERR_CONNECTION_REFUSED` heißt: Unter
  diesem Port läuft nichts, also falscher Port oder falsche IP.
- **IP statt Hostname:** Immer die **IP-Adresse** nehmen, keinen Hostnamen (der Miniserver löst
  Hostnamen womöglich nicht auf).

**Webhook-ID wählen:** Die ID ist der einzige Zugriffsschutz des Webhooks. Deshalb eine zufällige
ID statt eines sprechenden Namens nehmen, z. B. erzeugt mit
`python -c "import secrets; print(secrets.token_urlsafe(18))"`. In den Beispielen unten steht dafür
`<webhook-id>`.

**In Loxone Config:** Der Aufruf verteilt sich auf **zwei Stellen**, Loxone setzt ihn beim Senden
zusammen:

| Stelle | Inhalt (Beispiel) |
|---|---|
| **Virtueller Ausgang** (das Gerät), Feld „Adresse“ | `http://192.168.178.63` |
| **Virtueller Ausgangsbefehl** darunter, Feld „Befehl bei Ein“ | `/api/webhook/<webhook-id>?v=<v>` |
| ergibt den Aufruf | `http://192.168.178.63/api/webhook/<webhook-id>?v=800.000` |

Ein Virtueller Ausgang kann mehrere Ausgangsbefehle enthalten. Für Home Assistant reicht deshalb
**ein** Ausgang, unter dem alle Befehle hängen (Ladelimit hier, Grid-Bypass aus Schritt 6).

1. Unter **Virtuelle Ausgänge** einen neuen **Virtuellen Ausgang** für Home Assistant anlegen
   (z. B. „Home Assistant“). Adresse: `http://<HA-IP>:<Port>` wie oben ermittelt (bei Port 80 ohne
   `:<Port>`), ohne Pfad und ohne `/` am Ende. Die Zugangsdaten bleiben leer.
2. Diesem Ausgang einen **analogen** Virtuellen Ausgangsbefehl hinzufügen:
   - Befehl bei Ein: `/api/webhook/<webhook-id>?v=<v>`
   - Befehl bei Aus: leer lassen
   - Wiederholung z. B. 30 s, damit HA nach einem Neustart wieder den aktuellen Wert bekommt.

   Der Platzhalter ist `<v>`, nicht `\v` (siehe Schritt 5, Variante A). Loxone sendet den Wert mit
   Dezimalpunkt und drei Nachkommastellen (z. B. `800.000`), die Automation rechnet das um.
3. Den Ausgangsbefehl an den Ausgang von **F2** aus Schritt 8 hängen (Ladeleistung in **Watt**).
   **Nicht** direkt an den Merker `Earnie_LadeLeistungs-Limit` hängen: Der liefert **kW**, aus
   1,5 kW würden in HA sonst 100 W (die Untergrenze). Ohne die Logik aus Schritt 8 gehört eine
   Formel `I1*1000` dazwischen.
4. Speichern und übertragen.

**In HA:** Automation über die Oberfläche anlegen (siehe Grundlagen oben: Automatisierung
erstellen → „In YAML bearbeiten“). `<device>` an beiden Stellen durch den Gerätenamen aus Schritt 1
ersetzen, `<webhook-id>` durch die eigene ID:

```yaml
alias: "Loxone -> Ecoflow AC-Ladelimit"
mode: queued
max: 5
triggers:
  - trigger: webhook
    webhook_id: <webhook-id>
    allowed_methods: [GET]
    local_only: true
conditions:
  - condition: template
    value_template: "{{ trigger.query.v is defined and (trigger.query.v | is_number) }}"
actions:
  - variables:
      target: "{{ [ [ ((trigger.query.v | float) / 50) | round(0) * 50, 100 ] | max, 1500 ] | min }}"
  - condition: template
    value_template: "{{ states('number.<device>_ac_charging_power') | float(none) != target }}"
  - action: number.set_value
    target:
      entity_id: number.<device>_ac_charging_power
    data:
      value: "{{ target }}"
```

Was die Automation macht:

- **Nur gültige Werte:** Fehlt `v` oder ist es keine Zahl, passiert nichts (kein Rückfall auf einen
  festen Wert).
- **Begrenzung und Raster:** 100 bis 1500 W (Bereich der Delta 3), gerundet auf 50 W (Schrittweite
  der Integration): `812.000` → 800, `20` → 100.
- **Schreibt nur bei Änderung:** Die Wiederholung aus Loxone erzeugt keine Dauer-Schreibzugriffe auf
  die EcoFlow-Cloud.
- **`local_only: true`:** Der Webhook nimmt nur Aufrufe aus dem lokalen Netz an. Der Miniserver
  steht im selben Netz, von außen ist der Webhook damit nicht erreichbar.

Die Fehlermeldung „Message malformed: expected 'all' or 'none' at 'actions[0].target.entity_id'“ beim
Speichern heißt: `<device>` wurde nicht ersetzt.

**Test:** Im Browser `http://<HA-IP>:<Port>/api/webhook/<webhook-id>?v=800` aufrufen.
`number.<device>_ac_charging_power` muss danach auf 800 W stehen.

- Die Delta 3 übernimmt den Wert nur, wenn `select.<device>_ac_charging_mode` auf **Custom** steht
  (siehe Schritt 8).
- Ändert sich nichts, zeigt die Ablaufverfolgung (Trace) der Automation, an welcher Stelle sie
  stehen geblieben ist.

### 6. Quellenwahl-Merker (`ess.<id>.set_ess_source_select`)

Earnie schreibt entity-scoped `ess.<id>.set_ess_source_select` für physische Powerstations mit
`role: standby_backup` (status.json-Key gleich dem Pattern-B-Feld).

- **Merker-Name:** frei wählbar (historisch oft `Earnie_Speicher_Quellenwahl`).
- **Nach dem Umzug** von Plant-flach auf entity-scoped muss die Loxone↔HA-Bridge ggf. neu
  verdrahtet werden.
- **Bridge:** Die Strecke Loxone → HA bleibt nötig, solange Earnie auf `ehal.backend=loxone` läuft.

Es gibt zwei Wege, den Schaltzustand zu Home Assistant zu bringen.

**Zuordnung (gilt für beide Varianten, kein Invertieren nötig):**

- **Wert 1 / an:** Schalter `switch.<device>_grid_bypass` **AN** = Bypass aus. Die Batterie läuft
  standalone, es wird **nicht** nachgeladen.
- **Wert 0 / aus:** Schalter **AUS** = Bypass an. Der Ecoflow lädt aus dem Netz **nach**.

#### Variante A: über die Loxone-Integration (PyLoxone), getestet

**Voraussetzung:** In HA ist die Loxone-Integration (PyLoxone) eingerichtet. Sie spiegelt
Loxone-Eingänge als Entitäten in HA, wie es bei den Telemetrie-Eingängen aus Schritt 3 vielleicht
schon zu sehen war. Virtual Output, Webhook und HA-Port sind hier nicht nötig.

1. In Loxone Config einen **Virtuellen Eingang** anlegen. Die Standardbenennung ist
   `Earnie_Speicher_Quellenwahl`, der Name ist aber frei (im Praxistest: `Delta3_Grid_ByPass`).
   Für einen reinen Ein/Aus-Zustand eignet sich ein **digitaler** Eingang. Ins Programm ziehen,
   speichern, auf den Miniserver übertragen.
2. In HA die Loxone-Integration **neu laden** (Einstellungen → Geräte & Dienste → Loxone → Neu
   laden) oder HA neu starten. PyLoxone liest die Eingänge nur beim Verbinden ein.
3. Unter Einstellungen → Entitäten die neue Entität suchen. Ein digitaler Eingang erscheint als
   `binary_sensor.<raum>_<eingangsname>`, ein analoger als `sensor.<raum>_<eingangsname>`.
4. Automation über die Oberfläche anlegen (Automatisierung erstellen → „In YAML bearbeiten“).
   Beispiel für einen digitalen Eingang (`binary_sensor`, Zustände `on` und `off`):

   ```yaml
   alias: "Loxone Grid-Bypass -> Ecoflow"
   triggers:
     - trigger: state
       entity_id: binary_sensor.<raum>_<eingangsname>
   conditions:
     - condition: template
       value_template: "{{ trigger.to_state.state in ['on', 'off'] }}"
   actions:
     - action: >
         {{ 'switch.turn_on' if trigger.to_state.state == 'on' else 'switch.turn_off' }}
       target:
         entity_id: switch.<device>_grid_bypass
   ```

   Die Bedingung blockt `unavailable` und `unknown`. So setzt ein Verbindungsabbruch zu Loxone den
   Schalter nicht versehentlich zurück. Bei einem analogen Eingang (`sensor`, Zahlenwert) die
   Bedingung durch `{{ trigger.to_state.state | is_number }}` ersetzen und die Aktion durch
   `{{ 'switch.turn_on' if (trigger.to_state.state | float(0)) == 1 else 'switch.turn_off' }}`.
5. **Test:** Den Eingang in Loxone Config online auf 1 und wieder auf 0 setzen. Der Schalter in HA
   muss mitziehen. Die Automation nicht über „Ausführen“ testen (dort gibt es kein `to_state`).

> **Hinweis zum Eingang:** Inhaltlich ist der Schaltzustand eine Ausgabe von Loxone nach HA. In der
> Loxone-Welt ist er allerdings ein Virtueller *Eingang*, der sich im Programm nicht als Ausgang
> beschalten lässt. Der Umweg: Der Miniserver schreibt den Eingang selbst, genau wie Home Assistant
> in Schritt 4 Virtuelle Eingänge beschreibt.
>
> Dazu den **Miniserver einmal als Gerät für Virtuelle Ausgänge** anlegen (Adresse: die eigene
> Miniserver-Adresse). Darunter einen neuen **Virtuellen Ausgangsbefehl** ergänzen, der den Eingang
> beschreibt (`/dev/sps/io/<Eingangsname>/<Wert>`, mit den Zugangsdaten eines Benutzers mit
> Schreibrecht). Earnie schreibt Eingänge ohnehin von außen auf demselben Weg, dort ist später kein
> Umweg nötig.

**Grenzen:** Die Variante hängt an der PyLoxone-Verbindung zum Miniserver. Bricht sie ab, kommt der
Schaltbefehl verzögert an – zum Beispiel, wenn eine neue Konfiguration auf den Miniserver übertragen
wird und der Miniserver deshalb neu startet. Die Automation ändert den Schalter erst, wenn die
Verbindung wieder steht und der Eingang einen neuen Zustand meldet.

#### Variante B: über einen Webhook

Diese Variante ist robuster gegenüber Verbindungsabbrüchen der Loxone-Integration und kommt ohne
selbst beschriebenen Virtuellen Eingang aus. Adresse, Port und Webhook-ID wie in Schritt 5,
Variante B (mit einer eigenen, zweiten Webhook-ID).

**In Loxone Config:** Dem Virtuellen Ausgang „Home Assistant“ aus Schritt 5 einen **digitalen**
Virtuellen Ausgangsbefehl hinzufügen („Als Digitalausgang verwenden“ aktiv). Er arbeitet mit festen
Werten statt Platzhalter:

- Befehl bei Ein: `/api/webhook/<webhook-id>?v=1`
- Befehl bei Aus: `/api/webhook/<webhook-id>?v=0`
- Wiederholung: z. B. 10 s – **muss eingeschaltet sein**, siehe unten.

Den Befehl an den Ausgang von **F3** aus Schritt 8 hängen (ohne die Logik direkt an den Merker
`Earnie_Speicher_Quellenwahl`). Ein analoger Ausgang mit `?v=<v>` taugt hier nicht: Bei Wert 0
sendet er gar nichts.

**Ein fehlendes „Ein“ gilt als „Aus“:** Ein digitaler Ausgang wiederholt „Ein“ im eingestellten
Intervall, sendet „Aus“ aber nur **einmal** bei der Flanke (am Miniserver getestet). Geht genau
dieser eine Aufruf verloren, z. B. weil HA gerade neu startet, bliebe die Delta 3 im
Batteriebetrieb. Sie würde nicht nachladen und leerlaufen.

Die Automation wertet deshalb wie Earnie bei den Push-Signalen ein ausbleibendes „Ein“ als „Aus“:
Kommt **30 s** lang (3 × Wiederholung) kein „Ein“, schaltet sie auf Netz und schreibt eine Warnung
ins Protokoll. Genau 10 s wären zu knapp – ein leicht verspäteter Aufruf würde den Bypass kurz aus-
und wieder einschalten.

**In HA:** Automation über die Oberfläche anlegen (wie in Schritt 5), `<device>` an allen Stellen
und `<webhook-id>` ersetzen. Bei anderer Wiederholung `seconds: 30` auf das Dreifache anpassen:

```yaml
alias: "Loxone -> Ecoflow Grid Bypass"
mode: restart
triggers:
  - trigger: webhook
    id: webhook
    webhook_id: <webhook-id>
    allowed_methods: [GET]
    local_only: true
  - trigger: homeassistant
    id: start
    event: start
conditions:
  - condition: template
    value_template: "{{ trigger.id == 'start' or (trigger.query.v is defined and (trigger.query.v | is_number)) }}"
actions:
  - variables:
      want_on: "{{ trigger.id == 'webhook' and (trigger.query.v | float) >= 0.5 }}"
  - if:
      - condition: template
        value_template: "{{ want_on and not is_state('switch.<device>_grid_bypass', 'on') }}"
    then:
      - action: switch.turn_on
        target:
          entity_id: switch.<device>_grid_bypass
  - if:
      - condition: template
        value_template: "{{ want_on or trigger.id == 'start' }}"
    then:
      - delay:
          seconds: 30
      - if:
          - condition: template
            value_template: "{{ is_state('switch.<device>_grid_bypass', 'on') }}"
        then:
          - action: system_log.write
            data:
              level: warning
              logger: ha_loxone_bridge
              message: "Grid Bypass: kein Ein von Loxone seit 30 s, schalte auf Netz"
  - if:
      - condition: template
        value_template: "{{ is_state('switch.<device>_grid_bypass', 'on') }}"
    then:
      - action: switch.turn_off
        target:
          entity_id: switch.<device>_grid_bypass
```

So arbeitet die Automation:

- **`mode: restart`:** Jedes „Ein“ startet die Automation neu und damit auch die 30-s-Wartezeit.
  Solange Loxone „Ein“ wiederholt, läuft die Wartezeit nie ab.
- **„Aus“ von Loxone** (`v=0`): schaltet sofort auf Netz, ohne Wartezeit.
- **Kein „Ein“ mehr** (Aufruf verloren, Verbindung weg): Nach 30 s schaltet die Automation auf Netz
  und schreibt die Warnung (Einstellungen → System → Protokolle, Filter `ha_loxone_bridge`).
- **HA-Neustart:** Der Start-Trigger lässt die Wartezeit sofort laufen. Steht Loxone auf „Ein“,
  kommt innerhalb von 10 s die nächste Wiederholung, und der Bypass bleibt an. Steht Loxone auf
  „Aus“, kommt nichts mehr, und die Automation schaltet nach 30 s auf Netz.
- **Nur bei Änderung:** Geschaltet wird nur, wenn sich der Zustand wirklich ändert.

`v=1` schaltet den Schalter **an** (Batteriebetrieb), `v=0` **aus** (Netz), siehe Zuordnung oben.

**Test:** `http://<HA-IP>:<Port>/api/webhook/<webhook-id>?v=1` im Browser aufrufen. Der Schalter
geht an und nach 30 s ohne weiteren Aufruf wieder aus. Läuft Loxone mit, bleibt er an.

In den Ablaufverfolgungen der Automation (⋮ → Ablaufverfolgungen) erscheint alle 10 s ein neuer
Lauf. HA speichert standardmäßig nur die letzten 5, mehr mit `trace: stored_traces: 20` im YAML der
Automation.

Nach dem Mapping in EHAL-Com schreibt Earnie den Merker im Live-Zyklus. Manuelles Beschalten
(Taster/Zeitprogramm) bleibt für Tests möglich.

### 7. Prüfen und mappen

```powershell
python -m scripts.verify_loxone_setup
```

Danach in Earnie unter **Daemon Control → EHAL-Com → Loxone Structure → EHAL Mapping** nur
`ess.{id}.sens_ess_soc`, `sens_ess_power` und `set_ess_charge_power_limit` auf die drei Merker binden.
`Earnie_Speicher_Quellenwahl`, `Earnie_Batterie_Sollleistung`, `Earnie_EntladeLeistungs-Limit` und
`Earnie_Steuerbefehl` bewusst **nicht** mappen.

Das gilt, solange keine Loxone-Logik nach Schritt 8 dahinter hängt. Mit dieser Logik müssen
`set_ess_mode`, `set_ess_active_power` und `set_ess_charge_power_limit` gemappt sein, damit Earnie
sie schreibt.

### 8. Loxone-Logik: EHAL-Werte auf die Delta 3 umsetzen

Earnie schreibt für einen Speicher heute `set_ess_mode` (Steuerbefehl), `set_ess_active_power`
(Sollleistung) und `set_ess_charge_power_limit` (Lade-Limit). Die Delta 3 kennt davon nur zwei
Zustände: **Netz (Bypass an)** und **Batterie (Bypass aus)**, dazu eine einstellbare AC-Ladeleistung.
Die Logik im Miniserver übersetzt zwischen beiden Welten.

**Voraussetzung für die Ladeleistung:** Die Delta 3 übernimmt den Wert von
`number.<device>_ac_charging_power` nur, wenn `select.<device>_ac_charging_mode` auf **Custom**
(benutzerdefiniert) steht. In „Auto“ bestimmt die Firmware die Leistung selbst, in „Silent“ begrenzt
sie auf einen festen Wert. Das Lade-Limit aus Loxone wirkt sonst nicht.

Das **Lade-Limit** (`set_ess_charge_power_limit`) entscheidet, ob geladen werden darf:

- **Limit `> 0`:** „Laden erlaubt, höchstens mit dieser Leistung“.
- **Limit `0`:** „nicht laden“. Weil die Delta 3 „Netz“ nicht ohne Laden anbietet (mindestens
  100 W), ist „nicht laden“ nur über den Batteriebetrieb zu erreichen.

| Bedingung (von oben nach unten) | Bypass-Eingang (Schritt 6) | AC-Ladeleistung |
|---|---|---|
| Earnie ausgefallen oder Batterieschutz aktiv | `0` Netz | wie unten, mindestens 100 W |
| Steuerbefehl `1` Zwangsladen / Entladesperre | `0` Netz, Verbraucher am Netz, Batterie lädt | `min(Lade-Limit, \|Sollleistung\|)` bei negativer Sollleistung, sonst Lade-Limit |
| Steuerbefehl `2` Zwangsentladen | `1` Batterie, Verbraucher an der Batterie | ohne Bedeutung |
| Steuerbefehl `0` Automatik und Lade-Limit `> 0` | `0` Netz, Batterie lädt höchstens mit dem Limit | Lade-Limit |
| Steuerbefehl `0` Automatik und Lade-Limit `0` | `1` Batterie, kein Laden | ohne Bedeutung |

- **Ladeleistung:** in Watt (Eingang in kW × 1000) und auf 100 bis 1500 W begrenzt, den Bereich der
  Delta 3. Die Schrittweite der Integration ist 50 W. In Modus 0 bleibt die Sollleistung bewusst
  unberücksichtigt, weil der Loxone-Merker sie auch nach einem Moduswechsel behält.
- **Schutz vor leerer Batterie:** Im Batteriebetrieb (Bypass aus) schaltet die Delta 3 bei leerer
  Batterie den AC-Ausgang ab, die angeschlossenen Verbraucher fallen aus. Die Schwelle hängt von
  der **SOC-Untergrenze der Delta 3** ab (`Delta3_SOC_Min` aus Schritt 4). Die Logik wechselt auf
  Netz, sobald der SoC `Untergrenze + 5` erreicht, und geht erst bei `Untergrenze + 10` wieder auf
  Batterie (Hysterese). Ändert sich die Untergrenze in HA, folgt der Schutz automatisch.
- **Earnie ausgefallen:** Meldet die Heartbeat-Überwachung (siehe
  [Earnie-Dead-Man-Fallback](../referenz/loxone-signals.md#earnie-dead-fallback-in-loxone-config))
  „Earnie ausgefallen“, geht die Logik auf Netz.
- **Obergrenze:** Erreicht der SoC die SOC-Obergrenze (`Delta3_SOC_Max`), lädt die Delta 3 auch im
  Netzbetrieb nicht weiter und reicht das Netz nur noch durch. Die Logik muss dafür nichts tun.
- **Grenzen:** Ladeleistung und Quelle sind gekoppelt (siehe oben). Modus 2 liefert nur so viel, wie
  die angeschlossenen Verbraucher ziehen; eine Sollleistung `> 0` wird nicht eingehalten.
- **Entscheidung „Automatik“:** Bei Steuerbefehl `0` und Limit `0` versorgt die Batterie die
  Verbraucher, statt sie am Netz zu lassen. Ist das nicht gewünscht, in der Formel von Baustein F3
  unten den Teil `IF(I2<=0;1;0)` herausnehmen und dort `0` einsetzen. Dann hängt die Delta 3 in
  Automatik immer am Netz und lädt mit mindestens 100 W.

**Umsetzung mit Loxone-Bausteinen:** Die Logik braucht keinen Programmbaustein. Es reichen drei
**Formel**-Bausteine (je vier Eingänge `I1` bis `I4`, Trennzeichen `;`, Funktionen `IF`, `MIN`,
`MAX`) und ein **Schwellwertschalter**. Die Eingangswerte stammen aus:

- den Merkern `Earnie_Steuerbefehl`, `Earnie_Batterie_Sollleistung` (kW) und
  `Earnie_LadeLeistungs-Limit` (kW),
- dem SoC-Eingang (Schritt 3) und der SOC-Untergrenze (Schritt 4),
- dem Signal „Earnie lebt“ (`1` = Heartbeat frisch) aus der Heartbeat-Überwachung.

1. **F1, Formel „SoC-Abstand“.** `I1` = SoC, `I2` = SOC-Untergrenze der Delta 3.

   ```
   I1-I2
   ```

2. **S1, Schwellwertschalter „Batterie frei“.** Eingang `V` = Ausgang von F1. Parameter
   **Von = 10** und **Voff = 5**.
   - Der Ausgang `O` steht auf `1`, sobald der Abstand 10 Prozentpunkte erreicht, und fällt auf
     `0`, wenn er auf 5 oder weniger sinkt. Das ist die Hysterese des Batterieschutzes.
   - Von und Voff sind feste Parameter und lassen sich nicht anschließen. Deshalb rechnet F1 vorher
     den Abstand zur (veränderlichen) Untergrenze aus.
   - Nach einem Neustart des Miniservers steht `O` auf `0` (Netz), solange der Parameter „Rem“
     (Remanenz) nicht gesetzt ist. Den Parameter ungesetzt lassen: Das ist der sichere Zustand.

3. **F2, Formel „Ladeleistung in W“.** `I1` = Steuerbefehl, `I2` = Sollleistung (kW), `I3` =
   Lade-Limit (kW). Das Ergebnis geht an HA (siehe „Ausgänge an HA weitergeben“ unten).

   ```
   MIN(MAX(1000*IF(I1==1;IF(I2<0;MIN(I3;-I2);I3);I3);100);1500)
   ```

   Bedeutung: In Modus 1 gilt bei negativer Sollleistung der kleinere Wert aus Limit und
   `|Sollleistung|`, sonst das Limit; mal 1000 für Watt, begrenzt auf 100 bis 1500 W.

4. **F3, Formel „Bypass“.** `I1` = Steuerbefehl, `I2` = Lade-Limit (kW), `I3` = Ausgang `O` von S1,
   `I4` = Earnie lebt.

   ```
   I3*I4*IF(I1==2;1;IF(I1==0;IF(I2<=0;1;0);0))
   ```

   Das Ergebnis ist `1` (Batterie) nur, wenn die Batterie frei ist (`I3`), Earnie lebt (`I4`) und
   entweder Zwangsentladen (Modus 2) oder Automatik ohne Ladeerlaubnis (Modus 0, Limit 0) gilt.
   Sonst ist es `0` (Netz). Die Multiplikation wirkt wie ein UND.

Alle Werte kommen als Zahl an. Für `I1==2` und `I1==0` müssen die Merker ganze Zahlen liefern, wie
Earnie sie schreibt. Nach dem Speichern hilft der Online-Monitor in Loxone Config: Eingangswerte
setzen und prüfen, ob F2 und F3 die Werte aus der Tabelle oben liefern.

**Ausgänge an HA weitergeben:**

- **Bypass (Ausgang von F3):** schreibt den Virtuellen Eingang aus Schritt 6 über den Umweg des
  Miniservers (Virtueller Ausgangsbefehl auf die eigene Adresse). Die HA-Automation aus Schritt 6
  schaltet den Schalter.
- **AC-Ladeleistung (Ausgang von F2):** geht wie in Schritt 5 an HA, nur mit dem Wert aus der Logik
  statt direkt vom Merker. Der Ausgang von F2 hängt am Virtuellen Ausgangsbefehl, der den Eingang
  `Delta3_P_ChargeLimit` beschreibt (Schritt 5, Variante A), bzw. am Webhook-Ausgang (Variante B).
  Der Wert ist schon in Watt, die Begrenzung in der HA-Automation bleibt als Sicherung bestehen. Der
  Virtuelle Ausgang direkt an `Earnie_LadeLeistungs-Limit` entfällt dann.

Schreibt Earnie `set_ess_source_select`, entfällt die Ableitung aus dem Steuerbefehl. Der Wert wird
direkt als Bypass-Zustand übernommen. Die Logik behält dann nur noch Batterieschutz,
Earnie-ausgefallen-Fallback und die Ladeleistungs-Begrenzung.

## Anhang: die komplette `configuration.yaml`-Ergänzung zum Kopieren

Es sind drei Dateien betroffen:

- `configuration.yaml`: Template-Sensor und `rest_command`-Verweis
- `rest_command.yaml`: die Befehle
- `secrets.yaml`: die Zugangsdaten

Die Automationen (Schritt 4 bis 6) entstehen über die Oberfläche (siehe Grundlagen oben). **Vorher
überall** `<device>` und `192.168.178.10` durch die eigenen Werte ersetzen: die Entity-IDs aus
Schritt 1 bzw. die Miniserver-Adresse.

In `configuration.yaml` (ans Ende):

```yaml
template:
  - sensor:
      - name: "Ecoflow ESS Power EHAL"
        unique_id: ecoflow_ess_power_ehal
        unit_of_measurement: "W"
        state: >
          {{ (states('sensor.<device>_total_out_power') | float(0))
             - (states('sensor.<device>_total_in_power') | float(0)) }}

rest_command: !include rest_command.yaml
```

Neue Datei `rest_command.yaml` (im selben Ordner, ohne die Zeile `rest_command:`):

```yaml
loxone_push_ess_soc:
  url: "http://192.168.178.10/jdev/sps/io/Earnie_Batterie_SoC/{{ value }}"
  username: !secret loxone_user
  password: !secret loxone_pass
loxone_push_ess_power:
  url: "http://192.168.178.10/jdev/sps/io/Earnie_Batterie_Leistung/{{ value }}"
  username: !secret loxone_user
  password: !secret loxone_pass
loxone_push_ess_soc_max:
  url: "http://192.168.178.10/jdev/sps/io/Earnie_Batterie_SOC_Max/{{ value }}"
  username: !secret loxone_user
  password: !secret loxone_pass
loxone_push_ess_soc_min:
  url: "http://192.168.178.10/jdev/sps/io/Earnie_Batterie_SOC_Min/{{ value }}"
  username: !secret loxone_user
  password: !secret loxone_pass
```

In `secrets.yaml` (gleiches Verzeichnis, gleicher Editor):

```yaml
loxone_user: "ha-earnie"
loxone_pass: "euer-passwort"
```

**Falls `configuration.yaml` schon `template:` oder `rest_command:` enthält:**

- Den vorhandenen `rest_command:`-Eintrag durch die `!include`-Zeile ersetzen. Sein Inhalt wandert
  in `rest_command.yaml`.
- Beim `template:`-Block nur den neuen Sensor in den bestehenden Abschnitt übernehmen.

Danach wie gewohnt: Konfiguration prüfen → neu laden / neu starten (siehe Grundlagen oben). Die
Automationen aus Schritt 4, 5 und 6 separat über **Einstellungen → Automatisierungen & Szenen**
anlegen, mit den jeweiligen YAML-Inhalten aus den Kapiteln oben.

## Betriebshinweise

- **Rate-Limits:** Die EcoFlow-Cloud-API limitiert Anfragen. Nicht schneller als alle 30–60 s
  pollen oder pushen; für Earnies 15-Minuten-Schreibzyklus reicht das locker.
- **Gekoppelter Zustand:** `switch.<device>_grid_bypass` steuert Laden **und** Quellenwahl
  gleichzeitig. Ein unabhängiges „laden, aber Verbraucher trotzdem aus dem Netz“ oder umgekehrt
  ist mit dieser Integration nicht möglich.
- **Kein Grid-Offset:** Ohne Smart Home Panel zählt die Delta 3 nicht zur Netzbilanz
  (`sens_grid_power_active`). Sie versorgt ausschließlich direkt angeschlossene Verbraucher.
