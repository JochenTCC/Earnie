# Wärmespeicher: äquivalente Temperatur `T_eq` (Schichtspeicher → Earnie)

Earnies Wärmespeicher-RC ist ein **Einknoten-Modell** (eine Temperatur, ein Volumen). Viele Warmwasser-/Pufferspeicher sind **Schichtspeicher** mit mehreren Temperatursensoren (typisch drei oder vier Fühler in unterschiedlicher Höhe). Für Live-Vergleich und spätere Adaptation muss das Smart Home **eine** Temperatur liefern, die denselben **Wärmeinhalt** wie der geschichtete Speicher abbildet.

Entwickler-Kontext: [thermals-p2.md](../spec/thermals-p2.md) (Abschnitt *Stratified store → T_eq*). Konzept: Entwicklungsplan §3.5 im `Earnie-Projekt`-Repo.

## Physik (kurz)

Wärmekapazität aus dem konfigurierten Volumen (wie im Code):

```text
C [kWh/K] = (V_liter / 1000) × 1.163
```

Wärmeinhalt (Referenz 0 °C):

```text
Q [kWh] = C × T_eq
```

`T_eq` ist die **volumen-gewichtete** Mitteltemperatur der Schichten:

```text
T_eq = Σ (V_i · T_i) / V_gesamt
```

Sitzen die `n` Sensoren in den Mittelpunkten gleich hoher Schichten (drei Sensoren bei 1/6, 3/6, 5/6 der Höhe; vier Sensoren bei 1/8, 3/8, 5/8, 7/8), ist `T_eq` das arithmetische Mittel:

```text
T_eq = (T1 + … + Tn) / n        # drei Sensoren: (T1 + T2 + T3) / 3
```

Allgemein mit Gewichten `w_i` (`Σ w_i = 1`):

```text
T_eq = w1·T1 + … + wn·Tn        # drei Sensoren: w1·T1 + w2·T2 + w3·T3
```

Die **Endschichten** reichen bis Boden bzw. Deckel: Der äußerste Fühler steht für die gesamte Schicht bis zum Speicherende. Sitzt der oberste Fühler deutlich unter dem Deckel (oder der unterste deutlich über dem Boden), gehen diese Endschichten mit ihrem vollen Volumenanteil in die Gewichte ein. Bei nur drei Fühlern sind die Gewichte daher meist **ungleich**.

**Nicht** als `T_eq` verwenden: nur Obenfühler, nur Untenfühler, Min/Max oder Sollwert. Der Obenfühler bleibt für Komfort/WW-Bereitschaft sinnvoll — aber nicht als Energiezustand für das RC.

## Earnie-Anschluss (Live)

| Rolle | EHAL / Binding | Loxone-Merker (Default-Vorschlag) |
| --- | --- | --- |
| Äquivalente Speichertemperatur `T_eq` | `sens_temperature_heat_storage` auf dem `thermal_annual`-Consumer | `Earnie_Waermespeicher_Temp_eq` |
| Unterster Fühler `T_low` | `sens_temperature_heat_storage_low` auf dem `thermal_annual`-Consumer | `Earnie_Waermespeicher_Temp_low` |

- **`T_eq`:** RC-Zustand / Open-Loop-Boden für Live (fehlend → Fallback `setpoint_c`). Earnie speichert daraus `Q_meas = C × T_eq` je Live-Zyklus in `optimization_history.jsonl`.
- **`T_low`:** Rohwert des untersten Fühlers (nicht von Earnie in `T_eq` umgerechnet). Wenn `T_low < setpoint − tolerance`, erzwingt Live kurzfristig WP-AN, auch wenn `T_eq` noch über der Band-Untergrenze liegt (Schichtung). Fehlt das Binding, entfällt nur dieser Hinweis.

**Chart:** Im Hauskonfigurator unter Gesamt-Lastverhalten / Stündlicher Verlauf erscheint ein Wochenchart **Wärmeinhalt** (kWh): Modell `Q_sim` durchgezogen, Ist `Q_meas` gestrichelt — sobald der Live-Dienst Werte aufgezeichnet hat. Ohne Historie nur Modell + Hinweis.

Pool: weiterhin ein Sensor → `sens_temperature_water` (kein Schichtmittel nötig, solange nur ein Fühler). Gleiches `Q = C × T` und Chart-Muster.

## Loxone: Umsetzung (v1)

### 1. Sensoren erfassen

Die vorhandenen analogen Temperaturen (z. B. aus 1-Wire / Modbus / Hersteller-Regler / Hersteller-Baustein) als eigene Statuswerte oder als Eingänge eines Formel-/Status-Bausteins. Typisch sind drei Fühler:

| Symbol | Bedeutung (Beispiel) |
| --- | --- |
| `T_oben` | obere Schicht (WW-Zapfung / Bereitschaft) |
| `T_mitte` | Mitte |
| `T_unten` | untere Schicht (Rücklauf / Solar-Eintritt) |

Bei vier Fühlern kommen `T_oben_mitte` und `T_unten_mitte` an die Stelle von `T_mitte`. Reihenfolge und Bezeichnungen an die reale Sensorlage anpassen; die Physik hängt nur von den **Volumenanteilen** ab, nicht von den Namen. Wichtig ist, die **tatsächlich bestückten** Fühlertaschen und ihre Höhen zu kennen: Hat der Speicher mehr Fühlertaschen als Fühler (z. B. vier Taschen, drei Fühler), entscheidet die belegte Tasche über die Gewichte.

### 2. Formel für `T_eq` (Default: gleiche Gewichte, nur bei gleichmäßiger Verteilung)

**Status** oder **Formel**-Baustein, Ausgang z. B. `Earnie_Waermespeicher_Temp_eq` (°C). Bei drei Fühlern:

```text
(T_oben + T_mitte + T_unten) / 3
```

Bei vier Fühlern:

```text
(T_oben + T_oben_mitte + T_unten_mitte + T_unten) / 4
```

Diesen Ausgang auf einen **Virtuellen Ausgang** / Merker legen, den Earnie unter Pattern B als `sens_temperature_heat_storage` mappt (EHAL-Com). Greenfield-Titel: `Earnie_Waermespeicher_Temp_eq` (VO `VO_Earnie_Heatpump.xml`). Zusätzlich den untersten Fühler als `Earnie_Waermespeicher_Temp_low` → `sens_temperature_heat_storage_low`.

Das einfache Mittel gilt nur, wenn die Fühler in den Mitten gleich hoher Schichten sitzen (siehe oben). Sonst `w_i` proportional zur Schichtmächtigkeit setzen (siehe Schritt A):

```text
w1*T_oben + w2*T_mitte + w3*T_unten        # drei Fühler
w1*T_oben + w2*T_oben_mitte + w3*T_unten_mitte + w4*T_unten        # vier Fühler
```

mit `Σ w_i = 1`.

**Beispiel drei Fühler bei 25 % / 50 % / 75 % der Höhe** (konstanter Querschnitt): Schichtgrenzen bei 37,5 % und 62,5 %, die Endschichten reichen bis 0 % bzw. 100 %. Gewichte: `T_unten` 0,375 · `T_mitte` 0,25 · `T_oben` 0,375. Das einfache Drittel-Mittel würde die Mitte mit 0,33 statt 0,25 überbewerten.

**Beispiel vier Fühler bei 12,5 % / 37,5 % / 62,5 % / 87,5 %:** ≈ 0,25 je Fühler (Mittelpunkte gleicher Viertel).

### 3. Plausibilität in Loxone

- Wertebereich typisch ca. 5…95 °C; bei Sensorausfall keine „0“ in den Mittelwert ziehen (Fehlerzustand / letzter gültiger Wert).
- Alle Eingänge in ähnlicher Einheit (°C) und ohne Offset-Fehler.
- Optional: zusätzlich `T_oben` für Anzeige/WW-Logik behalten — getrennt von `T_eq`.

## Parameteridentifikation der Gewichte `w_i`

Ziel: `T_eq` so wählen, dass `Q = C(V_config) · T_eq` den realen Wärmeinhalt möglichst gut trifft (für Chart und spätere Adaptation von `U`).

### Schritt A — Geometrie zuerst (ohne Messung)

1. Sensorhöhen `z_i` und Speicherkörperhöhe `H` aus Datenblatt / Montage notieren (0 = Boden, H = Deckel). Nur **tatsächlich bestückte** Fühlertaschen zählen.
2. Schichtgrenzen = Mittel zwischen benachbarten Sensoren; Enden = 0 und H.
3. `V_i ∝ Δh_i` (bei zylindrischem Querschnitt); `w_i = Δh_i / H`.
4. Diese `w_i` in die Loxone-Formel eintragen.

**Beispiel:** Pufferspeicher 887 l, `H` = 2040 mm, vier Fühlertaschen bei 310 / 745 / 1250 / 1710 mm, aber nur **drei** Fühler eingebaut. Die Taschen heißen im Datenblatt **E** (310 mm), **F** (745 mm), **G** (1250 mm) und **H** (1710 mm); der Buchstabe `H` der Tasche ist nicht die Speicherhöhe `H` (2040 mm). Die Gewichte hängen davon ab, welche drei Taschen belegt sind:

| Belegte Taschen (unten → oben) | `w` unten | `w` mitte | `w` oben | Bewertung |
| --- | --- | --- | --- | --- |
| E / F / H (310 / 745 / 1710) | 0,26 | 0,34 | 0,40 | gut: beide Enden abgedeckt |
| E / G / H (310 / 1250 / 1710) | 0,38 | 0,34 | 0,27 | gut: beide Enden abgedeckt |
| F / G / H (745 / 1250 / 1710) | 0,49 | 0,24 | 0,27 | kalte Unterschicht (unter 745 mm) ungemessen, `T_eq` eher zu hoch |
| E / F / G (310 / 745 / 1250) | 0,26 | 0,23 | 0,51 | heiße Oberschicht (über 1250 mm) ungemessen, `T_eq` eher zu niedrig |

Die Werte vernachlässigen gewölbte Böden und das Volumen eines Registers (Abweichung typisch < 0,02). Als vorläufiger Startwert bis zur Klärung der Bestückung ist das einfache Drittel-Mittel vertretbar (Abweichung von den beiden guten Fällen ≤ 0,07 je Gewicht).

**Ungemessene Endschicht:** Bleibt die unterste (oder oberste) Fühlertasche unbelegt, trägt der nächstgelegene Fühler deren Volumen mit. Ist die Schicht dort deutlich kälter (unten: Rücklauf von Wärmepumpe und Solar) bzw. heißer als der Fühler, verfälscht das `T_eq`. Beispiel: Fühler auf 745 mm mit Gewicht 0,49 und ein Boden, der 15 K kälter ist als dieser Fühler. Dann liegt `T_eq` um rund 4 K zu hoch, bei 887 l (`C` ≈ 1,03 kWh/K) sind das etwa 4 kWh Fehler im Wärmeinhalt. Der Fehler wirkt besonders bei entladenem Speicher, also genau dort, wo die Untergrenze für den Wärmepumpen-Start geprüft wird. Wenn möglich, die freie Tasche am Speicherende mit einem zusätzlichen Tauchfühler belegen. Eine Tauchhülse nimmt oft zwei Fühler auf, auch wenn dort schon ein Zeigerthermometer steckt. Die Gewichte liegen dann wieder nahe 0,25.

### Schritt B — Feinschliff mit Ruhephase (empfohlen)

Wenn die Geometrie unsicher ist oder der Querschnitt nicht konstant:

1. **Ausgleichsphase:** Speicher weder stark beladen noch gezapft (keine WP-/Solar-Ladung, keine große WW-Entnahme), z. B. nachts mehrere Stunden.
2. Schichtung baut sich ab; die Fühlertemperaturen nähern sich an. Dann gilt näherungsweise `T_eq ≈ T_oben ≈ … ≈ T_unten` — Gewichte sind unkritisch.
3. **Kontrollfall mit klarer Schichtung:** nach Solar-/WP-Ladung oder nach WW-Zapfung alle Fühler-Istwerte und das volumengewichtete `T_eq` notieren.
4. Mit dem in Earnie konfigurierten `volume_liters` ist `C` fest. Vergleich im Wochenchart **Wärmeinhalt** (`Q_sim` vs. `Q_meas`) im Hauskonfigurator.
5. Wenn `Q_meas` systematisch **über** dem plausiblen Modell liegt bei gleicher Dynamik: effektives Volumen/C oder Gewichte prüfen (zu viel Gewicht auf heiße Oberschicht). Systematisch **unter**: zu viel Gewicht auf kalte Unterschicht oder Volumen zu klein.
6. Gewichte nur in kleinen Schritten ändern (z. B. ±0,05) und Summe 1 halten; nicht gleichzeitig Volumen und alle `w_i` „frei“ drehen.

### Schritt C — Was Adaptation später übernimmt

Thermals P3 adaptiert primär Verluste (`heat_loss_kw_per_k`) und ggf. effektives C gegen `Q_meas` aus **diesem** `T_eq`. Falsche Schichtgewichte erzeugen einen Bias in `Q_meas` und damit in der Adaptation — deshalb Gewichte einmalig sauber setzen (A/B), nicht der Adaptation überlassen.

## Kurz-Checkliste

- [ ] Belegte Fühlertaschen und ihre Höhen prüfen (nicht nur die Anzahl der Taschen)
- [ ] Drei oder vier Sensoren → eine Formel `T_eq` (Default: arithmetisches Mittel nur bei gleichmäßiger Verteilung, sonst Gewichte aus Schritt A)
- [ ] Merker `Earnie_Waermespeicher_Temp_eq` (oder eigener Name) in EHAL-Com auf `sens_temperature_heat_storage`
- [ ] Bei bekannter Geometrie: `w_i` aus Höhenanteilen
- [ ] Optional Feinschliff nach Ladung/Zapfung vs. Earnie-Chart
- [ ] Obenfühler nicht allein als Earnie-Ist verwenden
