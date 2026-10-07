# Loxone-Binding im Ist-Zustand — Walkthrough

**Arbeitsdokument zum Verständnis, nicht zum Veröffentlichen.** Stand 2026-10-07, aus dem Code gelesen (Working Tree von `main`, inkl. uncommitteter 2.7.m-Arbeit). In Loxone Config selbst nicht geprüft; wo die Doku etwas behauptet, was ich im Code nicht sehe, steht es als „laut Doku“; Aussagen aus reinem Code-Lesen (nicht ausgeführt) sind mit „nach Code-Lage“ markiert.

**Anwendungsfall:** Earnie hat neue EHAL-Felder, die an den Miniserver angebunden werden müssen — hier: Es wurde eine **zweite Batterie** angelegt (eine physische Powerstation, z. B. EcoFlow Delta 3). Damit kommen **Pattern-B-Felder** `ess.<kennung>.*` hinzu.

**Durchgehendes Beispiel:** Batterie „EcoFlow Delta 3“, Kennung `ecoflow_delta_3`.

| Richtung | EHAL-Feld (Pattern B) | Bedeutung | Einheit auf dem Miniserver | Beispielname (frei wählbar) |
|---|---|---|---|---|
| Lesen | `ess.ecoflow_delta_3.sens_ess_soc` | Ladezustand dieser Batterie | **%** (0–100) | `Earnie_Batterie_ecoflow_delta_3_SoC` |
| Schreiben | `ess.ecoflow_delta_3.set_ess_charge_power_limit` | Obergrenze Ladeleistung, die Earnie vorgibt | **kW**, Betrag ≥ 0 (`0` = nicht laden) | `Earnie_Batterie_ecoflow_delta_3_LadeLeistungs-Limit` |

Die Namenskonvention `Earnie_Batterie_<Kennung>_…` steht nur in der Doku (2.7.m); es gibt keinen Code, der sie erzeugt oder prüft. Earnie verlangt nur, dass der gewählte Name auf dem Miniserver existiert.

---

## 1. Das Grundprinzip in sechs Sätzen

1. Earnie kennt vom Miniserver nur **Namen** (Merker, Virtual Inputs, EFM-Zähler-Bezeichnungen). Es gibt keine IDs, kein Schema, keinen Katalog auf Loxone-Seite.
2. Jede Zuordnung „EHAL-Feld → Name“ steht als **Binding** in der Earnie-Konfiguration. Bei Batterien liegt es in `components.json` → `batteries[].ehal_bindings` unter dem Schlüssel `ess.<kennung>.<feld>`; die **Kennung steckt also in jedem Binding-Schlüssel**.
3. Gelesen wird **ein Wert pro HTTP-Aufruf** (Polling), geschrieben ebenfalls **ein Wert pro Aufruf**. Earnie hält keine Verbindung offen und bekommt nichts gepusht.
4. Die **Einheit steckt nicht im Binding**, sondern fest im Code je EHAL-Feld (Leistung in Loxone = kW, in EHAL = W). Der Miniserver muss genau die erwartete Einheit liefern.
5. Ein **zweiter, getrennter Kanal** läuft in die andere Richtung: Loxone holt sich per Virtual HTTP Input regelmäßig `status.json` von Earnie (Spiegel der Sollwerte + Heartbeat für den Dead-Man-Fallback).
6. Ein Feld ohne Binding wird meist **still ignoriert** oder blockiert nur die zugehörige **Funktion** — es gibt aber Ausnahmen, die bei der zweiten Batterie wichtig sind (Abschnitte 2 und 3).

## 2. Wie Earnie technisch liest

**Allgemein** (`integrations/loxone_client.py`, `integrations/loxone_adapter.py`): pro Feld `GET http://<LOXONE_IP>/jdev/sps/io/<Name>` mit HTTP Basic Auth (`LOXONE_USER` / `LOXONE_PASS`), Timeout `GLOBAL_TIMEOUT` (Default 5 s). Die Antwort ist JSON, gelesen wird `LL.value` als Text. Leer → Warnung, „nicht gelesen“. Der Text wird geparst: Komma → Punkt, Einheitensuffixe (`kW`, `W`, `%`, `°C`, `A`) werden **abgeschnitten, nicht umgerechnet**. Im Shadow-Modus liest Earnie aus einem aufgezeichneten Feed statt live.

**Hausbatterie / Anlage:** `LoxoneAdapter.read_telemetry` liest Netz, PV, SoC, Batterieleistung zwingend (fehlt eines: `LoxoneAdapterError`) und die optionalen `get_*`-Felder (ohne Fehler ausgelassen, wenn nicht gebunden). Die Namen holt `ehal_live.get_loxone_adapter()` über `resolve_plant_binding`; für die **Primärbatterie** werden die Pattern-B-Schlüssel als flache Aliase auf die Anlage gespiegelt.

**Zweite Batterie — nach Code-Lage so:**

1. Vor jeder Optimierung ruft `main.py` (Zeile 93) `ehal_live.read_ess_soc_by_id()`.
2. Für **jede** Batterie aus der Planung wird die Adresse von `ess.<kennung>.sens_ess_soc` aus `batteries[].ehal_bindings` genommen (`_soc_address_for_battery`) und wie oben per `/jdev/sps/io/<Name>` gelesen.
3. Ergebnis ist der Start-Ladezustand dieser Batterie für die Optimierung (`current_soc_by_id`).
4. **Stolperfalle:** Fehlt das Binding oder schlägt das Lesen fehl, setzt Earnie **ohne Warnung (nur Debug-Log) den SoC der Primärbatterie** ein. Eine falsch benannte SoC-Zeile der zweiten Batterie sieht im Betrieb also „plausibel“ aus.
5. Andere Pattern-B-Lesefelder der zweiten Batterie (`sens_ess_power`, `get_ess_*`) zeigt **Live-Lesen** je Batterie an; eine Verwendung durch den Optimierer habe ich dafür nicht gefunden — der Adapter liest diese Felder nur für die Primärbatterie.

**Verbraucher** (Wärmepumpe, Pool, EV, …) werden separat gelesen (`integrations/loxone_live_power.py`): kW-Merker oder 0/1-Merker × Nennleistung; fehlt der Merker, gilt der Optimierer-Sollwert als Rückfall.

## 3. Wie Earnie technisch schreibt

**Hausbatterie / Anlage / Verbraucher (Produktion, Loxone-Backend):** über `integrations/loxone_writes.py` — `send_huawei_modbus_states` (ESS-Grenzen, Sollleistung, Modus, Einspeisegrenze) und `send_flexible_consumer_states`. Diese Funktionen arbeiten mit den Parametern und Bindings der **Primärbatterie** (flache Anlagen-Namen). `LoxoneAdapter.write_setpoints` gibt es zusätzlich; es wird vom Schreibtest und den Vertragstests genutzt, nicht vom Produktionslauf.

**Zweite Batterie — nur als physische Powerstation (2.7.g/h), nach Code-Lage:**

1. Pro Lauf stellt `main.py` (Zeilen 431–444) aus Reserve-/Standby-Plänen eine Ladevorgabe je physischer Powerstation zusammen (`cycle_powerstation_charge_kw`). Hat die Powerstation ein Lade-Binding, wird **in jedem Lauf mindestens `0` geschrieben** (Sticky-Merker auffrischen); Plan-Werte überschreiben das.
2. `write_physical_powerstation_charges` bildet das Feld `ess.ecoflow_delta_3.set_ess_charge_power_limit` (Wert in W). Ein Entlade-Limit wird **nur geschrieben, wenn es gemappt ist** (Wert `0`); EcoFlow-Packs sollen es nicht mappen.
3. `_write_powerstation_fields` prüft die Torwächter (Tabelle unten). Dann `_write_powerstation_loxone`: Der Name kommt aus `batteries[].ehal_bindings` der **eigenen** Batterie. Es gibt bewusst **keinen Rückfall auf den Anlagen-Merker** der Hausbatterie (einzige Ausnahme: `set_ess_source_select`, gemeinsamer EcoFlow-Merker `Earnie_Speicher_Quellenwahl`).
4. Fehlt der Name: **das ist ein Fall, der nicht still bleibt** — Warnung im Log und ein Eintrag in `runtime/ehal_write_error.json` („Powerstation ESS fields have no own Merker; refusing plant-flat house-battery fallback: …“). Genau diese Meldung steht aktuell als offener Fehler in `Backlog-Bugfixes.md` (NAS alpha, Kennung `15_kwh_speicher_copy_3`).
5. Wert: W → **kW** (÷ 1000) für die beiden Limit-Felder; Senden mit `GET http://<LOXONE_IP>/dev/sps/io/<Name>/<kW>` (**`dev`**, nicht `jdev`), Basic Auth. Erfolg heißt nur HTTP 200; Earnie prüft nicht, was Loxone danach tut.
6. Der gesendete Wert wird in `_last_powerstation_sent` gemerkt (für `status.json`, Abschnitt 4).

**Nachweis des Schreibens:** Die Rückgabe von `_send_loxone_value_traced` wird in `_write_powerstation_loxone` verworfen; `main.py` übernimmt nur `huawei_writes + flex_writes` in die Schreibprotokoll-Liste, und `build_sent_loxone_snapshot` kennt nur Anlage und Verbraucher. Nach Code-Lage taucht der Powerstation-Schreibvorgang deshalb **nicht mit Wert und Erfolg in EHAL-Com → Live-Schreiben** auf. Sichtbar ist er im Log („Loxone API: <Name> erfolgreich auf <Wert> gesetzt“) und in Loxone selbst.

**Torwächter vor jedem Schreiben:**

| Bedingung | Wirkung |
|---|---|
| **Silent-Modus** an (Default ohne Datei) | nichts wird gesendet |
| Shadow-Modus | Schreiben blockiert, nur protokolliert |
| Batterie `control = read_only` | keine ESS-Schreibzugriffe (Hausbatterie-Pfad) |
| `control = limits_only` | Zwangsladen/-entladen wird zu Automatik (Hausbatterie-Pfad) |
| Funktion unvollständig (`ehal/functions.py`) | Beispiel: nur eine der beiden ESS-Grenzen der Hausbatterie gemappt → „Speicher begrenzen“ nicht verfügbar |
| Physische Powerstation ohne Lade-Binding, aber ein Plan verlangt Laden | Schreibfehler-Eintrag (s. o.), kein Rückfall; ohne Plan und ohne Binding passiert nichts |

**Sticky:** Loxone behält den letzten Wert. Deshalb frischt Earnie Limits auch im Leerlauf mit `0` auf. Die Loxone-Logik darf den Wert nur als **Obergrenze in kW** verstehen und muss mit „konstant zwischen zwei Läufen“ rechnen.

## 4. Der zweite Kanal: `status.json`

Das Loxone-Template `VI_Earnie_*` enthält einen **Virtual HTTP Input**, der alle 30 s `http://<Earnie>:8541/ehal/loxone/status.json` abruft. Earnie baut das JSON aus dem letzten Lauf (`integrations/loxone_status_json.py`): `heartbeat_ts` (Unix-Sekunden) plus die zuletzt gesendeten Sollwerte unter **flachen** Anlagen-Schlüsseln (`set_ess_charge_power_limit`, …) und Verbraucher-Schlüsseln (`flex.<kennung>.Earnie_Verbraucher_Freigabe`, …). Zweck: Spiegel der Sollwerte und **Heartbeat** für den Dead-Man-Fallback.

**Für die zweite Batterie gibt es keinen Pattern-B-Schlüssel in `status.json`.** Der Template-Weg (`VI_Earnie_Plant.xml` mit flachen Schlüsseln) passt also nicht auf `ess.ecoflow_delta_3.*`; das Schreiben läuft direkt auf den benannten Virtual Input (Abschnitt 3).

**Mögliches Problem, nach Code-Lage:** `_write_powerstation_loxone` merkt den Wert unter dem **flachen Feldtyp** (`_last_powerstation_sent["set_ess_charge_power_limit"]`), nicht unter dem Pattern-B-Schlüssel. `build_loxone_status_payload` schreibt diese Werte nach den Anlagen-Werten in dieselben flachen Schlüssel. Ein Powerstation-Ladelimit kann dadurch das **Hausbatterie-Ladelimit in `status.json` überschreiben**; bei zwei Powerstations gewinnt die zuletzt geschriebene. Wer die Hausbatterie über den Virtual-HTTP-Input-Spiegel steuert, bekäme dann den falschen Wert. Direktes Schreiben per `/dev/sps/io/` ist davon nicht betroffen. Ich habe das nicht ausgeführt, nur gelesen.

**Lesefelder:** kein Gegenstück. Die `VO_Earnie_*`-Templates (Loxone → Earnie, Push an `/ehal/loxone/telemetry/…`) sind **Platzhalter ohne Empfänger** in Earnie; gelesen wird ausschließlich per Polling (Abschnitt 2).

## 5. Was ein Pattern-B-Feld im System ist

| Aspekt | Wo es definiert ist |
|---|---|
| Registry der ESS-Feldtypen | `ehal/ess_fields.py` → `ESS_FIELD_KINDS` (11 Typen); daraus `ess.<kennung>.<typ>` |
| Welche Felder die Mapping-Zeile zeigt | `ESS_BATTERY_MAPPING_KINDS` (alle außer `set_ess_source_select`) |
| Welche in Live-Lesen / Live-Schreiben | `BATTERY_ESS_LIVE_READ_KINDS` / `BATTERY_ESS_LIVE_WRITE_KINDS` in `integrations/ehal_debug_mapping.py` |
| Pflicht | `sens_ess_soc` je Batterie (Speichern ohne SoC wird abgelehnt) |
| Einheit / Umrechnung | im Code (Hausbatterie: `loxone_adapter.py`; Powerstation: `powerstation_live.py`) |
| Binding | `components.json` → `batteries[].ehal_bindings["ess.<kennung>.<typ>"]` |
| Virtuelle Powerstation | hat **keine** EHAL-Bindings, erscheint nicht in EHAL-Com |
| Standard-Name (Vorschlag) | nur für Anlage/Primärbatterie in `greenfield_device_map.json` / `recipes/ess.json`; für Mehrfach-Batterien nur Prosa |

## 6. Schritt für Schritt (Betreiber-Sicht)

### 0. Voraussetzung: die zweite Batterie existiert

1. Im Hauskonfigurator (Planung → Batterie/Powerstation) die Batterie anlegen: Bezeichnung, Kapazität, Leistung, Art **physisch**, `control`.
2. **Kennung prüfen** (EHAL-Com zeigt sie in der Entity-Auswahl in Klammern hinter der Bezeichnung). Die Kennung geht in alle Binding-Schlüssel ein. Aus dem Kopier-Weg entstehen Kennungen wie `15_kwh_speicher_copy_3`; die lassen sich später nur mit Aufwand ändern (uncommittete id-lock-Arbeit und `scripts/clean_entity_ids_once.py` adressieren das für Batterie/PV).
3. In EHAL-Com erscheint die Batterie danach als eigene **Entity** (physische Powerstations und Hausbatterien; virtuelle nicht).

### A. Nach dem Anlegen: was ist neu?

1. **Daemon Control → EHAL-Com → Loxone Structure → EHAL Mapping**, Entity „EcoFlow Delta 3 (`ecoflow_delta_3`)“ wählen.
2. Die Zeile bietet **zehn** Pattern-B-Felder an (SoC, Leistung, SoC-Min/-Max, max. Lade-/Entladeleistung, Sollleistung, Lade-/Entladelimit, Modus), alle leer. Pflicht ist nur `sens_ess_soc` (Stern). Für ein EcoFlow-Pack bleibt das **Entlade-Limit leer** und die Quellenwahl liegt auf der Anlage (`set_ess_source_select`).
3. Eine Anzeige „neu seit dem Update“ gibt es nicht; die Doku dazu steht in `loxone-signals.md` und `ehal-com.md` §C.2.

### B. Lesefeld `ess.ecoflow_delta_3.sens_ess_soc` anbinden

1. **Quelle klären:** Welches Loxone-Objekt liefert den SoC dieses Packs (z. B. über die HA-/EcoFlow-Brücke)? Einheit **Prozent, 0–100**.
2. **In Loxone Config** einen **analogen Merker** anlegen (Beispiel `Earnie_Batterie_ecoflow_delta_3_SoC`), mit der Quelle verdrahten, speichern, auf den Miniserver übertragen.
3. In EHAL-Com **HTTP-Probe** drücken (`200`/`403` = vorhanden, `404` = fehlt). Der Name erscheint in den Dropdowns.
4. Im Dropdown des Felds `ess.ecoflow_delta_3.sens_ess_soc` (die Beschriftung nennt Bedeutung und Feldname) den Namen wählen (oder eintippen und „Neuer Merker?“ mit **Ja** bestätigen).
5. **Mapping speichern.** Ohne SoC lehnt Earnie das Speichern ab („Pflichtfelder fehlen: …“); es schreibt nach `components.json`.
6. **Prüfen in Live-Lesen:** Zeile `ess.ecoflow_delta_3.sens_ess_soc` — Mapping-Spalte zeigt den Namen, Wert und Status OK. **Gegenprobe:** der Wert darf nicht identisch mit dem Haus-SoC sein (außer er ist es wirklich) — sonst greift womöglich der stille Rückfall aus Abschnitt 2.
7. Wirkung: ab dem nächsten Lauf geht dieser SoC als Startwert der zweiten Batterie in die Optimierung ein.

### C. Schreibfeld `ess.ecoflow_delta_3.set_ess_charge_power_limit` anbinden

1. **Ziel klären:** Wer setzt das Ladelimit am Gerät um (Loxone-Logik → EcoFlow-Brücke)? Wert **kW, Betrag ≥ 0**, `0` = nicht laden.
2. **In Loxone Config** einen **Virtual Input** (analog) anlegen (Beispiel `Earnie_Batterie_ecoflow_delta_3_LadeLeistungs-Limit`). Earnie schreibt **direkt auf diesen Namen**. Ein Template mit `status.json`-Schlüssel gibt es für Pattern-B-Batterien nicht (Abschnitt 4); `VI_Earnie_Plant.xml` ist nur für die flachen Anlagen-Felder.
3. In der **Programmierung** den Wert an die Gerätesteuerung anschließen, **Sticky** beachten und für „Earnie tot“ einen sicheren Rückfall vorsehen (Dead-Man-Fallback laut `loxone-signals.md`; bei einem Pack typischerweise Laden sperren).
4. Speichern, auf den Miniserver übertragen.
5. **HTTP-Probe** in EHAL-Com (Virtual Inputs antworten oft `403` = „vorhanden“).
6. Im Dropdown des Felds `ess.ecoflow_delta_3.set_ess_charge_power_limit` den Namen wählen, **Mapping speichern**. Entlade-Limit **nicht** mappen (EcoFlow).
7. **Silent-Modus an:** Es wird nichts gesendet. Ob der **Schreibtest** Pattern-B-Felder einer zweiten Batterie anspricht, habe ich nicht geprüft (die Doku nennt nur die flachen Probe-Felder).
8. **Loud-Modus:** Ab dem nächsten Lauf schreibt Earnie die Ladevorgabe (im Leerlauf `0`). **Nachweis** (nach Code-Lage nicht in Live-Schreiben): Log-Zeile „Loxone API: … erfolgreich auf … gesetzt“, Wert am Virtual Input in Loxone, Verhalten des Geräts.
9. Meldet `runtime/ehal_write_error.json` „Powerstation ESS fields have no own Merker“, fehlt das Binding dieser Batterie (häufig: unter einer anderen Kennung gespeichert, siehe Fehlerbilder).

### D. Typische Fehlerbilder (zweite Batterie)

| Symptom | Ursache |
|---|---|
| Schreibfehler „… have no own Merker; refusing plant-flat house-battery fallback: ess.<kennung>.…“ | Lade-Binding fehlt, oder Binding liegt unter einer anderen Kennung (z. B. `…_copy_3`) |
| Zweite Batterie hat immer denselben SoC wie die Hausbatterie | SoC-Binding fehlt/falsch → stiller Rückfall auf Primär-SoC |
| Live-Lesen leer, Status „kein Mapping“ | Feld nicht gebunden oder auf anderer Entity gespeichert |
| Wert 100× / 1000× falsch | Einheit am Merker (SoC in 0–1 statt %; Limit in W statt kW); Earnie schneidet Einheiten nur ab |
| Probe `404` | Name falsch geschrieben oder Programm nicht übertragen |
| Nichts wird geschrieben, kein Fehler | Silent-/Shadow-Modus, oder die Powerstation hat gar kein Lade-Binding und ist nicht in der Planung |
| Loxone reagiert nicht, Log meldet Erfolg | Earnie prüft nur HTTP 200; Logik/Verdrahtung in Config |
| Hausbatterie-Limit über `status.json`-Spiegel falsch | möglicher Überschreib-Effekt (Abschnitt 4) |
| Wert bleibt nach Earnie-Ausfall stehen | Sticky-Merker ohne Dead-Man-Fallback |

## 7. Entwickler-Sicht: ein neues Pattern-B-Feld entsteht

**ESS-Felder sind besser gestellt als Anlagen-Felder:** `ESS_FIELD_KINDS` in `ehal/ess_fields.py` ist eine zentrale Registry. Ein neuer Typ erscheint damit als `ess.<kennung>.<typ>` und kann in `ESS_BATTERY_MAPPING_KINDS` bzw. in den Live-Listen von `ehal_debug_mapping.py` ergänzt werden. Trotzdem muss je nach Feld zusätzlich angepasst werden:

- Schema/Rolle: `share/ehal/telemetry.schema.json` / `setpoint.schema.json`, `share/ehal/roles/ess.json`, `ehal/models.py`, `ehal/profiles.py`
- **Lesen je Batterie:** nur SoC ist als Per-Batterie-Pfad vorhanden (`ehal_live.read_ess_soc_by_id`); alles andere müsste ergänzt werden
- **Schreiben je Batterie:** nur Powerstation-Funktionen in `optimizer/powerstation_live.py` (Ladelimit, optional Entladelimit, Quellenwahl); Einheit W→kW ist dort fest für die zwei Limit-Typen codiert
- Status/Trace: `loxone_status_json.py` (flache Schlüssel, Überschreib-Effekt), `loxone_writes.build_sent_loxone_snapshot` (kennt keine Powerstations)
- Mapping/UI und Namen: `integrations/loxone_ehal_mapping.py`, `ui/ehal_loxone_mapping.py`, `share/loxone/greenfield_device_map.json`, `share/loxone/recipes/ess.json`, VO-Templates
- HA: `integrations/ha_adapter.py`, `ha_units.py`, `house_config/ha_ehal_bindings.py` (`aggregate_ha_entities`)
- Doku: `loxone-signals.md`, `ehal-com.md`, `ehal.md`

Zum Vergleich ein Anlagen-Feld (Commit `32bb5b8f`, 2.7.j): rund 15 Dateien, ohne zentrale Registry. **Fallstrick:** `PLANT_FIELDS` ist doppelt definiert — `ui/ehal_loxone_mapping.py:56` (vollständig) und `ui/ehal_loxone_mapping_ui.py:52` (nur `set_ess_*`); die zweite speist die Namensvorschläge der HTTP-Probe, `set_grid_export_power_limit` bekommt dort nie einen Vorschlag.

## 8. Nicht geprüft

- Verhalten von Loxone Config / Miniserver (Schreiben auf Virtual Inputs per `/dev/sps/io/`, Wirkung von `403`, Template-Installation, ob ein Virtual HTTP Input und ein direkter Schreibzugriff dasselbe Objekt meinen).
- Alle „nach Code-Lage“-Aussagen (Powerstation-Schreibnachweis in Live-Schreiben, Überschreib-Effekt in `status.json`) sind nicht ausgeführt worden.
- Ob Schreibtest und Live-Schreiben Pattern-B-Zeilen einer zweiten Batterie anzeigen.
- Zweite **Haus**batterie (nicht Powerstation): ich habe keinen eigenen Schreibpfad gefunden; `send_huawei_modbus_states` arbeitet mit den Parametern der Primärbatterie.
