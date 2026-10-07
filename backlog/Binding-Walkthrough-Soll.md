# Loxone-Binding im Sollzustand (Epic `Binding` umgesetzt) — Walkthrough

**Zielbild, nicht implementiert.** Beschreibt denselben Anwendungsfall wie [Binding-Walkthrough-Ist.md](Binding-Walkthrough-Ist.md) — eine **zweite Batterie** (physische Powerstation) mit Pattern-B-Feldern `ess.<kennung>.*` — so, wie er nach **Binding P0–P6** ablaufen soll. Grundlage: [EHAL-Binding-UX-Draft.md](EHAL-Binding-UX-Draft.md). Alle UI-Texte und Namensendungen sind Entwurf.

**Annahmen (noch offene Entscheidungen, siehe Draft §7):**

- Gebundene, aber im SB fehlende Namen dürfen gespeichert werden und erscheinen **gelb** (Annahme 1; Entscheidung nach P0d).
- Für **Lesefelder** exportiert Earnie nur eine **Namensliste** (Merker-Checkliste), keine VO-Templates, solange es keinen Telemetrie-Empfänger gibt (Annahme 2).
- Neue Namensvorschläge enthalten **immer** die Kennung der Entity (Annahme 3).
- Wie ein Template in Loxone Config installiert wird und ob `LoxAPP3.json` mehr hergibt, klärt **P0a/P0b**. Die Installationsschritte unten sind bis dahin der heutige Weg (Datei in den Template-Ordner, Config neu starten).
- **Kennung editierbar** (P6) ist entschieden.

**Durchgehendes Beispiel:** Batterie „EcoFlow Delta 3“, Kennung `ecoflow_delta_3`.

| Richtung | Qualifizierte EHAL-ID | Bedeutung | Vorgeschlagener SB-Name (Loxone) |
|---|---|---|---|
| Lesen | `ess.ecoflow_delta_3.sens_ess_soc` | EcoFlow Delta 3 — Ladezustand (%) | `Earnie_Batterie_ecoflow_delta_3_SoC` |
| Schreiben | `ess.ecoflow_delta_3.set_ess_charge_power_limit` | EcoFlow Delta 3 — Ladeleistung begrenzen (kW, Betrag) | `Earnie_Batterie_ecoflow_delta_3_LadeLeistungs-Limit` |

Die Endungen kommen aus der **Namenstabelle** (P1); sie führt für jedes Feld Präfix und Endung explizit, auch für die unregelmäßigen Namen (`…LadeLeistungs-Limit`).

---

## 1. Was sich gegenüber heute ändert (Überblick)

| Thema | Ist | Soll |
|---|---|---|
| Anzeige | Dropdown je Feld mit Bedeutung + EHAL-Name | **Tabelle**: EHAL-ID · Bedeutung · SB-Name · Status |
| Welcher Name existiert schon? | nur nach „HTTP-Probe“, nirgends farbig | **automatischer Scan** beim Öffnen, Status je Zeile: ✓ grün · ◌ gelb · ✕ rot · ? grau |
| Namen für Mehrfach-Batterien | Konvention nur als Prosa, jeder denkt sich selbst etwas aus | Earnie **schlägt Namen vor** (eine Namenstabelle für Export *und* Import) |
| Anlegen in Loxone | von Hand; für Pattern-B-Batterien **keine** Template-Unterstützung | **Export**: fertig befüllte Vorlage für Schreibsignale + Checkliste für Lesesignale |
| Kennung (`ecoflow_delta_3`) | aus der Bezeichnung abgeleitet, steckt fest in jedem Binding-Schlüssel (Kopier-Weg → `…_copy_3`) | **editierbar**, Umbenennen nur mit Vorschau |
| Stiller SoC-Rückfall | fehlendes/falsches SoC-Binding der zweiten Batterie → Primär-SoC ohne Warnung | Zeile **gelb/rot** sichtbar; der Rückfall bleibt, wird aber im Status angezeigt |
| `status.json` für die zweite Batterie | nur flache Schlüssel; Powerstation-Werte können Hausbatterie-Schlüssel überschreiben | **qualifizierte Schlüssel** (`ess.ecoflow_delta_3.set_ess_charge_power_limit`) neben den alten |
| Import | Namen werden still geparst; Tippfehler fallen unter den Tisch; Batterien nicht anlegbar | **Vorschau**, „Meintest du …“, optionaler **Signalkatalog**; Batterien als Stub |
| ID-Schreibweise | `ess.`, `flex.`, nackt, `ev.` je nach Bereich | **eine qualifizierte Form** überall |

Unverändert: Earnie liest und schreibt weiterhin einzeln per HTTP (`/jdev/sps/io/<Name>` lesen, `/dev/sps/io/<Name>/<Wert>` schreiben), Einheiten stecken im Code, `status.json` bleibt Spiegel-/Heartbeat-Kanal, die Per-Batterie-Pfade (SoC-Lesen, Powerstation-Schreiben) bleiben Code. Das Epic ändert Benennung, Anzeige, Export und Import, **nicht** den Lese-/Schreibpfad selbst.

## 2. Die Tabelle und ihre Zustände

Je Zeile: **qualifizierte EHAL-ID** · **Bedeutung** (mit Entity und Einheit) · **SB-Name** (Auswahl + Status-Chip). Der Zustand wird bei jedem Öffnen aus einem frischen Scan abgeleitet und nicht gespeichert.

| Chip | Bedeutung | Was zu tun ist |
|---|---|---|
| ✓ grün | Name ist gebunden **und** auf dem Miniserver vorhanden (Probe `200`/`403`) | nichts |
| ◌ gelb | Name ist Vorschlag oder gebunden, aber **nicht im Miniserver** | in Loxone anlegen (Export) oder anderen Namen wählen |
| ✕ rot | war gebunden, ist jetzt **weg** (`404`) | Name reparieren oder Zuordnung entfernen |
| ? grau | noch nicht gescannt | „Prüfen“ |
| leer | nicht gemappt, kein Vorschlag | von Hand zuordnen |

Farbe immer **mit Symbol**. Zusammenfassung je Entity in der Auswahl, z. B. „EcoFlow Delta 3 — 1 ✓ · 2 ◌ · 0 ✕“.

## 3. Schritt für Schritt (Betreiber-Sicht)

### 0. Die zweite Batterie anlegen — mit sauberer Kennung

1. Im Hauskonfigurator (Planung → Batterie/Powerstation) Bezeichnung „EcoFlow Delta 3“ eintragen. Neben der Bezeichnung steht die **Kennung** `ecoflow_delta_3`, vorbelegt aus der Bezeichnung, mit Eindeutigkeitsprüfung („vergeben → `_2`“).
2. Solange die Kennung nicht gesperrt ist, folgt sie der Bezeichnung; mit der ersten bewussten Änderung wird sie gesperrt. Ein Kopieren (`…_copy_3`) erzeugt keine unbrauchbare Kennung mehr, weil sie vor dem Speichern sichtbar und änderbar ist.
3. Speichern. Die Batterie erscheint in EHAL-Com als eigene Entity.

### A. Nach dem Anlegen: was ist neu?

1. **Daemon Control → EHAL-Com → Loxone Structure → EHAL Mapping** öffnen; der **Scan läuft automatisch** (HTTP-Probe + `LoxAPP3.json`).
2. Entity „EcoFlow Delta 3“ wählen. Die Tabelle zeigt die zehn Pattern-B-Felder mit Vorschlägen aus der Namenstabelle:
   - Existiert ein passender Name schon (z. B. `Earnie_Batterie_ecoflow_delta_3_SoC`) → Zeile **grün**, per Klick bestätigen.
   - Existiert nichts → Zeile **gelb** mit dem Vorschlag.
   - Für ein EcoFlow-Pack ist das **Entlade-Limit** als „nicht für diesen Gerätetyp“ vorbelegt (leer, kein Vorschlag); die Quellenwahl liegt weiter auf der Anlage.
3. Die Entity-Zusammenfassung zeigt auf einen Blick, wie viel offen ist.

### B. Lesefeld `ess.ecoflow_delta_3.sens_ess_soc`

**Variante 1 — es gibt schon ein passendes Loxone-Objekt** (anderer Name)

1. In der Zeile das vorhandene Objekt wählen → Chip ✓ grün.
2. **Mapping speichern.**
3. **Live-Lesen** prüfen: Wert plausibel, Einheit % (steht in der Bedeutungs-Spalte). Weicht er vom Haus-SoC ab, greift der Rückfall nicht.

**Variante 2 — es gibt noch nichts**

1. Gelbe Zeile lassen, **Mapping speichern** („Vorschläge übernehmen“, eine Sammelbestätigung für alle gelben Zeilen). Der SoC ist Pflichtfeld: Speichern ist mit gelbem Namen möglich (Annahme 1).
2. **Export → Lesesignale (Checkliste)**: CSV/Markdown mit Name, Bedeutung, Einheit, Richtung. Für Lesefelder gibt es keine fertige Loxone-Vorlage, weil jeder Wert aus einer eigenen Quelle kommt.
3. In **Loxone Config** den **analogen Merker** `Earnie_Batterie_ecoflow_delta_3_SoC` anlegen (Name aus der Liste kopieren), mit der Quelle verdrahten, speichern, auf den Miniserver übertragen.
4. In EHAL-Com **„Prüfen“** → Chip ◌ gelb → ✓ grün. Bei Tippfehler bleibt er gelb/wird rot, mit „Meintest du `…`?“.
5. **Live-Lesen** prüfen, Gegenprobe gegen den Haus-SoC.

### C. Schreibfeld `ess.ecoflow_delta_3.set_ess_charge_power_limit`

1. Zeile ist **gelb** mit `Earnie_Batterie_ecoflow_delta_3_LadeLeistungs-Limit` (oder ✓ grün, wenn schon vorhanden). **Mapping speichern.**
2. **Export → Loxone-Vorlagen für gelbe Signale.** Auswahl:
   - **Minimal** (nur, was die aktivierten Funktionen brauchen, z. B. Ladelimit; Entlade-Limit nicht, solange es leer ist) oder **Alle**.
   - Adresse: Earnie trägt Host und Port (8541) ein, änderbar (Docker/Container-Netz).
3. Earnie liefert ein **ZIP**: `VI_…xml` mit **echtem Titel, fertigem `Check`-Muster `"ess.ecoflow_delta_3.set_ess_charge_power_limit":\v` und Adresse** (statt `{hk_id}` / `EARNIE_HOST` zum Selbstersetzen), plus eine kurze Anleitung. Die Vorlage ist temporär und deckt nur die gelben Signale ab.
4. In den Config-Template-Ordner kopieren, Config neu starten, über **Peripherie → Vorlagen** einfügen (bis P0a wie heute).
5. In der **Programmierung** den Wert an die Gerätesteuerung anschließen (**kW, Betrag, Sticky**), sicherer Rückfall bei „Earnie tot“ wie bisher; speichern, auf den Miniserver übertragen.
6. EHAL-Com → **„Prüfen“**: Chip ✓ grün (Virtual Inputs melden `403`, zählt als vorhanden).
7. **Silent-Modus an**; optional **Schreibtest** (soll Pattern-B-Zeilen einer zweiten Batterie ansprechen, Teil von P2).
8. **Loud-Modus** einschalten. **Nachweis:** Live-Schreiben zeigt auch Powerstation-Schreibvorgänge mit Wert und Erfolg; `status.json` enthält den qualifizierten Schlüssel `ess.ecoflow_delta_3.set_ess_charge_power_limit` getrennt vom Hausbatterie-Schlüssel. Cutover-Checkliste abhaken.

Hinweis: Die letzten beiden Verbesserungen (Nachweis in Live-Schreiben, getrennte `status.json`-Schlüssel) sind **nicht** Teil der bisherigen Epic-Phasen in dieser Genauigkeit: P1 führt die qualifizierten `status.json`-Schlüssel ein, der Powerstation-Nachweis in Live-Schreiben ist ein zusätzlicher kleiner Punkt (siehe §5).

### D. Kennung ändern: „ecoflow_delta_3“ → „delta3“

1. In der Batterie-Form neben der Bezeichnung **„Kennung ändern“**.
2. Earnie zeigt eine **Vorschau**: betroffene Szenarien (`battery_ids`), Bindings (`ess.ecoflow_delta_3.*` → `ess.delta3.*`), Shadow-Overlay, `status.json`-Schlüssel — und **welche SB-Namen danach von der Konvention abweichen** (hier: `Earnie_Batterie_ecoflow_delta_3_SoC`, `…_LadeLeistungs-Limit`).
3. Bestätigen. Die Bindings zeigen weiter auf die **alten Loxone-Namen** (✓ grün, funktioniert); die Abweichung ist nur ein Hinweis.
4. Wer die Namen nachziehen will: **Umbenennungsliste** exportieren, in Config umbenennen, Name im Dropdown neu wählen, „Prüfen“.
5. Das Loxone-VI-Template mit altem `Check`-Schlüssel braucht den neuen Schlüssel (`ess.delta3.…`), bis dahin liefert `status.json` die alten Schlüssel parallel (eine Version lang).
6. Historie/Dumps, die nach der alten Kennung schlüsseln, liest Earnie über eine **Alias-Tabelle** (falls Spike P0c das als nötig zeigt).

### E. Variante „SB zuerst“ (Import statt Export)

Die Namen sind schon in Loxone definiert, z. B. durch einen Installateur.

1. Der SB-Verantwortliche liefert den **Signalkatalog** (CSV): `ehal_id; bedeutung; sb_name; richtung; einheit`. Dieselbe Datei kann Earnie aus der Tabelle **exportieren**.
2. **Smarthome-Backend → Import** (Loxone-Import oder Katalog-Import): **Vorschau**
   - Zeilen zu bestehenden Entities → ✓ grün, werden gebunden.
   - Zeilen mit **neuer** Kennung (`ess.ecoflow_delta_3.*` ohne bekannte Batterie) → EHAL-ID **gelb** („Entity würde angelegt“); Bezeichnung und Kennung editierbar.
   - Beinahe-Treffer (`Earnie_Batterie_ecoflow_delta_3_Soc`, `…_LadeLeistungs-Limt`) → „Meintest du …?“.
   - Eine Batterie lässt sich aus Namen nicht vollständig anlegen (Kapazität, Leistung fehlen): es entsteht ein **unvollständiger Stub**, der die Planung erst freigibt, wenn die Parameter ergänzt sind (oder die Zeile wird nur an eine vorhandene Batterie gebunden; Entscheidung steht aus).
3. Bestätigen → Entity und Bindings werden angelegt. Weiter wie B/C ab „Prüfen“.

### F. Fehlerbilder (neu bzw. verändert)

| Symptom | Ursache / Anzeige |
|---|---|
| Zeile ✕ rot | Name in Loxone gelöscht/umbenannt → Name reparieren oder Zuordnung entfernen |
| Zeile bleibt ◌ gelb nach dem Anlegen | Programm nicht übertragen, Tippfehler („Meintest du …?“), oder Name existiert nur in Config, nicht auf dem Miniserver |
| Alle Chips ? grau | Scan nicht möglich (Zugangsdaten / Miniserver offline) → Smarthome-Backend prüfen |
| SoC der zweiten Batterie = Haus-SoC | SoC-Zeile gelb/rot → in der Entity-Zusammenfassung sichtbar (Rückfall bleibt, ist aber nicht mehr unsichtbar) |
| Schreibfehler „no own Merker“ | Lade-Zeile gelb/leer — Export + Anlegen, oder Binding unter alter Kennung nach Umbenennen (Vorschau hätte es gezeigt) |
| Wert 100×/1000× falsch | Einheit am Merker; die Bedeutungs-Spalte nennt die erwartete Einheit |
| „Kennung weicht von Konvention ab“ | Hinweis nach Umbenennen; funktional egal |

## 4. Entwickler-Sicht: ein neues Pattern-B-Feld entsteht

**Was einfacher wird** (P1): Das Feld wird in der Registry (`ESS_FIELD_KINDS`, bzw. der Registry der jeweiligen Rolle) und in der **Namenstabelle** (Präfix + Endung + Einheit + Richtung) eingetragen. Daraus folgen: Zeile in der Tabelle, qualifizierte ID, Namensvorschlag, Export, Import-Parsing, Signalkatalog, `status.json`-Schlüssel. Die doppelte `PLANT_FIELDS`-Liste und die Prosa-Regeln für Mehrfach-Instanzen entfallen. Ein Rundlauf-Test (`parse(suggest(x)) == x`) fängt vergessene Felder.

**Was gleich bleibt:** Lese-Umrechnung und Schreibpfad je Feld stehen weiter im Code (`ehal_live.read_ess_soc_by_id`, `optimizer/powerstation_live.py`, `loxone_adapter.py`, `loxone_writes.py`). Das Epic macht den Lese-/Schreibpfad **nicht** generisch; das ist **2.7.n-5 / 2.7.n-6** (generischer Lese- und Schreibpfad, siehe `Backlog.md`, Version 2.7). Erst wenn diese Teilschritte umgesetzt sind, genügt für ein neues Feld eine Zeile in der Rollen-JSON; sie sind per Gate abgesichert und rutschen im Zweifel nach 2.+1.

## 5. Nicht festgelegt / hängt von Spikes ab

- Installation generierter Templates in Config (P0a) und ob `LoxAPP3.json` oder exportierte XMLs EHAL-IDs preisgeben (P0b).
- Ob ein gebundener, aber fehlender Name das Laufzeitverhalten stört (P0d) → entscheidet, ob gelbe Bindings gespeichert werden dürfen.
- Ob Lesefelder später per Loxone-Push (VO + Telemetrie-Empfänger) gefüllt werden; dann entfiele die Checkliste.
- **Nicht im Epic enthalten, aber im Soll-Ablauf vorausgesetzt:** (a) Powerstation-Schreibvorgänge im Schreibprotokoll / Live-Schreiben, (b) Schreibtest für Pattern-B-Batterie-Felder, (c) sichtbarer Hinweis beim stillen SoC-Rückfall. Gehört in einen eigenen Backlog-Punkt oder in P2.
- HA/MQTT: gleiche Tabelle, aber mit `entity_id` bzw. Topic statt Merker-Name; Vorschläge dort nur für Schreibfelder (Helper) bzw. durch das Add-on.
