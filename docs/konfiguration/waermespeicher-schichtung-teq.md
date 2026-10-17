# Wärmespeicher: äquivalente Temperatur `T_eq` (Schichtspeicher → Earnie)

Earnie bildet den Wärmespeicher als **Einknoten-Modell** ab: eine Temperatur, ein Volumen. Viele Warmwasser- und Pufferspeicher sind dagegen **Schichtspeicher** mit mehreren Temperaturfühlern, typisch drei oder vier in unterschiedlicher Höhe. Für den Live-Vergleich und die spätere Adaptation muss das Smart Home deshalb **eine** Temperatur liefern, die denselben **Wärmeinhalt** wie der geschichtete Speicher abbildet.

Entwickler-Kontext: [thermals-p2.md](../dev/done/thermals-p2.md) (Abschnitt *Stratified store → T_eq*).
## Physik (kurz)

Die Wärmekapazität ergibt sich aus dem konfigurierten Volumen (wie im Code):

```text
C [kWh/K] = (V_liter / 1000) × 1.163
```

Wärmeinhalt (Referenz 0 °C):

```text
Q [kWh] = C × T_eq
```

`T_eq` ist die **volumengewichtete** Mitteltemperatur der Schichten:

```text
T_eq = Σ (V_i · T_i) / V_gesamt
```

Sitzen die `n` Fühler in den Mittelpunkten gleich hoher Schichten, ist `T_eq` das arithmetische Mittel. Das gilt bei drei Fühlern auf 1/6, 3/6 und 5/6 der Höhe sowie bei vier Fühlern auf 1/8, 3/8, 5/8 und 7/8:

```text
T_eq = (T1 + … + Tn) / n        # drei Sensoren: (T1 + T2 + T3) / 3
```

Allgemein mit Gewichten `w_i` (`Σ w_i = 1`):

```text
T_eq = w1·T1 + … + wn·Tn        # drei Sensoren: w1·T1 + w2·T2 + w3·T3
```

Die **Endschichten** reichen bis zum Boden bzw. Deckel: Der äußerste Fühler steht für die gesamte Schicht bis zum Speicherende. Sitzt der oberste Fühler deutlich unter dem Deckel (oder der unterste deutlich über dem Boden), gehen diese Endschichten mit ihrem vollen Volumenanteil in die Gewichte ein. Bei nur drei Fühlern sind die Gewichte daher meist **ungleich**.

Ungeeignet als `T_eq` sind: nur der Obenfühler, nur der Untenfühler, Min/Max oder der Sollwert. Der Obenfühler bleibt für Komfort und WW-Bereitschaft sinnvoll, taugt aber nicht als Energiezustand für das RC-Modell.

## Earnie-Anschluss (Live)

| Rolle | EHAL / Binding | Loxone-Merker (Default-Vorschlag) |
| --- | --- | --- |
| Äquivalente Speichertemperatur `T_eq` | `sens_temperature_heat_storage` auf dem `thermal_annual`-Consumer | `Earnie_Waermespeicher_Temp_eq` |
| Unterster Fühler `T_low` | `sens_temperature_heat_storage_low` auf dem `thermal_annual`-Consumer | `Earnie_Waermespeicher_Temp_low` |

- **`T_eq`:** RC-Zustand und Open-Loop-Boden für Live (fehlt der Wert, greift der Fallback `setpoint_c`). Earnie speichert daraus je Live-Zyklus `Q_meas = C × T_eq` in `optimization_history.jsonl`.
- **`T_low`:** Rohwert des untersten Fühlers, den Earnie nicht in `T_eq` umrechnet. Gilt `T_low < setpoint − tolerance`, erzwingt Live kurzfristig WP-AN, auch wenn `T_eq` noch über der Band-Untergrenze liegt (Schichtung). Fehlt das Binding, entfällt nur dieser Hinweis.

**Chart:** Unter **Live-Cockpit → Analyse Verbrauch & Kosten** erscheint ein Chart **Wärmeinhalt** (kWh) für das gewählte 7- oder 28-Tage-Fenster. Die Daten stammen aus `thermal_observability` in `optimization_history.jsonl`.

- **Linien:** Live-Sim `Q_sim` durchgezogen, Ist `Q_meas` gestrichelt.
- **Prognose-Fächer:** Zusätzlich zeigt der Chart die **letzten 12 stündlichen Q-Prognosen** (`horizon_q_sim_kwh`, Wärmespeicher und Pools). Alle Linien teilen den größten gemeinsamen Horizont, maximal 24 h.
- **Ohne Historie:** Statt des Charts erscheint ein Hinweis.
- **Hauskonfigurator:** Unter Stündlicher Verlauf bleibt nur die Modell-Temperatur (°C), dort gibt es kein Wärmeinhalt-Chart.

Pool: weiterhin ein Fühler → `sens_temperature_water`. Ein Schichtmittel ist nicht nötig, solange nur ein Fühler vorhanden ist. Es gelten dasselbe `Q = C × T` und dasselbe Chart-Muster.

## Loxone: Umsetzung (v1)

### 1. Sensoren erfassen

Die vorhandenen analogen Temperaturen (z. B. aus 1-Wire, Modbus, Hersteller-Regler oder Hersteller-Baustein) als eigene Statuswerte anlegen oder als Eingänge eines Formel- bzw. Status-Bausteins verwenden. Typisch sind drei Fühler:

| Symbol | Bedeutung (Beispiel) |
| --- | --- |
| `T_oben` | obere Schicht (WW-Zapfung / Bereitschaft) |
| `T_mitte` | Mitte |
| `T_unten` | untere Schicht (Rücklauf / Solar-Eintritt) |

Bei vier Fühlern treten `T_oben_mitte` und `T_unten_mitte` an die Stelle von `T_mitte`. Reihenfolge und Bezeichnungen an die reale Fühlerlage anpassen; die Physik hängt nur von den **Volumenanteilen** ab, nicht von den Namen.

Entscheidend sind die **tatsächlich bestückten** Fühlertaschen und ihre Höhen. Hat der Speicher mehr Fühlertaschen als Fühler (z. B. vier Taschen, drei Fühler), bestimmt die belegte Tasche die Gewichte.

### 2. Formel für `T_eq` (Default: gleiche Gewichte, nur bei gleichmäßiger Verteilung)

**Status**- oder **Formel**-Baustein mit Ausgang z. B. `Earnie_Waermespeicher_Temp_eq` (°C). Bei drei Fühlern:

```text
(T_oben + T_mitte + T_unten) / 3
```

Bei vier Fühlern:

```text
(T_oben + T_oben_mitte + T_unten_mitte + T_unten) / 4
```

Diesen Ausgang auf einen **Virtuellen Ausgang** bzw. Merker legen, den Earnie in EHAL-Com entity-scoped als `sens_temperature_heat_storage` mappt. Vorgeschlagener Titel bei Neuanlage (Greenfield): `Earnie_Waermespeicher_Temp_eq` (VO `VO_Earnie_Heatpump.xml`). Zusätzlich den untersten Fühler als `Earnie_Waermespeicher_Temp_low` → `sens_temperature_heat_storage_low` anlegen.

Das einfache Mittel gilt nur, wenn die Fühler in den Mitten gleich hoher Schichten sitzen (siehe [Physik](#physik-kurz)). Andernfalls `w_i` proportional zur Schichtmächtigkeit setzen (siehe Schritt A):

```text
w1*T_oben + w2*T_mitte + w3*T_unten        # drei Fühler
w1*T_oben + w2*T_oben_mitte + w3*T_unten_mitte + w4*T_unten        # vier Fühler
```

mit `Σ w_i = 1`.

**Beispiel drei Fühler bei 25 % / 50 % / 75 % der Höhe** (konstanter Querschnitt): Die Schichtgrenzen liegen bei 37,5 % und 62,5 %, die Endschichten reichen bis 0 % bzw. 100 %. Gewichte: `T_unten` 0,375 · `T_mitte` 0,25 · `T_oben` 0,375. Das einfache Drittel-Mittel würde die Mitte mit 0,33 statt 0,25 überbewerten.

**Beispiel vier Fühler bei 12,5 % / 37,5 % / 62,5 % / 87,5 %:** ≈ 0,25 je Fühler (Mittelpunkte gleicher Viertel).

### 3. Plausibilität in Loxone

- **Wertebereich:** typisch ca. 5…95 °C. Bei Sensorausfall Fehlerzustand oder letzten gültigen Wert verwenden und keine „0“ in den Mittelwert ziehen.
- **Einheit:** Alle Eingänge in °C und ohne Offset-Fehler.
- **Anzeige:** Optional `T_oben` zusätzlich für Anzeige und WW-Logik behalten, getrennt von `T_eq`.

## Parameteridentifikation der Gewichte `w_i`

Ziel: `T_eq` so wählen, dass `Q = C(V_config) · T_eq` den realen Wärmeinhalt möglichst gut trifft. Das ist für den Chart und die spätere Adaptation von `U` wichtig.

### Schritt A – Geometrie zuerst (ohne Messung)

1. Fühlerhöhen `z_i` und Speicherkörperhöhe `H` aus Datenblatt oder Montage notieren (0 = Boden, H = Deckel). Nur **tatsächlich bestückte** Fühlertaschen zählen.
2. Schichtgrenzen in die Mitte zwischen benachbarten Fühlern legen; die Enden sind 0 und H.
3. Bei zylindrischem Querschnitt gilt `V_i ∝ Δh_i`, also `w_i = Δh_i / H`.
4. Diese `w_i` in die Loxone-Formel eintragen.

**Beispiel:** Pufferspeicher 887 l, `H` = 2040 mm, vier Fühlertaschen bei 310 / 745 / 1250 / 1710 mm, aber nur **drei** Fühler eingebaut. Die Taschen heißen im Datenblatt **E** (310 mm), **F** (745 mm), **G** (1250 mm) und **H** (1710 mm); der Buchstabe `H` der Tasche ist nicht die Speicherhöhe `H` (2040 mm). Die Gewichte hängen davon ab, welche drei Taschen belegt sind:

| Belegte Taschen (unten → oben) | `w` unten | `w` mitte | `w` oben | Bewertung |
| --- | --- | --- | --- | --- |
| E / F / H (310 / 745 / 1710) | 0,26 | 0,34 | 0,40 | gut: beide Enden abgedeckt |
| E / G / H (310 / 1250 / 1710) | 0,38 | 0,34 | 0,27 | gut: beide Enden abgedeckt |
| F / G / H (745 / 1250 / 1710) | 0,49 | 0,24 | 0,27 | kalte Unterschicht (unter 745 mm) ungemessen, `T_eq` eher zu hoch |
| E / F / G (310 / 745 / 1250) | 0,26 | 0,23 | 0,51 | heiße Oberschicht (über 1250 mm) ungemessen, `T_eq` eher zu niedrig |

Die Werte vernachlässigen gewölbte Böden und das Volumen eines Registers (Abweichung typisch < 0,02). Bis die Bestückung geklärt ist, ist das einfache Drittel-Mittel als vorläufiger Startwert vertretbar. Es weicht von den beiden guten Fällen um höchstens 0,07 je Gewicht ab.

**Ungemessene Endschicht:** Bleibt die unterste (oder oberste) Fühlertasche unbelegt, trägt der nächstgelegene Fühler deren Volumen mit. Ist die Schicht dort deutlich kälter (unten: Rücklauf von Wärmepumpe und Solar) bzw. heißer als der Fühler, verfälscht das `T_eq`.

- **Beispiel:** Fühler auf 745 mm mit Gewicht 0,49, der Boden ist 15 K kälter als dieser Fühler. Dann liegt `T_eq` um rund 4 K zu hoch. Bei 887 l (`C` ≈ 1,03 kWh/K) sind das etwa 4 kWh Fehler im Wärmeinhalt.
- **Auswirkung:** Der Fehler wirkt besonders bei entladenem Speicher, also genau dort, wo Earnie die Untergrenze für den Wärmepumpen-Start prüft.
- **Abhilfe:** Wenn möglich, die freie Tasche am Speicherende mit einem zusätzlichen Tauchfühler belegen. Eine Tauchhülse nimmt oft zwei Fühler auf, auch wenn dort schon ein Zeigerthermometer steckt. Die Gewichte liegen dann wieder nahe 0,25.

### Schritt B – Feinschliff mit Ruhephase (empfohlen)

Dieser Schritt lohnt sich, wenn die Geometrie unsicher oder der Querschnitt nicht konstant ist:

1. **Ausgleichsphase abwarten:** Der Speicher wird weder stark beladen noch gezapft (keine WP- oder Solar-Ladung, keine große WW-Entnahme), z. B. nachts über mehrere Stunden.
2. **Schichtung abbauen lassen:** Die Fühlertemperaturen nähern sich an. Dann gilt näherungsweise `T_eq ≈ T_oben ≈ … ≈ T_unten`, die Gewichte sind unkritisch.
3. **Kontrollfall mit klarer Schichtung:** Nach Solar- oder WP-Ladung bzw. nach WW-Zapfung alle Fühler-Istwerte und das volumengewichtete `T_eq` notieren.
4. **Mit Earnie vergleichen:** Mit dem in Earnie konfigurierten `volume_liters` ist `C` fest. Den Vergleich zeigt der Chart **Wärmeinhalt** (`Q_sim` vs. `Q_meas`) unter **Analyse Verbrauch & Kosten**.
5. **Abweichung deuten:** Liegt `Q_meas` bei gleicher Dynamik systematisch **über** dem plausiblen Modell, effektives Volumen bzw. C oder die Gewichte prüfen (zu viel Gewicht auf der heißen Oberschicht). Liegt es systematisch **darunter**, ist zu viel Gewicht auf der kalten Unterschicht oder das Volumen zu klein.
6. **Behutsam nachstellen:** Gewichte nur in kleinen Schritten ändern (z. B. ±0,05) und die Summe bei 1 halten. Volumen und alle `w_i` nicht gleichzeitig „frei“ verändern.

### Schritt C – Was die Adaptation später übernimmt

Die Adaptation der thermischen Parameter passt in erster Linie die Verluste (`heat_loss_kw_per_k`) und ggf. das effektive C an `Q_meas` aus **diesem** `T_eq` an. Falsche Schichtgewichte verzerren `Q_meas` und damit auch die Adaptation. Die Gewichte deshalb einmalig sorgfältig setzen (Schritt A und B), statt sie der Adaptation zu überlassen.

## Kurz-Checkliste

- [ ] Belegte Fühlertaschen und ihre Höhen prüfen (nicht nur die Anzahl der Taschen)
- [ ] Aus drei oder vier Fühlern eine Formel `T_eq` bilden (Default: arithmetisches Mittel nur bei gleichmäßiger Verteilung, sonst Gewichte aus Schritt A)
- [ ] Merker `Earnie_Waermespeicher_Temp_eq` (oder eigenen Namen) in EHAL-Com auf `sens_temperature_heat_storage` mappen
- [ ] Bei bekannter Geometrie: `w_i` aus Höhenanteilen ableiten
- [ ] Optional: Feinschliff nach Ladung oder Zapfung mit dem Earnie-Chart abgleichen
- [ ] Obenfühler nicht allein als Earnie-Ist verwenden
