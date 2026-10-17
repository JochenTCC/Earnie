# Historische Leistungsprofil-CSV (Hausprofil)

Im **Hauskonfigurator** lassen sich Jahres-Leistungsprofile als CSV hinterlegen – für das gesamte Haus und optional je Verbraucher. Gemeint ist die Leistung, die Verbraucher im Haus tatsächlich bezogen haben. Woher sie stammt (Netz, PV-Anlage oder Batterie), spielt keine Rolle. Kennzahlen in **kWh** (z. B. Monatsverbrauch, Jahresverbrauch) bleiben Energiegrößen und heißen weiterhin Verbrauch bzw. Erzeugung.

Zusätzlich kann ein **PV-Erzeugungsprofil [kW]** (Summe aller Anlagen) importiert werden. Auch hier zählt die gesamte Leistung der PV-Anlagen, unabhängig davon, ob Verbraucher im Haus sie direkt genutzt haben, ob sie in die Batterie geflossen ist oder ins Netz eingespeist wurde.

**Begriffe:**

- **Profil:** Zeitreihe der **Leistung** (Lastprofil, Leistungsprofil, PV-Erzeugungsprofil; Einheit kW).
- **Verbrauch bzw. Erzeugung:** Summen und Kennzahlen der **Energie** (Einheit kWh).

## Kanonisches Format

```text
timestamp;power_kw
2023-01-01 00:00:00;3.177
```


| Regel        | Bedeutung                                                                                                                                                          |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Trennzeichen | Semikolon (`;`)                                                                                                                                                    |
| Zeitstempel  | ISO-ähnlich `YYYY-MM-DD HH:MM:SS`                                                                                                                                  |
| Leistung     | Last bzw. PV-Erzeugung als **Leistungsprofil in kW**, positiv                                                                                                      |
| Länge        | Kurze Serien sind zur visuellen Kontrolle erlaubt. Für den **Szenario-Explorer** mit importiertem PV bzw. Meter-Bezug sind **≥8760 Stunden** (ca. 12 Monate) nötig, sonst rechnet er mit synthetischen Werten. |
| Abtastung    | Beliebig. Beim Import rechnet Earnie auf Stundenwerte um: zuerst Zero-Order-Hold auf ein 1‑Minuten-Raster, dann Stundenmittel = ∫P·dt / 1 h. Bei Lücken gilt der letzte Wert bis zum nächsten Sample. |


Beim Upload schreibt Earnie eine **normalisierte** Datei nach `earnie_env/config/uploads/` (im Container: `config/uploads/`). Der Dateiname leitet sich vom Original ab: `{Originalname}_resampled.csv` (z. B. `BEZUG-2025-22.7.2026_resampled.csv`).

- **Gleicher Originalname:** Ein erneuter Upload überschreibt die vorhandene resampled-Datei.
- **Anderer Originalname:** Earnie legt eine neue Datei an, und der Profil-Pfad zeigt auf diese neue Datei.

## Importmodus (Hausprofil)

Unter **Historische Jahres-Leistungsprofile [kW] (CSV)** stehen drei Modi zur Wahl:


| Modus                     | Inhalt                                                                                                                        |
| ------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| **Getrennte CSVs**        | Lastprofil (für den Abgleich Ist vs. Modell) und optional PV-Erzeugungsprofil als eigene Dateien.                              |
| **Loxone Energiemonitor** | Eine Statistik-Datei. `Leistung Verbrauch [kW]` ist Pflicht und dient direkt als Lastprofil. Optional sind `Leistung Produktion [kW]` (PV), `Leistung Batterie` und `Leistung Energieversorger [kW]` (Netz). Eine Bilanz-Ableitung findet nicht statt, der SOC wird ignoriert. |
| **Bilanz**                | Aus PV und Netz (Batterie optional, sonst 0) leitet Earnie das Lastprofil ab: \(P_\mathrm{Ges} = P_\mathrm{PV} + P_\mathrm{Batt} + P_\mathrm{Grid}\) |


**Bevorzugter Import:** Leistungsdaten in kW (`timestamp;power_kw`). Kumulierte **Energiezähler [kWh]** werden ebenfalls akzeptiert und automatisch in mittlere Leistung [kW] umgerechnet (siehe [Energiezähler-CSV](#energiezähler-csv-kwh)).

**Bilanz-Vorzeichen:**

- **Positiv** bei Batterie und Netz bedeutet Leistung **in** das Haussystem (Entladen bzw. Netzbezug).
- **Negativ** bedeutet Laden bzw. Einspeisung.
- Ein negatives \(P_\mathrm{Ges}\) setzt Earnie auf 0 und gibt eine Warnung aus.
- Optional lässt sich das Vorzeichen je Serie umkehren.

Gespeicherte Pfade im Hausprofil:

- `total_profile_csv`: Lastprofil
- `pv_profile_csv`: optionales PV-Erzeugungsprofil
- `battery_profile_csv` / `grid_profile_csv`: Serien für den Modus Bilanz
- `historical_csv_source`: gewählter Modus (`separate` / `energiemonitor` / `balance`)

### Historische Jahres-Leistungsprofile [kW] (CSV)

Die Überschrift **Historische Jahres-Leistungsprofile [kW]** weist darauf hin, dass der Import **optional** ist. Darunter folgt der **aufklappbare Bereich** „Historische Jahres-Leistungsprofile [kW] (CSV)“. Er enthält den Datenimport (getrennte CSVs, Energiemonitor oder Bilanz) und einen Leistungsplot zur Kontrolle (QC).

### Gesamt-Lastverhalten

Der Abschnitt **Gesamt-Lastverhalten** ist immer sichtbar, unabhängig von den CSV-Importen:

- **Mit Lastprofil-CSV** (direkt, Energiemonitor oder Bilanz): Der Abschnitt zeigt den **Monatsverbrauch** (Ist vs. gestapeltes Modell, Energie in kWh) und den **stündlichen Verlauf** (Leistung).
- **Ohne CSV:** Der Abschnitt zeigt nur das modellierte Hausprofil (Monats- und Wochencharts).

## Loxone-CSV (Einzelserie)

Exportierte Loxone-Dateien mit einer Leistungsserie erkennt Earnie beim Import. Earnie rechnet sie in das kanonische Format um, einschließlich stündlicher Mittelung.

Akzeptierte Layouts:


| Layout                   | Beispiel-Kopfzeile                                | Wertspalte                                                                      |
| ------------------------ | ------------------------------------------------- | ------------------------------------------------------------------------------- |
| Getrennt Datum + Zeit    | `Datum;Zeit;Wert` oder `Datum;Zeit;Wert;Leistung` | Spalte `Leistung`, falls vorhanden; sonst die **letzte** Spalte nach Datum/Zeit |
| Kombinierter Zeitstempel | `Datum/Uhrzeit;Wert` bzw. `dd.mm.YYYY HH:MM:SS;…` | Spalte `Leistung`, falls vorhanden; sonst die letzte Spalte                     |


**Trennzeichen und Dezimalzeichen:**

- Üblich ist `;` als Spaltentrenner mit `,` als Dezimalzeichen (z. B. `0,03`).
- Excel-Exporte mit deutscher Einstellung nutzen oft `,` als Spaltentrenner und ebenfalls `,` als Dezimalzeichen. Die Zahlen stehen dann in Anführungszeichen (`"0,03"`).
- Earnie erkennt beide Varianten sowie `,` als Spaltentrenner mit `.` als Dezimalzeichen.

Dreispaltige Digitalsignale (`Datum;Zeit;0/1`) sind zulässig. Beim Verbraucher-Import lassen sie sich optional mit der Nennleistung skalieren (siehe [Digitale Ein/Aus-Signale](#digitale-einaus-signale-01)).

## Energiezähler-CSV (kWh)

Neben Leistungszeitreihen erkennt Earnie **kumulierte Zählerstände** automatisch und rechnet sie in stündliche mittlere Leistung (kW) um:

```text
Datum;Zeit;Counter [kWh]
01.01.2025;02:00:00;5652,226
01.01.2025;03:00:00;5652,435
```

| Regel | Bedeutung |
| ----- | --------- |
| Wert | Zählerstand in **kWh**, also integrierte Energie ∫P·dt (keine Momentanleistung) |
| Umrechnung | \(P(t_i)=(E_{i+1}-E_i)/\Delta t_i\) mit \(\Delta t_i\) in Stunden (beliebige Abtastung) |
| Erkennung | Kopfzeile mit `[kWh]` oder Namen wie `Zähler`/`Counter`/`Ertrag`; sonst eine Heuristik (selten nahe 0, kaum fallend, große Medianwerte) |
| Leistung bleibt | Kopfzeile mit `[kW]` oder `Leistung` → normaler Import als Leistungsserie |
| Zähler-Reset | Ein negatives Intervall wird **ignoriert** (`P=0`) und als Warnung im Log vermerkt |

Das gilt für **Lastprofil [kW] (Gesamt)**, **PV-Erzeugungsprofil [kW]** und Verbraucher-CSVs im Modus Getrennte CSVs.

### Bilanz Netz-Leistung: Leistung oder zwei Energiezähler

Für den Upload **Netz-Leistung** im Modus Bilanz gilt zusätzlich:

| Variante | Kopfzeile (Wertspalten) | Verhalten |
| -------- | ----------------------- | --------- |
| Leistung | Erste Wertspalte mit `[kW]` (eine bipolare Serie) | Positiv = Netzbezug, negativ = Einspeisung |
| Zwei Zähler | Erste Wertspalte Bezug `[kWh]`, zweite Einspeisung `[kWh]` | Beide gelten als kumulierte Zähler → \(\Delta E/\Delta t\); Netzleistung \(P = P_\mathrm{Bezug} - P_\mathrm{Einspeisung}\) |
| Ungültig | Nur eine Wertspalte mit `[kWh]` | Earnie lehnt den Import ab, weil für das Netz Bezug und Einspeisung nötig sind |

```text
Datum;Zeit;Bezug [kWh];Einspeisung [kWh]
01.01.2025;00:00:00;1000,000;200,000
01.01.2025;01:00:00;1002,000;200,500
```

Ergebnis: \(P_\mathrm{Bezug}=2\,\mathrm{kW}\) und \(P_\mathrm{Einspeisung}=0{,}5\,\mathrm{kW}\), also Netz \(+1{,}5\,\mathrm{kW}\).

Diese Zwei-Spalten-Regel gilt **nur** für **Netz-Leistung** im Modus Bilanz. Batterie, PV und Last nutzen den oben beschriebenen Import mit einem Zähler.

## Gesamt-CSV (`total_profile_csv`)

Die Gesamt-CSV ist optional. Sie dient dem Abgleich Ist vs. Modell und ist die Grundlage für die Rest-Grundlast, wenn Verbraucher-CSVs abgezogen werden.

Die Kennzahlen **Ist-Jahresverbrauch** und **Modell-Jahresverbrauch** beziehen sich auf die **letzten 8760 Stunden** der CSV (ca. 12 Monate), auch wenn die Datei länger ist. Monats- und Wochencharts nutzen weiterhin die gesamte Zeitreihe.

Im Abgleich **Ist vs. Modell** (Hauskonfigurator, Abschnitt **Gesamt-Lastverhalten**) lässt sich die Verteilung der Modell-Basislast wählen (`baseload_distribution` am Hausprofil):

| Modus | Verhalten |
| ----- | --------- |
| **Jahres-Rest gleichmäßig** (`equal`, Standard) | Eine konstante Grundlast aus dem Jahres-Rest Ist − Verbraucher (letzte 8760 h). Im Chart beträgt sie mindestens **1 %** des konfigurierten Jahresverbrauchs. Im Szenario-Explorer (Pfad A): flache `baseload_kwh/8760`. |
| **Monats-Rest je Monat** (`monthly`) | Pro Kalendermonat `max(0, Ist − Verbraucher)`, gleichmäßig auf die Stunden des Monats verteilt. Im Chart gibt es keine 1 %-Untergrenze. Monate, in denen die Verbraucher mehr als das Ist ergeben, bleiben ohne Basislast. **Gilt für die Charts und für Pfad A im Szenario-Explorer**, sofern eine Gesamt-CSV vorhanden ist. |

**Pfad B im Szenario-Explorer** (Gesamt-CSV vorhanden und alle Verbraucher der Rollen Gesteuert/Manuell mit aktiver CSV) verwendet weiterhin den stündlichen Meter-Rest. `baseload_distribution` hat auf Pfad B keinen Einfluss.

Die Modell-Basislast im Chart entspricht damit dem gewählten Jahres- oder Monats-Rest plus den gestapelten Verbrauchern. Der stündliche Meter-Rest aus Pfad B fließt dort nicht ein.

## PV-Erzeugungsprofil (`pv_profile_csv`)

Optionaler Jahresverlauf der PV-Leistung als Summe über alle PV-Anlagen. Im Szenarienkonfigurator lässt sich pro Szenario festlegen, ob der Szenario-Explorer dieses Profil statt der PV aus Wetterdaten (Open-Meteo) für die Berechnung nutzt.

- **Mindestlänge:** Die PV-CSV muss dafür mindestens ca. **12 Monate** abdecken.
- **Kürzere Importe** bleiben im Hauskonfigurator sichtbar, der Szenario-Explorer verwendet sie aber **nicht** und greift auf Open-Meteo zurück.
- **Darstellung:** In den Lastverhaltens-Charts erscheint importiertes PV zusätzlich als **punktierte** Linie.

## Verbraucher-CSV (`profile_csv` + `use_profile_csv`)

Pro Verbraucher:

1. CSV-Pfad angeben oder Datei hochladen.
2. Checkbox **„Von Basis-Last abziehen“** setzen oder leer lassen.

- **Aktiv:** Earnie nutzt die Last aus der CSV statt der Synthese und zieht sie von der Basislast ab (im Hauskonfigurator und, bei Pfad B, im Szenario-Explorer).
- **Inaktiv:** Earnie nutzt das synthetische Modell bzw. den Schedule. Der Pfad kann gespeichert bleiben, fließt aber nicht in die Modellierung ein.

| earnie_role | Hauskonfigurator | Szenario-Explorer | Live |
| ----------- | ---------------- | ----------------- | ---- |
| Bekannt | Abzug von Basislast | feste zusätzliche Last aus CSV (nicht Schedule) | wie Szenario-Explorer |
| Gesteuert | Abzug von Basislast | CSV-Energie über den Horizont als MILP-Ziel; Timing wird optimiert | CSV ignorieren, Schedule |
| Manuelles Gerät | Abzug von Basislast | wie Gesteuert | Nutzer-Tagesplan, wenn aktiv; sonst weder CSV noch Default-Schedule |

**Basislast im Szenario-Explorer:**

- **Pfad B** (stündlicher Meter-Rest) gilt, wenn eine Gesamt-CSV vorhanden ist und alle Verbraucher der Rollen Gesteuert/Manuell eine aktive CSV haben.
- **Pfad A** gilt in allen anderen Fällen. Bei `baseload_distribution=monthly` verwendet er monatsweise Ist − Modellverbraucher, sonst eine flache `baseload_kwh/8760`.

Die synthetische `cons_data.csv` nutzt die konfigurierte Grundlast (`baseload_kwh / 8760`). Ausnahmen: Der Szenario-Explorer läuft mit Pfad B oder mit Pfad A und Monats-Rest aus dem Hausprofil.

### Digitale Ein/Aus-Signale (0/1)

Enthält die CSV nach der Erkennung überwiegend nur die Werte **0** und **1** (z. B. den Schaltzustand eines Geräts), fragt der Hauskonfigurator beim Import einmalig nach. Zur Wahl steht, die Werte mit der **Nennleistung (kW)** des Verbrauchers zu multiplizieren.

- **Ja:** Earnie schreibt die Datei als kanonisches Leistungsprofil neu (0 bzw. Nennleistung).
- **Nein:** Die Werte bleiben unverändert (0/1).

Die Haus-Gesamt-CSV (`total_profile_csv`) wird nicht so skaliert, weil es dort keine einzelne Nennleistung gibt.

## Test-Export aus Live-`cons_data`

Für lokale Import-Tests lässt sich aus der Live-Datei `cons_data.csv` eine CSV für das **PV-Erzeugungsprofil** und eine **Energiemonitor**-CSV (nur relevante Spalten) erzeugen:

```text
python -m scripts.export_historical_test_csvs --out-dir Historical-Data/export-test
```

Optionale Parameter: `--cons-data`, `--from`, `--to`. Die Dateien sind Loxone-kompatibel und lassen sich im Hauskonfigurator wieder einlesen (getrennte CSVs bzw. Energiemonitor). Nötig sind mindestens 8760 Stunden.

## Von Loxone Energieflussmonitor zum Hausprofil

Kurzanleitung für die Einrichtung. Details und Rollen-Tabelle stehen in der [EFM-Auto-Sync-Spezifikation](../dev/done/efm-auto-sync.md), ein manueller Blueprint im Repo-Plan `energieflussmonitor_hausprofil_blueprint_a`.

1. In Loxone **Energieflussmonitor** und **Zähler** für Netz, PV, Speicher und Verbraucher anlegen (flach bzw. bewusst flach halten).
2. Auf der Seite **Smarthome-Backend** den **Loxone-Import** ausführen. Er übernimmt Merker und EFM-Zähler ins Hausprofil bzw. in die `ehal_bindings`, optional auch Live-`flex.{slug}.sens_power_act` = Zähler-Bezeichnung. Freigabe-Merker (`flex.{slug}.set_enable`) und Feintuning bleiben Handarbeit unter **EHAL-Com → Signalliste**.
3. **Statistik-CSVs einzeln** je Serie exportieren und im Hauskonfigurator hochladen. Für das Haus stehen Energiemonitor, Bilanz oder getrennte CSVs zur Wahl. Für Verbraucher dient die Einzelserie als `profile_csv`, ggf. mit „Von Basis-Last abziehen“. Einen Import aller EFM-Leistungsflüsse in einem Schritt als Mehrspalten-Datei gibt es **nicht**.

## Abgrenzung Live-Loxone und CSV-Ebenen


| Ebene            | Ort                                                                    | Zweck                            |
| ---------------- | ---------------------------------------------------------------------- | -------------------------------- |
| Runtime          | `scenario_explorer_conf.path_cons_data` → `cons_data.csv`       | Live + Szenario-Explorer         |
| Hausmodell       | `house_profiles`: `total_profile_csv`, `pv_profile_csv`, `profile_csv` | Planung, Ist-vs-Modell, Synthese |
| Offline-Flex-Log | `path_historical_log` am Verbraucher (Legacy-Overlay / Profil)         | Einzelserie → cons_data          |


Das Feld `path_historical_log` (flexible Verbraucher, Hausprofil) gehört zum Offline-Weg Loxone-Log → `cons_data.csv`. Es ist unabhängig von den Jahres-CSVs im Hausprofil. Die früheren Keys `path_consumption` / `path_production` in `config.json` sind entfernt (data-model v3).
