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
| `set_ess_source_select` *(2.7.h)* | ✅ Earnie schreibt Quellenwahl für `role: standby_backup`; Merker `Earnie_Speicher_Quellenwahl` + Bridge zu `switch.<device>_grid_bypass` |
| `set_ess_active_power`, `set_ess_discharge_power_limit`, `set_ess_mode` | ❌ nicht anlegen/mappen — für einen One-Way-Speicher grundsätzlich nicht zutreffend |

**Konsequenz für `components.json` (2.7.g):** Die Delta 3 ist eine Powerstation
(`type: powerstation`, `backing: physical`, `role: single_use` oder später `standby_backup`),
**nicht** eine Hausbatterie in Szenario-`battery_ids[]`. Anbindung über ein manuelles Gerät mit
`appliance_recommendation.mode: reserve` und `powerstation_id`. Die MILP plant kein
Hausnetz-Entladen und keinen Entlade-Befehl; Laden läuft über
`ess.{slug}.set_ess_charge_power_limit`. Telemetrie (`sens_ess_power`) kann als Zähler für
Energie-pro-Lauf dienen.

## Architektur

```
Earnie ──HTTP jdev/sps/io (bestehend)──► Loxone Miniserver ◄──HTTP push (neu)── Home Assistant ◄──EcoFlow Cloud MQTT── Delta 3
   ▲                                            │                                      │
   └────────── main.py liest/schreibt ──────────┘                                      └── hassio-ecoflow-cloud Integration
```

Zwei neue, rein HTTP-basierte Bridge-Strecken (kein zusätzlicher MQTT-Broker nötig):

- **HA → Loxone** (Telemetrie: SoC, Leistung): HA `rest_command` + Automationen schreiben in neue
  Loxone **Virtuelle Eingänge**.
- **Loxone → HA** (Sollwerte: Ladelimit, Quellenwahl): Loxone **Virtual Output** ruft einen
  HA-**Webhook** auf, der den passenden HA-Service auf der Ecoflow-Entity aufruft. Für die
  Quellenwahl geht es alternativ ohne Webhook über die Loxone-Integration (PyLoxone) in HA
  (Schritt 6, Variante A).

Earnies eigene Anbindung bleibt unverändert auf `ehal.backend=loxone`.

## Mapping-Tabelle

| EHAL-Feld | Ecoflow-Entity (interner Key) | Loxone-Merker | Richtung | In Earnie mappen? |
|---|---|---|---|---|
| `sens_ess_soc` | `sensor.<device>_main_battery_level` (`bms_batt_soc`) | `Earnie_Batterie_SoC` | HA → Loxone | ✅ (Anzeige only) |
| `sens_ess_power` | Template-Sensor aus `pow_out_sum_w − pow_in_sum_w` | `Earnie_Batterie_Leistung` | HA → Loxone | ✅ (Anzeige only) |
| `set_ess_charge_power_limit` | `number.<device>_ac_charging_power` (`plug_in_info_ac_in_chg_pow_max`, 100–1500 W) | `Earnie_LadeLeistungs-Limit` | Loxone → HA | ✅ |
| `get_ess_soc_max` (optional) | `number.<device>_max_charge_level` (50–100 %) | `Earnie_Batterie_SOC_Max` | HA → Loxone | optional |
| `get_ess_soc_min` (optional) | `number.<device>_min_discharge_level` (0–30 %) | `Earnie_Batterie_SOC_Min` | HA → Loxone | optional |
| `set_ess_source_select` *(2.7.h)* | `switch.<device>_grid_bypass` (`ban_bypass_en`) | `Earnie_Speicher_Quellenwahl` | Loxone → HA | ✅ bei `role: standby_backup` |
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
  Template-Sensor und `rest_command` legt ihr die Automationen dieser Anleitung **nicht**
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
- **Die Dateien `automations.yaml`, `scripts.yaml`, `scenes.yaml`:** Diese drei Dateien binden die
  meisten HA-Installationen per `!include` in `configuration.yaml` ein (z. B.
  `automation: !include automations.yaml`). Jede gehört fest zu genau einem Eintrag
  (`automation:`, `script:`, `scene:`) und ist nur für dessen Inhalt gedacht. `rest_command:` und
  `template:` sind eigene Einträge und gehören **nicht** in diese Dateien. Die UI schreibt
  außerdem selbst in `automations.yaml` und kann fremde Einträge dort überschreiben oder die Datei
  beschädigen (Fehler „response error: 500“ beim Speichern). Wer `rest_command` auslagern möchte,
  nimmt dafür eine eigene Datei (siehe Schritt 4).
- **Ändern übernehmen (für `configuration.yaml`-Änderungen: Template-Sensor, `rest_command`):**
  1. **Entwicklerwerkzeuge → YAML** (oder **Einstellungen → System → Wartung**) → Button
     **„Konfiguration prüfen“** — meldet Syntaxfehler, ohne etwas zu übernehmen.
  2. Ist die Prüfung grün: gezielt **„REST-Befehle neu laden“** bzw. **„Vorlage neu laden“**, oder
     bei Unsicherheit **Einstellungen → System → Neu starten** (wirkt immer, dauert aber länger).
     Ein **Neustart ist nötig**, wenn ihr `rest_command:` oder `template:` zum **ersten Mal**
     einführt (die Integration ist dann noch nicht geladen, der Neu-laden-Button fehlt oder wirkt
     nicht). Spätere Änderungen an den Einträgen selbst lassen sich per Neu-laden übernehmen.
     Änderungen an `secrets.yaml` greifen, sobald der Eintrag, der sie nutzt, neu geladen wird.
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

### 3. Virtuelle Eingänge in Loxone Config anlegen

**Welcher Typ?** Ihr braucht pro Wert einen normalen **„Virtuellen Eingang"** (analog), **nicht**
den „Virtuellen HTTP-Eingang". Der Unterschied:

- Ein **Virtueller HTTP-Eingang** (mit Adresse, Abfrageintervall und Befehlen darunter) holt sich
  Werte selbst, indem er periodisch eine Webseite oder URL abfragt. Das nutzen die Earnie-Vorlagen
  `VI_Earnie_*.xml`, wo Loxone den Status-JSON von Earnie abruft. Für Home Assistant taugt das
  nicht: HAs REST-API verlangt einen `Authorization: Bearer <Token>`-Header, den Virtuelle
  HTTP-Eingänge nicht mitschicken können. Außerdem sind die Befehle darunter dafür gedacht, Werte
  aus dem abgerufenen Dokument zu lesen. Ein Wert, den HA von außen hineinschreibt, kommt dort
  nicht an.
- Ein **Virtueller Eingang** ist ein reiner Speicherplatz, den ein anderes System per HTTP setzen
  kann (`/dev/sps/io/<Name>/<Wert>`). Genau das macht Home Assistant in Schritt 4 (und Earnie auf
  demselben Weg für seine eigenen Sollwerte).

**Schritte in Loxone Config:**

1. Im Peripherie-Baum unter **Virtuelle Eingänge** einen neuen **Virtuellen Eingang** hinzufügen
   (Rechtsklick auf „Virtuelle Eingänge" → Virtuellen Eingang hinzufügen; der Menüpfad kann je
   nach Loxone-Config-Version leicht abweichen).
2. Einen Namen vergeben und die Option „Digitaler Eingang" **deaktiviert** lassen (analoger Wert).
   Der Name ist später Teil der URL in Schritt 4 und muss dort **exakt** (Groß- und Kleinschreibung)
   so geschrieben sein. Beispiele: `Earnie_Batterie_SoC` und `Earnie_Batterie_Leistung` (die
   Standardnamen aus [Loxone-Signale](../referenz/loxone-signals.md)) oder eigene Namen wie
   `Delta3_Bat_SoC_Act`.
3. Dasselbe für den zweiten Wert wiederholen, also je Wert ein eigener Virtueller Eingang.
4. Beide Eingänge in die Programmseite ziehen, damit sie im Programm vorhanden sind, dann das
   Programm speichern und auf den Miniserver übertragen („Speichern und alle Programme
   übertragen").
5. Der Loxone-Benutzer, den HA nutzt (Schritt 4), braucht Schreibrechte auf diese Eingänge.
6. Kontrolle: In Loxone Config im Online-Monitor zeigen die Eingänge den Wert 0. Sobald Schritt 4
   läuft, ändert er sich mit jedem Push aus HA.

Soll Earnie die Werte später als Batterie-Telemetrie lesen, müssen die Namen zu den Merkern passen,
die ihr auf der EHAL-Com-Seite zuordnet (Schritt 7). Verwendet ihr eigene Namen, wählt ihr sie dort
einfach aus.

### 4. HA `rest_command` + Automationen zum Pushen der Telemetrie

**Wozu das gut ist:** Jetzt sollen die beiden Werte aus Schritt 1/2 (SoC, Netto-Leistung) laufend
zum Loxone Miniserver geschickt werden, in die Virtuellen Eingänge aus Schritt 3. Das
passiert in zwei Teilen, die beide in dieselbe `configuration.yaml` kommen wie Schritt 2:

- Ein **`rest_command`**: eine benannte „Vorlage“ für einen HTTP-Aufruf (URL + Zugangsdaten), die
  man später per Name aufrufen kann, ohne die URL jedes Mal neu zu schreiben.
- Eine **`automation`**: die Regel „immer wenn sich der Sensorwert ändert, rufe den `rest_command`
  mit diesem Wert auf“.

**Vorbereitung — feste Werte statt Platzhalter einsetzen:**

- Tragt in den URLs unten die **IP-Adresse** eures Miniservers ein, z. B. `192.168.178.10`, **nicht**
  seinen Hostnamen (z. B. `miniservergen2`). Läuft HA in einem Container, kennt es die Namen aus
  eurem Router/PC nicht, und der Aufruf scheitert mit
  `Cannot connect to host ...: Timeout while contacting DNS servers`.
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

**`rest_command` in eigene Datei auslagern:** Die Befehle gehören **nicht** in `automations.yaml`,
`scripts.yaml` oder `scenes.yaml` (siehe Grundlagen-Abschnitt oben), sondern in eine eigene Datei,
die ihr in `configuration.yaml` einbindet:

1. In `configuration.yaml` eintragen (einen eventuell schon vorhandenen `rest_command:`-Eintrag
   vorher entfernen, sonst gibt es einen doppelten Schlüssel):

   ```yaml
   rest_command: !include rest_command.yaml
   ```

2. Neue Datei `rest_command.yaml` im selben Ordner wie `configuration.yaml` anlegen, mit diesem
   Inhalt — **ohne** die Zeile `rest_command:`, die steht ja schon in `configuration.yaml`:

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
Daten `value: 55` eingeben, ausführen, danach den Wert in Loxone kontrollieren (Online-Monitor in
Loxone Config).

Die Automationen selbst nicht über „Ausführen“ testen: Ohne echte Zustandsänderung gibt es kein
`trigger.to_state`, und im Protokoll erscheint der harmlose Fehler `'dict object' has no attribute
'to_state'`. Fehlermeldungen zu `rest_command` stehen unter **Einstellungen → System → Protokolle**
(Filter `rest_command`). `client_error` mit `Cannot connect to host` deutet auf Hostname statt IP
oder einen nicht erreichbaren Miniserver hin, 401/403 auf Benutzer oder Rechte, 404 auf einen
falsch geschriebenen Eingangsnamen.

#### Optional: SOC-Grenzen der Delta 3 nach Loxone

Die Delta 3 hat einstellbare Grenzen für den Ladestand (`number.<device>_max_charge_level`,
50 bis 100 %, und `number.<device>_min_discharge_level`, 0 bis 30 %). Earnie kann sie als
`get_ess_soc_max` und `get_ess_soc_min` lesen. Sie laufen wie die anderen Werte von HA nach Loxone:

1. In Loxone Config zwei weitere analoge Virtuelle Eingänge anlegen (Standardnamen
   `Earnie_Batterie_SOC_Max` und `Earnie_Batterie_SOC_Min`, der Name ist frei, z. B.
   `Delta3_SOC_Max`).
2. Zwei weitere Befehle in der `rest_command.yaml` (Namen der Eingänge anpassen):

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

3. Zwei Automationen über die Oberfläche (hier einmal für das Maximum, das Minimum analog mit
   `min_discharge_level` und `loxone_push_ess_soc_min`). Der zweite Trigger sorgt dafür, dass Loxone
   den Wert auch nach einem HA-Neustart bekommt, ohne dass sich der Wert ändern muss:

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

Es gibt wie bei Schritt 6 zwei Wege: Variante A über die Loxone-Integration (PyLoxone) und
Variante B über einen Webhook. Beide setzen `number.<device>_ac_charging_power`.

#### Variante A: über die Loxone-Integration (PyLoxone)

1. In Loxone Config einen **analogen Virtuellen Eingang** anlegen, z. B. `Delta3_P_ChargeLimit`
   (Wert in Watt). Ins Programm ziehen, speichern, übertragen.
2. Der Miniserver beschreibt diesen Eingang selbst (Umweg wie in Schritt 6): Miniserver als Gerät
   für Virtuelle Ausgänge anlegen, darunter ein **analoger** Virtueller Ausgangsbefehl. Der
   Befehl bei Ein lautet `/dev/sps/io/Delta3_P_ChargeLimit/\v`. Der Name im Befehl muss **exakt**
   dem Namen des Eingangs entsprechen, sonst antwortet der Miniserver mit 404 und der Wert kommt
   nicht an. Das Ausgangs-Gerät braucht die Miniserver-Adresse und die Zugangsdaten eines Benutzers
   mit Schreibrecht.
3. In HA die Loxone-Integration neu laden. Der Eingang erscheint als
   `sensor.<raum>_<eingangsname>`. Hat der Eingang früher anders geheißen, behält die Entität den
   alten Namen (z. B. `sensor.zimmer_jochen_delta3_bat_p_chargelimit`). Maßgeblich ist, was unter
   Einstellungen → Entitäten steht.
4. Automation über die Oberfläche anlegen. Sie begrenzt auf 100 bis 1500 W und rundet auf 50-W-Schritte
   (Schrittweite der Integration):

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

Am bestehenden `Earnie_LadeLeistungs-Limit`-Merker (aus `VI_Earnie_Plant.xml`, siehe
[Loxone-Signale](../referenz/loxone-signals.md)) einen **Virtual Output** ergänzen, der bei
Wertänderung folgende URL aufruft:

```
GET http://<HA-Host>:8123/api/webhook/earnie_charge_limit?v=\v
```

`<HA-Host>` ist die IP-Adresse eures Home-Assistant-Systems (der Miniserver löst Hostnamen
womöglich nicht auf). **Port:** Standardmäßig läuft HA auf Port `8123`. Habt ihr in der
`configuration.yaml` unter `http:` einen anderen `server_port` eingestellt (z. B. `8124`), muss genau
dieser Port in der URL stehen. Dasselbe gilt für Schritt 6.

In HA — Automation über die Oberfläche anlegen (siehe Grundlagen-Abschnitt oben: Automatisierung
erstellen → „In YAML bearbeiten“), Inhalt einfügen:

```yaml
alias: "Earnie -> Ecoflow AC-Ladelimit"
triggers:
  - trigger: webhook
    webhook_id: earnie_charge_limit
    allowed_methods: [GET, POST]
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

### 6. Quellenwahl-Merker (`set_ess_source_select`, 2.7.h)

Earnie schreibt `set_ess_source_select` für physische Powerstations mit `role: standby_backup`
(status.json-Feld / Merker `Earnie_Speicher_Quellenwahl`). Die Bridge Loxone → HA bleibt nötig,
wenn Earnie auf `ehal.backend=loxone` läuft. Es gibt zwei Wege, den Schaltzustand zu Home Assistant
zu bringen.

**Zuordnung (gilt für beide Varianten, kein Invertieren nötig):**
- Wert **1 / an** → Schalter `switch.<device>_grid_bypass` **AN** = Bypass aus, die Batterie läuft
  standalone, es wird **nicht** nachgeladen.
- Wert **0 / aus** → Schalter **AUS** = Bypass an, der Ecoflow lädt aus dem Netz **nach**.

#### Variante A: über die Loxone-Integration (PyLoxone), getestet

Voraussetzung: In HA ist die Loxone-Integration (PyLoxone) eingerichtet. Sie spiegelt Loxone-Eingänge
als Entitäten in HA, so wie ihr es für die Telemetrie-Eingänge in Schritt 3 vielleicht schon
gesehen habt. Weder Virtual Output noch Webhook noch HA-Port sind nötig.

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

   Die Bedingung blockt `unavailable` und `unknown`, damit ein Verbindungsabbruch zu Loxone den
   Schalter nicht versehentlich zurücksetzt. Bei einem analogen Eingang (`sensor`, Zahlenwert)
   ersetzt ihr die Bedingung durch `{{ trigger.to_state.state | is_number }}` und die Aktion durch
   `{{ 'switch.turn_on' if (trigger.to_state.state | float(0)) == 1 else 'switch.turn_off' }}`.
5. Test: Den Eingang in Loxone Config online auf 1 und wieder auf 0 setzen. Der Schalter in HA muss
   mitziehen. Die Automation nicht über „Ausführen“ testen (dort gibt es kein `to_state`).

**Hinweis zum Eingang:** Inhaltlich ist der Schaltzustand eine Ausgabe von Loxone nach HA, in der
Loxone-Welt aber ein Virtueller *Eingang*, den ihr im Programm nicht als Ausgang beschalten könnt.
Der Umweg: Der Miniserver schreibt den Eingang selbst, genau wie Home Assistant in Schritt 4
Virtuelle Eingänge beschreibt. Dazu legt ihr den **Miniserver einmal als Gerät für Virtuelle
Ausgänge** an (Adresse: die eigene Miniserver-Adresse) und darunter einen neuen **Virtuellen
Ausgangsbefehl**, der den Eingang beschreibt (`/dev/sps/io/<Eingangsname>/<Wert>`, mit den
Zugangsdaten eines Benutzers mit Schreibrecht). Earnie schreibt Eingänge ohnehin von außen auf
demselben Weg, dort ist später kein Umweg nötig.

**Grenzen:** Die Variante hängt an der PyLoxone-Verbindung zum Miniserver. Bricht sie ab (zum Beispiel
wenn eine neue Konfiguration auf den Miniserver übertragen wird, der Miniserver startet dann neu),
kommt der Schaltbefehl verzögert an. Die Automation ändert den Schalter erst, wenn die Verbindung
wieder steht und der Eingang einen neuen Zustand meldet.

#### Variante B: über einen Webhook

Robuster gegenüber Verbindungsabbrüchen der Loxone-Integration, dafür aufwendiger. Virtueller
Ausgang am Merker `Earnie_Speicher_Quellenwahl`:

```
GET http://<HA-Host>:8123/api/webhook/earnie_speicher_quelle?v=\v
```

In HA — Automation über die Oberfläche anlegen (wie in Schritt 4/5):

```yaml
alias: "Speicher-Quellenwahl -> Ecoflow Grid Bypass"
triggers:
  - trigger: webhook
    webhook_id: earnie_speicher_quelle
    allowed_methods: [GET, POST]
    local_only: false
actions:
  - action: >
      {{ 'switch.turn_on' if (trigger.query.v | int(0)) == 1 else 'switch.turn_off' }}
    target:
      entity_id: switch.<device>_grid_bypass
```

Nach dem Mapping in EHAL-Com schreibt Earnie den Merker im Live-Zyklus; manuelles Beschalten
(Taster/Zeitprogramm) bleibt für Tests möglich.

### 7. Prüfen und mappen

```powershell
python -m scripts.verify_loxone_setup
```

Danach in Earnie unter **Daemon Control → EHAL-Com → Loxone Structure → EHAL Mapping** nur
`sens_ess_soc`, `sens_ess_power` und `set_ess_charge_power_limit` auf die drei Merker binden.
`Earnie_Speicher_Quellenwahl`, `Earnie_Batterie_Sollleistung`, `Earnie_EntladeLeistungs-Limit` und
`Earnie_Steuerbefehl` bewusst **nicht** mappen. Das gilt, solange keine Loxone-Logik nach Schritt 8
dahinter hängt: Dann müssen `set_ess_mode`, `set_ess_active_power` und
`set_ess_charge_power_limit` gemappt sein, damit Earnie sie schreibt.

### 8. Loxone-Logik: EHAL-Werte auf die Delta 3 umsetzen

Earnie schreibt für einen Speicher heute `set_ess_mode` (Steuerbefehl), `set_ess_active_power`
(Sollleistung) und `set_ess_charge_power_limit` (Lade-Limit). Die Delta 3 kennt davon nur zwei
Zustände: **Netz (Bypass an)** und **Batterie (Bypass aus)**, dazu eine einstellbare AC-Ladeleistung.
Die Logik im Miniserver übersetzt:

**Voraussetzung für die Ladeleistung:** Die Delta 3 übernimmt den Wert von
`number.<device>_ac_charging_power` nur, wenn `select.<device>_ac_charging_mode` auf **Custom**
(benutzerdefiniert) steht. In „Auto“ bestimmt die Firmware die Leistung selbst, in „Silent“ begrenzt
sie auf einen festen Wert. Das Lade-Limit aus Loxone wirkt sonst nicht.

Das **Lade-Limit** (`set_ess_charge_power_limit`) entscheidet dabei, ob geladen werden darf: ein
Limit `> 0` heißt „Laden erlaubt, höchstens mit dieser Leistung“, ein Limit `0` heißt „nicht laden“.
Weil die Delta 3 „Netz“ nicht ohne Laden anbietet (mindestens 100 W), ist „nicht laden“ nur über den
Batteriebetrieb zu erreichen.

| Bedingung (von oben nach unten) | Bypass-Eingang (Schritt 6) | AC-Ladeleistung |
|---|---|---|
| Earnie ausgefallen oder Batterieschutz aktiv | `0` Netz | wie unten, mindestens 100 W |
| Steuerbefehl `1` Zwangsladen / Entladesperre | `0` Netz, Verbraucher am Netz, Batterie lädt | `min(Lade-Limit, \|Sollleistung\|)` bei negativer Sollleistung, sonst Lade-Limit |
| Steuerbefehl `2` Zwangsentladen | `1` Batterie, Verbraucher an der Batterie | ohne Bedeutung |
| Steuerbefehl `0` Automatik und Lade-Limit `> 0` | `0` Netz, Batterie lädt höchstens mit dem Limit | Lade-Limit |
| Steuerbefehl `0` Automatik und Lade-Limit `0` | `1` Batterie, kein Laden | ohne Bedeutung |

- **Ladeleistung:** in Watt (Eingang in kW × 1000) und auf 100 bis 1500 W begrenzt, der Bereich der
  Delta 3. In Modus 0 wird die Sollleistung bewusst ignoriert, weil der Loxone-Merker sie auch nach
  einem Moduswechsel behält. Die Schrittweite der Integration ist 50 W.
- **Schutz vor leerer Batterie:** Im Batteriebetrieb (Bypass aus) schaltet die Delta 3 bei leerer
  Batterie den AC-Ausgang ab, die angeschlossenen Verbraucher fallen aus. Die Schwelle hängt jetzt von
  der **SOC-Untergrenze der Delta 3** ab (`Delta3_SOC_Min` aus Schritt 4): Die Logik wechselt auf Netz,
  sobald der SoC `Untergrenze + 5` erreicht, und geht erst bei `Untergrenze + 10` wieder auf Batterie
  (Hysterese). Ändert ihr die Untergrenze in HA, folgt der Schutz automatisch.
- **Earnie tot:** Meldet die Heartbeat-Überwachung (siehe
  [Earnie-Dead-Man-Fallback](../referenz/loxone-signals.md#earnie-dead-fallback-in-loxone-config))
  „Earnie ausgefallen“, geht die Logik auf Netz.
- **Obergrenze:** Erreicht der SoC die SOC-Obergrenze (`Delta3_SOC_Max`), lädt die Delta 3 auch im
  Netzbetrieb nicht mehr weiter und reicht das Netz nur noch durch. Die Logik muss dafür nichts tun.
- **Grenzen:** Ladeleistung und Quelle sind gekoppelt (siehe oben). Modus 2 liefert nur so viel, wie
  die angeschlossenen Verbraucher ziehen; eine Sollleistung `> 0` wird nicht eingehalten.
- **Entscheidung „Automatik“:** Bei Steuerbefehl `0` und Limit `0` versorgt die Batterie die
  Verbraucher, statt sie am Netz zu lassen. Wollt ihr das nicht, nehmt in der Formel von Baustein
  F3 unten den Teil `IF(I2<=0;1;0)` heraus und setzt dort `0` ein. Dann hängt die Delta 3 in
  Automatik immer am Netz und lädt mit mindestens 100 W.

**Umsetzung mit Loxone-Bausteinen.** Die Logik braucht keinen Programmbaustein. Es reichen drei
**Formel**-Bausteine (je vier Eingänge `I1` bis `I4`, Trennzeichen `;`, Funktionen `IF`, `MIN`, `MAX`)
und ein **Schwellwertschalter**. Die Eingangswerte lest ihr aus den Merkern `Earnie_Steuerbefehl`,
`Earnie_Batterie_Sollleistung` (kW), `Earnie_LadeLeistungs-Limit` (kW), dem SoC-Eingang (Schritt 3),
der SOC-Untergrenze (Schritt 4) und dem Signal „Earnie lebt“ (`1` = Heartbeat frisch) aus der
Heartbeat-Überwachung.

1. **F1, Formel „SoC-Abstand“.** `I1` = SoC, `I2` = SOC-Untergrenze der Delta 3.

   ```
   I1-I2
   ```

2. **S1, Schwellwertschalter „Batterie frei“.** Eingang `V` = Ausgang von F1. Parameter
   **Von = 10** und **Voff = 5**. Der Ausgang `O` steht auf `1`, sobald der Abstand 10 Prozentpunkte
   erreicht, und fällt auf `0`, wenn er auf 5 oder weniger sinkt. Das ist die Hysterese des
   Batterieschutzes. Von und Voff sind feste Parameter und lassen sich nicht anschließen, deshalb
   rechnet F1 vorher den Abstand zur (veränderlichen) Untergrenze aus. Nach einem Neustart des
   Miniservers steht `O` auf `0` (Netz), solange der Parameter „Rem“ (Remanenz) nicht gesetzt ist.
   Lasst ihn ungesetzt: Das ist der sichere Zustand.

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
   Sonst `0` (Netz). Die Multiplikation wirkt wie ein UND.

Alle Werte kommen als Zahl an. Für `I1==2` und `I1==0` müssen die Merker ganze Zahlen liefern, wie
Earnie sie schreibt. Nach dem Speichern hilft der Online-Monitor in Loxone Config: Eingangswerte
setzen und prüfen, ob F2 und F3 die Werte aus der Tabelle oben liefern.

**Ausgänge an HA weitergeben:**
- **Bypass (Ausgang von F3)** schreibt den Virtuellen Eingang aus Schritt 6 über den Umweg des
  Miniservers (Virtueller Ausgangsbefehl auf die eigene Adresse). Die HA-Automation aus Schritt 6
  schaltet den Schalter.
- **AC-Ladeleistung (Ausgang von F2)** geht wie in Schritt 5 an HA, nur mit dem Wert aus der Logik
  statt direkt vom Merker. Der Ausgang von F2 hängt am Virtuellen Ausgangsbefehl, der den Eingang
  `Delta3_P_ChargeLimit` beschreibt (Schritt 5, Variante A), bzw. am Webhook-Ausgang (Variante B).
  Der Wert ist schon in Watt, die Begrenzung in der HA-Automation bleibt als Sicherung bestehen. Der
  Virtuelle Ausgang direkt an `Earnie_LadeLeistungs-Limit` entfällt dann.

Sobald `set_ess_source_select` (Backlog) von Earnie geschrieben wird, entfällt die Ableitung aus dem
Steuerbefehl: Der Wert wird direkt als Bypass-Zustand übernommen, und die Logik behält nur noch
Batterieschutz, Earnie-tot-Fallback und die Ladeleistungs-Begrenzung.

## Anhang: die komplette `configuration.yaml`-Ergänzung zum Kopieren

Es sind drei Dateien betroffen: `configuration.yaml` (Template-Sensor und `rest_command`-Verweis),
`rest_command.yaml` (die Befehle) und `secrets.yaml` (Zugangsdaten). Die Automationen (Schritt 4
bis 6) legt ihr über die Oberfläche an (siehe Grundlagen-Abschnitt oben). **Vorher überall** `<device>` und
`192.168.178.10` durch eure eigenen Werte aus Schritt 1 (Entity-IDs) bzw. eure Miniserver-Adresse
ersetzen.

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

**Falls in eurer `configuration.yaml` schon `template:` oder `rest_command:` vorkommt:** den
vorhandenen `rest_command:`-Eintrag durch die `!include`-Zeile ersetzen (sein Inhalt wandert in
`rest_command.yaml`), beim `template:`-Block nur den neuen Sensor in den bestehenden Abschnitt
übernehmen. Danach wie gewohnt: Konfiguration prüfen → neu laden / neu starten (siehe
Grundlagen-Abschnitt oben). Die Automationen (aus Schritt 4, 5 und 6) legt ihr separat über
**Einstellungen → Automatisierungen & Szenen** an, mit den jeweiligen YAML-Inhalten aus den Kapiteln
oben.

## Betriebshinweise

- **Rate-Limits:** Die EcoFlow-Cloud-API limitiert Anfragen — pollt/pusht nicht schneller als alle
  30–60 s; für Earnies 15-Minuten-Schreibzyklus reicht das locker.
- **Gekoppelter Zustand:** `switch.<device>_grid_bypass` steuert Laden **und** Quellenwahl
  gleichzeitig — ein unabhängiges „laden, aber Verbraucher trotzdem aus dem Netz“ oder umgekehrt
  ist mit dieser Integration nicht möglich.
- **Kein Grid-Offset:** Ohne Smart Home Panel zählt die Delta 3 nicht zur Netzbilanz
  (`sens_grid_power_active`) — sie versorgt ausschließlich direkt angeschlossene Verbraucher.
