# EcoFlow Delta 3 (HA `hassio-ecoflow-cloud`) über Loxone anbinden

Diese Anleitung koppelt eine EcoFlow Delta 3 Powerstation, die über die Community-Integration
[`hassio-ecoflow-cloud`](https://github.com/tolwi/hassio-ecoflow-cloud) in Home Assistant
eingebunden ist, an Earnie — **über den Umweg Loxone Miniserver**. Earnie kommuniziert dabei
weiterhin ausschließlich mit dem Miniserver (`ehal.backend=loxone`, Default); der Miniserver
fungiert als Bridge zu Home Assistant / EcoFlow.

Andere Hubs (HA+evcc direkt, OpenEMS): [Smarthome-Backend wählen](smarthome-backend-wahl.md).
Grundlagen Merker-Namen / Virtual In-Out: [Loxone-Integration](loxone-anbindung.md) ·
[Loxone-Signale und Earnie-Library](../referenz/loxone-signals.md). EHAL-Feldkontrakt:
[`docs/spec/ehal.md`](../spec/ehal.md).

## Einordnung: One-Way-Speicher, kein vollwertiger ESS

Die Delta 3 ist eine **portable Powerstation**, kein netzgekoppelter Hybrid-Wechselrichter. Ohne
ein kompatibles EcoFlow Smart Home Panel (das für Delta 3 laut Herstellerangabe ohnehin nicht
vorgesehen ist — kompatibel sind Delta Pro / Delta Pro 3 / Delta Pro Ultra X) hängt ihr AC-Ausgang
nicht am Hausstromkreis, sondern nur an direkt angeschlossenen Verbrauchern. Sie wird deshalb in
Earnie als **One-Way-Speicher** geführt (Backlog: [Backlog.md](../../backlog/Backlog.md) §„Enable
multiple isolated battery … One-Way storage type“):

- **auf Kommando ladbar** (AC-Ladeleistung begrenzbar)
- **nicht auf Kommando entladbar** (keine erzwingbare Entladeleistung über die HA-Integration)
- **speist nicht ins Hausnetz zurück**
- an ihr angeschlossene Verbraucher können zwischen **Netz-Pass-Through** und **reinem
  Batteriebetrieb** umgeschaltet werden (`switch.<device>_grid_bypass`)

### Was heute in Earnie nutzbar ist

| EHAL-Feld | Status |
|---|---|
| `sens_ess_soc`, `sens_ess_power` | ✅ heute nutzbar (reine Telemetrie/Anzeige) |
| `set_ess_charge_power_limit` | ✅ heute nutzbar (bestehendes EHAL-Feld) |
| `set_ess_source_select` *(neu, Backlog-Vorschlag)* | 🔜 Merker/Bridge lässt sich vorbereiten, Earnie schreibt/nutzt das Feld aber erst nach Umsetzung des Backlog-Punkts |
| `set_ess_active_power`, `set_ess_discharge_power_limit`, `set_ess_mode` | ❌ nicht anlegen/mappen — für einen One-Way-Speicher grundsätzlich nicht zutreffend |

**Konsequenz für `components.json`:** Solange `batteries[].direction: one_way` in der MILP noch
nicht berücksichtigt wird, würde Earnie die Delta 3 sonst wie einen normalen bidirektionalen
Speicher einplanen — inklusive Entlade-Fahrplan, der physisch nie ankommt, weil es keinen echten
Entlade-Befehl gibt. Nehmt die Delta 3 deshalb **vorerst nicht** als optimierten Batterie-Eintrag
in `components.json` → `batteries[]` auf. Bindet nur `sens_ess_soc` / `sens_ess_power` zur
Anzeige, ohne sie der MILP als disponible Kapazität zu übergeben.

## Architektur

```
Earnie ──HTTP jdev/sps/io (bestehend)──► Loxone Miniserver ◄──HTTP push (neu)── Home Assistant ◄──EcoFlow Cloud MQTT── Delta 3
   ▲                                            │                                      │
   └────────── main.py liest/schreibt ──────────┘                                      └── hassio-ecoflow-cloud Integration
```

Zwei neue, rein HTTP-basierte Bridge-Strecken (kein zusätzlicher MQTT-Broker nötig):

- **HA → Loxone** (Telemetrie: SoC, Leistung): HA `rest_command` + Automationen schreiben in neue
  Loxone **Virtual HTTP Inputs**.
- **Loxone → HA** (Sollwerte: Ladelimit, Quellenwahl): Loxone **Virtual Output** ruft einen
  HA-**Webhook** auf, der den passenden HA-Service auf der Ecoflow-Entity aufruft.

Earnies eigene Anbindung bleibt unverändert auf `ehal.backend=loxone`.

## Mapping-Tabelle

| EHAL-Feld | Ecoflow-Entity (interner Key) | Loxone-Merker | Richtung | In Earnie mappen? |
|---|---|---|---|---|
| `sens_ess_soc` | `sensor.<device>_main_battery_level` (`bms_batt_soc`) | `Earnie_Batterie_SoC` | HA → Loxone | ✅ (Anzeige only) |
| `sens_ess_power` | Template-Sensor aus `pow_out_sum_w − pow_in_sum_w` | `Earnie_Batterie_Leistung` | HA → Loxone | ✅ (Anzeige only) |
| `set_ess_charge_power_limit` | `number.<device>_ac_charging_power` (`plug_in_info_ac_in_chg_pow_max`, 100–1500 W) | `Earnie_LadeLeistungs-Limit` | Loxone → HA | ✅ |
| `set_ess_source_select` *(Backlog, noch nicht implementiert)* | `switch.<device>_grid_bypass` (`ban_bypass_en`) | `Earnie_Speicher_Quellenwahl` | Loxone → HA | 🔜 sobald verfügbar |
| `set_ess_discharge_power_limit`, `set_ess_active_power`, `set_ess_mode` | – | – | – | ❌ nicht anlegen |

**Polarität `set_ess_source_select` ↔ `switch.<device>_grid_bypass`:** 1:1-Abbildung, kein
Invertieren nötig — EHAL `1` (battery) = Switch **ON** = „grid bypass disabled“ = Speicher läuft
standalone (kein AC-Laden, Verbraucher exklusiv aus Batterie); EHAL `0` (grid) = Switch **OFF** =
„grid bypass enabled“ = Speicher lädt aus AC-Eingang, Verbraucher im Pass-Through vom Netz. Der
interne EcoFlow-Feldname (`ban_bypass_en`, „Disable Grid Bypass“) ist selbst gegenläufig benannt —
das ist nur eine Doku-Falle, kein Bug (verifiziert gegen `hassio-ecoflow-cloud`,
`switch.py::BypassBanScalarSwitch`).

## Bevor ihr beginnt: Home-Assistant-Grundlagen für diese Anleitung

Diese Anleitung setzt drei HA-Techniken ein, die über die normale Klick-Oberfläche hinausgehen.
Kurz erklärt, damit die folgenden Schritte nicht wie „Zauberei“ wirken:

- **Entity / `entity_id`:** Jeder Sensor, Schalter, Zahlenwert usw. in HA ist eine „Entität“ mit
  einer eindeutigen ID der Form `domain.name`, z. B. `sensor.delta_3_haupt_batteriestand` oder
  `switch.delta_3_grid_bypass`. `sensor.`, `number.`, `switch.` am Anfang zeigen den **Typ** (die
  „Domain“), der Rest ist der **Gerätename**, den die Integration beim Einrichten vergeben hat —
  bei euch vermutlich nicht `<device>`, sondern z. B. `delta_3` oder ähnlich. Diese IDs müsst ihr
  einmalig **selbst ablesen** (Schritt 1) und danach überall in dieser Anleitung anstelle von
  `<device>` einsetzen.
- **`configuration.yaml`:** Die zentrale Textdatei, in der Home Assistant Dinge konfiguriert, die
  sich nicht über die Oberfläche einrichten lassen — hier landet nur noch der YAML-Block aus
  Schritt 2 (Template-Sensor) und Schritt 4 (`rest_command`). Ihr braucht einen Weg, diese Datei zu
  **bearbeiten**:
  - Am einfachsten über das Add-on **„File editor“** (Einstellungen → Add-ons → Add-on Store →
    „File editor“ installieren und starten; erscheint danach als Icon in der linken Seitenleiste).
  - Alternativ **„Studio Code Server“** (VS-Code im Browser) oder Zugriff per Samba/SSH, falls
    ihr das schon nutzt.
  - Falls in eurem HA noch keine `configuration.yaml`-Bearbeitung stattgefunden hat: die Datei
    existiert bereits (HA legt sie beim Ersteinrichten an), ihr müsst sie nur öffnen und am Ende
    ergänzen — nicht neu anlegen.
- **Automationen: über die Oberfläche anlegen, nicht in `configuration.yaml`.** Anders als beim
  Template-Sensor und `rest_command` legt ihr die vier Automationen dieser Anleitung **nicht**
  händisch in `configuration.yaml` an. Grund: In den meisten HA-Installationen existiert dort schon
  ein `automation:`-Eintrag (Standard: `automation: !include automations.yaml`), und ein zweiter,
  von Hand ergänzter `automation:`-Block führt schnell zu Konflikten (doppelte Schlüssel,
  Schema-Fehler wie „not a valid option at 'automation'“). Stattdessen:
  1. **Einstellungen → Automatisierungen & Szenen** → Tab „Automatisierungen“ → **„+ Automatisierung
     erstellen“** → **„Leere Automatisierung erstellen“**.
  2. Oben rechts die drei Punkte (⋮) → **„In YAML bearbeiten“**.
  3. Vorgeschlagenen Platzhalterinhalt löschen und den YAML-Block aus der jeweiligen Anleitungsstelle
     einfügen — **ohne** die umschließende `automation:`-Zeile und **ohne** den führenden
     Listenstrich (`- `) vor `alias:` (die Codeblöcke in dieser Anleitung sind absichtlich schon in
     genau diesem einfügefertigen Format).
  4. Oben rechts speichern (Diskettensymbol). Fertig — kein Neustart, kein Neu-Laden nötig, die UI
     übernimmt das sofort.
  5. Für jede weitere Automation (Schritt 4 hat zwei, Schritt 5 und 6 je eine) denselben Ablauf
     wiederholen.
- **Ändern übernehmen (für `configuration.yaml`-Änderungen: Template-Sensor, `rest_command`):**
  1. **Entwicklerwerkzeuge → YAML** (oder **Einstellungen → System → Wartung**) → Button
     **„Konfiguration prüfen“** — meldet Syntaxfehler, ohne etwas zu übernehmen.
  2. Ist die Prüfung grün: gezielt **„REST-Befehle neu laden“** bzw. **„Vorlage neu laden“**, oder
     bei Unsicherheit **Einstellungen → System → Neu starten** (wirkt immer, dauert aber länger).
- **Automation / `rest_command` / Webhook:** Eine **Automation** ist eine „Wenn X passiert, dann
  tue Y“-Regel. Ein **`rest_command`** ist eine wiederverwendbare, benannte HTTP-Anfrage, die eine
  Automation als „Y“ aufrufen kann. Ein **Webhook** ist eine feste, geheime URL, unter der HA von
  außen (hier: vom Loxone Miniserver) angestoßen werden kann — ihr müsst dafür nichts freischalten,
  die Webhook-ID in der URL ist bereits der Zugriffsschutz.
- **Schreibweise `triggers:`/`actions:`:** Seit Home Assistant 2024.10 heißen die Automation-Schlüssel
  `triggers`/`actions`/`conditions` (Mehrzahl) statt `trigger`/`action`/`condition`, und innerhalb
  eines Triggers heißt das frühere Feld `platform:` jetzt `trigger:`, innerhalb einer Aktion heißt
  `service:` jetzt `action:`. Alle Codeblöcke in dieser Anleitung nutzen bereits die neue Schreibweise.
  Die Jinja-Variable `{{ trigger.to_state.state }}` innerhalb eines Templates bleibt davon unberührt
  — das ist ein anderer `trigger` (die Laufzeit-Variable, nicht der Konfigurationsschlüssel).

## Schritt für Schritt

### 1. HA-Entity-IDs ermitteln

Ja — das müsst ihr **selbst nachschauen**, `<device>` ist in dieser Anleitung nur ein Platzhalter
für den Gerätenamen, den eure Delta 3 bei der Ersteinrichtung von `hassio-ecoflow-cloud` bekommen
hat. Zwei gleichwertige Wege:

**Weg A — über die Geräteseite (übersichtlicher):**

1. **Einstellungen → Geräte & Dienste → Geräte** (oben in der Leiste).
2. Nach „Delta 3“ / „EcoFlow“ suchen, das Gerät anklicken.
3. Unten auf der Geräteseite erscheint eine Liste **„Entitäten“** — jede Zeile zeigt Anzeigename
   und in Klammern/beim Anklicken die tatsächliche `entity_id`.

**Weg B — über Entwicklerwerkzeuge (findet auch versteckte/deaktivierte Entitäten):**

1. Links in der Seitenleiste **Entwicklerwerkzeuge** (Symbol mit Schraubenschlüssel) öffnen, Tab
   **„Zustände“**.
2. Oben im Feld „Entität“ `ecoflow` oder euren Gerätenamen eintippen — die Tabelle filtert live.
3. In der Spalte **„Entität“** stehen die kompletten `entity_id`-Werte.

Sucht und notiert euch diese vier — die tatsächlichen Namen ersetzen ab jetzt überall `<device>`:

| Gesucht | Erkennbar an (Anzeigename in HA) | Beispiel-`entity_id` |
|---|---|---|
| Battery-Level-Sensor | „… Main Battery Level“ / „Hauptbatteriestand“ | `sensor.delta_3_main_battery_level` |
| Total-In-Power-Sensor | „… Total In Power“ | `sensor.delta_3_total_in_power` |
| Total-Out-Power-Sensor | „… Total Out Power“ | `sensor.delta_3_total_out_power` |
| AC-Charging-Power (Zahlenfeld) | „… AC Charging Power“ | `number.delta_3_ac_charging_power` |
| Grid-Bypass-Schalter | „… Grid Bypass“ | `switch.delta_3_grid_bypass` |

Der Teil vor dem ersten `_` nach dem Punkt (bei euch statt `delta_3` eventuell ein anderer Name,
je nachdem wie das Gerät in HA benannt wurde) ist überall identisch — sobald ihr ihn einmal kennt,
könnt ihr die restlichen Entity-IDs meist direkt ableiten, solltet sie aber trotzdem einzeln in
der Zustände-Tabelle gegenprüfen, falls HA abweichende Bezeichnungen vergeben hat.

### 2. Template-Sensor für die Netto-Batterieleistung

**Wozu das gut ist:** EHAL will ein einziges Leistungssignal `sens_ess_power` (positiv =
Entladung, negativ = Ladung). Die EcoFlow-Integration liefert aber **zwei getrennte** Sensoren —
„Total In Power“ (was reinfließt) und „Total Out Power“ (was rausfließt) — keinen fertigen
„Netto“-Wert. Ein **Template-Sensor** ist ein selbst definierter, virtueller Sensor, dessen Wert
HA aus einer Formel über andere Entitäten berechnet; hier: „Out minus In“. Nach dem Einspielen
erscheint er als ganz normale neue Entität `sensor.ecoflow_ess_power_ehal` in HA (prüfbar über
Entwicklerwerkzeuge → Zustände), die ihr in Schritt 4 wie jeden anderen Sensor weiterverwenden
könnt.

**Wo das hingehört:** in eure `configuration.yaml` (siehe Grundlagen-Abschnitt oben zum Bearbeiten
und Übernehmen). Ersetzt `<device>` durch euren in Schritt 1 ermittelten Gerätenamen:

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
starten. Kontrolle: `sensor.ecoflow_ess_power_ehal` muss danach in Entwicklerwerkzeuge → Zustände
auftauchen und einen Zahlenwert zeigen (0, solange nichts lädt/entlädt).

### 3. Neue Virtuelle HTTP-Eingänge in Loxone Config anlegen

**Zweistufiger Aufbau:** Virtuelle Eingänge sind in Loxone Config immer zweistufig — zuerst legt
ihr **ein** übergeordnetes Gerät „Virtueller HTTP-Eingang" an, danach fügt ihr darunter für **jeden
einzelnen Wert** einen eigenen „Virtueller HTTP-Eingang Befehl" hinzu. Erst diese Befehle werden zu
den eigentlichen, per Titel ansprechbaren Merkern.

**Warum das übergeordnete Gerät hier keine aktive Abfrage macht:** Ein „Virtueller HTTP-Eingang"
kann grundsätzlich auch aktiv eine URL abfragen (Loxone holt sich den Wert periodisch selbst). Das
würde sich anbieten, um direkt bei Home Assistant abzufragen — funktioniert hier aber nicht: HAs
REST-API verlangt zwingend einen `Authorization: Bearer <Token>`-Header, und Virtuelle
HTTP-Eingänge können laut Loxone keine eigenen HTTP-Header mitschicken (nur Virtuelle **Ausgänge**
können das, siehe Schritt 5/6). Deshalb bleibt es beim **Push**: Home Assistant schreibt die Werte
aktiv in die Merker (Schritt 4) — das übergeordnete Gerät braucht dafür keine funktionierende
Abfrage-Adresse, nur die Befehle darunter müssen mit den richtigen Titeln existieren.

**Schritte in Loxone Config:**

1. Im Peripherie-Baum: **Peripherie → Virtueller Eingang → Virtueller HTTP-Eingang** hinzufügen
   (Menüpfad kann je nach Loxone-Config-Version leicht abweichen, z. B. Rechtsklick auf den
   Miniserver im Baum → „Peripheriegerät hinzufügen").
2. Titel vergeben, der auf die Quelle hinweist, z. B. `HA_Ecoflow_Bridge`. Falls der Dialog ein
   Adressfeld verlangt: dort informativ die HA-Host-Adresse eintragen (z. B.
   `http://<HA-Host>:8123`) — funktional wird sie hier nicht ausgewertet, da wir nicht abfragen,
   aber leer lassen akzeptieren manche Loxone-Config-Versionen nicht. Ein Abfrageintervall könnt
   ihr auf einen hohen Wert stellen oder ignorieren.
3. Unter diesem neuen Gerät zwei „Virtueller HTTP-Eingang Befehl" (Rechtsklick auf das Gerät →
   Befehl hinzufügen, oder Plus-Symbol) anlegen:
   - Titel `Earnie_Batterie_SoC`, Feld „Befehlserkennung" / „Command Recognition": `\v`
   - Titel `Earnie_Batterie_Leistung`, Befehlserkennung: `\v`
4. Kontrolle: Beide Befehle erscheinen als eigene Zeilen unter dem Gerät im Peripherie-Baum — ihre
   **Titel** sind ab jetzt die Merkernamen, die Home Assistant in Schritt 4 per HTTP beschreibt.
5. Programm speichern und auf den Miniserver übertragen (Speichern-Symbol bzw. „Speichern und alle
   Programme übertragen").

Falls euch das Anlegen über den Dialog zu fummelig ist: alternativ eine der bestehenden
Earnie-Vorlagen aus `share/loxone/templates/VirtualIn/` (z. B. `VI_Earnie_Consumer.xml`, hat
bereits die passende zweistufige Struktur mit zwei Befehlen) importieren und Titel sowie
`EARNIE_HOST`-Platzhalter entsprechend umbenennen/anpassen — siehe
[Loxone-Signale und Earnie-Library](../referenz/loxone-signals.md#library-setup) für den generellen
Import-Ablauf.

### 4. HA `rest_command` + Automationen zum Pushen der Telemetrie

**Wozu das gut ist:** Jetzt sollen die beiden Werte aus Schritt 1/2 (SoC, Netto-Leistung) laufend
zum Loxone Miniserver geschickt werden, in die Virtual-HTTP-Input-Merker aus Schritt 3. Das
passiert in zwei Teilen, die beide in dieselbe `configuration.yaml` kommen wie Schritt 2:

- Ein **`rest_command`**: eine benannte „Vorlage“ für einen HTTP-Aufruf (URL + Zugangsdaten), die
  man später per Name aufrufen kann, ohne die URL jedes Mal neu zu schreiben.
- Eine **`automation`**: die Regel „immer wenn sich der Sensorwert ändert, rufe den `rest_command`
  mit diesem Wert auf“.

**Vorbereitung — feste Werte statt Platzhalter einsetzen:**

- Ersetzt `{{ states('input_text.loxone_ip') }}` unten direkt durch die IP-Adresse eures
  Miniservers, z. B. `192.168.178.10` (der `input_text`-Platzhalter war nur ein Beispiel für „falls
  ihr die IP schon irgendwo als Helper gepflegt habt“ — für den Einstieg reicht eine feste IP).
- `!secret loxone_user` / `!secret loxone_pass` lesen Benutzername/Passwort aus HAs eigener
  Geheimnis-Datei `secrets.yaml` (liegt im selben Verzeichnis wie `configuration.yaml`, mit dem
  gleichen Editor bearbeitbar). Dort ergänzen:

  ```yaml
  loxone_user: "ha-earnie"
  loxone_pass: "euer-passwort"
  ```

  Alternativ könnt ihr Benutzername/Passwort auch direkt in Anführungszeichen statt `!secret ...`
  eintragen — `secrets.yaml` ist nur die sauberere Variante, damit Zugangsdaten nicht offen in
  `configuration.yaml` stehen. Nutzt idealerweise eine eigene, eingeschränkte
  Miniserver-Benutzerkennung für HA statt der `LOXONE_USER`/`LOXONE_PASS`-Zugangsdaten aus Earnies
  `.env`.

**`rest_command` einfügen:** ans Ende eurer `configuration.yaml` (oder in einen bestehenden
`rest_command:`-Block, siehe Grundlagen-Abschnitt oben zum Zusammenführen):

```yaml
rest_command:
  loxone_push_ess_soc:
    url: "http://192.168.178.10/jdev/sps/io/Earnie_Batterie_SoC/{{ value }}"
    username: !secret loxone_user
    password: !secret loxone_pass
  loxone_push_ess_power:
    url: "http://192.168.178.10/jdev/sps/io/Earnie_Batterie_Leistung/{{ value }}"
    username: !secret loxone_user
    password: !secret loxone_pass
```

Konfiguration prüfen → **„REST-Befehle neu laden“** (oder HA neu starten).

**Automationen anlegen:** über die HA-Oberfläche, wie im Grundlagen-Abschnitt oben beschrieben
(Automatisierung erstellen → „In YAML bearbeiten“) — **zweimal**, einmal je Block. `<device>`
jeweils durch euren echten Gerätenamen aus Schritt 1 ersetzen:

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

**Test:** Am Miniserver in der Loxone-App oder per Browser
`http://<Miniserver-IP>/jdev/sps/io/Earnie_Batterie_SoC` aufrufen (Basic-Auth-Login mit euren
Loxone-Zugangsdaten) — der Wert sollte kurz nach der nächsten SoC-Änderung in HA dort ankommen.
Schneller Testauslöser ohne auf eine echte Zustandsänderung zu warten: in HA
**Entwicklerwerkzeuge → Aktionen** die Aktion `rest_command.loxone_push_ess_soc` auswählen, als
Daten `value: 55` eingeben, ausführen, danach den Merker-Wert in Loxone kontrollieren.

### 5. Ladelimit zurückschreiben: Loxone Virtual Output → HA-Webhook

Am bestehenden `Earnie_LadeLeistungs-Limit`-Merker (aus `VI_Earnie_Plant.xml`, siehe
[Loxone-Signale](../referenz/loxone-signals.md)) einen **Virtual Output** ergänzen, der bei
Wertänderung folgende URL aufruft:

```
POST http://<HA-Host>:8123/api/webhook/earnie_charge_limit?v=\v
```

`<HA-Host>` ist die IP oder der Hostname eures Home-Assistant-Systems.

In HA — Automation über die Oberfläche anlegen (siehe Grundlagen-Abschnitt oben: Automatisierung
erstellen → „In YAML bearbeiten“), Inhalt einfügen:

```yaml
alias: "Earnie -> Ecoflow AC-Ladelimit"
triggers:
  - trigger: webhook
    webhook_id: earnie_charge_limit
    allowed_methods: [POST]
    local_only: false
actions:
  - action: number.set_value
    target:
      entity_id: number.<device>_ac_charging_power
    data:
      value: "{{ (trigger.query.v | int(1500)) | max(100) | min(1500) }}"
```

Die Webhook-ID wirkt selbst als Geheimnis — kein zusätzlicher Bearer-Token nötig, passt zum
`\v`-Platzhalter-Muster der bestehenden Earnie-VO-Templates.

### 6. Quellenwahl-Merker vorbereiten (Infrastruktur, noch ohne Earnie-Anbindung)

`set_ess_source_select` ist im EHAL-Wireformat noch nicht implementiert (Backlog-Punkt). Die
Bridge lässt sich aber schon heute vorbereiten, damit später nur noch das EHAL-Com-Mapping in
Earnie fehlt.

Virtueller Ausgang am neuen Merker `Earnie_Speicher_Quellenwahl`:

```
POST http://<HA-Host>:8123/api/webhook/earnie_speicher_quelle?v=\v
```

In HA — Automation über die Oberfläche anlegen (wie in Schritt 4/5), direkte 1:1-Abbildung, kein
Invertieren nötig (siehe Polaritäts-Hinweis oben):

```yaml
alias: "Speicher-Quellenwahl -> Ecoflow Grid Bypass"
triggers:
  - trigger: webhook
    webhook_id: earnie_speicher_quelle
    allowed_methods: [POST]
    local_only: false
actions:
  - action: >
      {{ 'switch.turn_on' if (trigger.query.v | int(0)) == 1 else 'switch.turn_off' }}
    target:
      entity_id: switch.<device>_grid_bypass
```

Bis Earnie `set_ess_source_select` tatsächlich schreibt, könnt ihr den Merker
`Earnie_Speicher_Quellenwahl` manuell in Loxone Config beschalten (Taster/Zeitprogramm) oder
unbeschaltet lassen.

### 7. Prüfen und mappen

```powershell
python -m scripts.verify_loxone_setup
```

Danach in Earnie unter **Daemon Control → EHAL-Com → Loxone Structure → EHAL Mapping** nur
`sens_ess_soc`, `sens_ess_power` und `set_ess_charge_power_limit` auf die drei Merker binden.
`Earnie_Speicher_Quellenwahl`, `Earnie_Batterie_Sollleistung`, `Earnie_EntladeLeistungs-Limit` und
`Earnie_Steuerbefehl` bewusst **nicht** mappen.

## Anhang: die komplette `configuration.yaml`-Ergänzung zum Kopieren

Nur noch Template-Sensor (Schritt 2) und `rest_command` (Schritt 4) gehören in
`configuration.yaml` — die vier Automationen legt ihr über die Oberfläche an (siehe
Grundlagen-Abschnitt oben). **Vorher überall** `<device>` und `192.168.178.10` durch eure eigenen
Werte aus Schritt 1 (Entity-IDs) bzw. eure Miniserver-Adresse ersetzen:

```yaml
template:
  - sensor:
      - name: "Ecoflow ESS Power EHAL"
        unique_id: ecoflow_ess_power_ehal
        unit_of_measurement: "W"
        state: >
          {{ (states('sensor.<device>_total_out_power') | float(0))
             - (states('sensor.<device>_total_in_power') | float(0)) }}

rest_command:
  loxone_push_ess_soc:
    url: "http://192.168.178.10/jdev/sps/io/Earnie_Batterie_SoC/{{ value }}"
    username: !secret loxone_user
    password: !secret loxone_pass
  loxone_push_ess_power:
    url: "http://192.168.178.10/jdev/sps/io/Earnie_Batterie_Leistung/{{ value }}"
    username: !secret loxone_user
    password: !secret loxone_pass
```

Dazu in `secrets.yaml` (gleiches Verzeichnis, gleicher Editor):

```yaml
loxone_user: "ha-earnie"
loxone_pass: "euer-passwort"
```

**Falls in eurer `configuration.yaml` schon `template:` oder `rest_command:` vorkommt:** nicht den
ganzen Block oben einfügen, sondern nur die neuen Einträge darunter in den bestehenden Abschnitt
übernehmen. Danach wie gewohnt: Konfiguration prüfen → neu laden / neu starten (siehe
Grundlagen-Abschnitt oben). Die vier Automationen (zwei aus Schritt 4, je eine aus Schritt 5 und 6)
legt ihr separat über **Einstellungen → Automatisierungen & Szenen** an, mit den jeweiligen
YAML-Inhalten aus den Kapiteln oben.

## Betriebshinweise

- **Rate-Limits:** Die EcoFlow-Cloud-API limitiert Anfragen — pollt/pusht nicht schneller als alle
  30–60 s; für Earnies 15-Minuten-Schreibzyklus reicht das locker.
- **Gekoppelter Zustand:** `switch.<device>_grid_bypass` steuert Laden **und** Quellenwahl
  gleichzeitig — ein unabhängiges „laden, aber Verbraucher trotzdem aus dem Netz“ oder umgekehrt
  ist mit dieser Integration nicht möglich.
- **Kein Grid-Offset:** Ohne Smart Home Panel zählt die Delta 3 nicht zur Netzbilanz
  (`sens_grid_power_active`) — sie versorgt ausschließlich direkt angeschlossene Verbraucher.
