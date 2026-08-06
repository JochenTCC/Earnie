# Historische Leistungsprofil-CSV (Hausprofil)

Im **Hauskonfigurator** können Sie Jahres-Leistungsprofile als CSV hinterlegen — für das gesamte Haus und optional je Verbraucher. Gemeint ist die Leistung, die im Haus tatsächlich von Verbrauchern gezogen wurde, egal woher sie gespeist wurde (Netz, PV-Anlage oder Batterie). Kennzahlen in **kWh** (z. B. Monatsverbrauch, Jahresverbrauch) bleiben Energiegrößen und heißen weiterhin Verbrauch bzw. Erzeugung.

Zusätzlich kann ein **PV-Erzeugungsprofil [kW]** (Summe aller Anlagen) importiert werden. Auch hier ist die gesamte Leistung gemeint, die aus den PV-Anlagen geflossen ist, egal ob sie direkt im Haus von Verbrauchern genutzt wurde, in die Batterie oder ins Netz eingespeist wurde.

**Terminologie:** Zeitreihen der **Leistung** → *Profil* (Lastprofil / Leistungsprofil / PV-Erzeugungsprofil, Einheit kW). Summen und Kennzahlen der **Energie** → *Verbrauch* bzw. *Erzeugung* (Einheit kWh).

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
| Länge        | Kurze Serien sind erlaubt (visuelle Kontrolle). Für den **Szenario-Explorer** mit importiertem PV bzw. Meter-Bezug sind **≥8760 Stunden** (ca. 12 Monate) nötig — sonst synthetische Werte |
| Abtastung    | Beliebig; beim Import → stündlich (Zero-Order-Hold auf 1‑Minuten-Raster, dann Stundenmittel = ∫P·dt / 1 h; Lücken halten den letzten Wert bis zum nächsten Sample) |


Beim Upload schreibt Earnie eine **normalisierte** Datei unter `earnie_env/config/uploads/` (im Container: `config/uploads/`). Der Dateiname leitet sich vom Original ab: `{Originalname}_resampled.csv` (z. B. `BEZUG-2025-22.7.2026_resampled.csv`). Ein erneuter Upload derselben Originaldatei überschreibt diese resampled-Datei; ein anderer Originalname erzeugt eine neue Datei (der Profil-Pfad zeigt dann auf die neue).

## Importmodus (Hausprofil)

Unter **Historische Jahres-Leistungsprofile [kW] (CSV)** wählen Sie:


| Modus                     | Inhalt                                                                                                                        |
| ------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| **Getrennte CSVs**        | Lastprofil (für Ist-vs-Modell) und optional PV-Erzeugungsprofil als eigene Dateien                                            |
| **Loxone Energiemonitor** | Eine Statistik-Datei; `Leistung Verbrauch [kW]` (Pflicht, direkt als Lastprofil), optional `Leistung Produktion [kW]` (PV), `Leistung Batterie` und `Leistung Energieversorger [kW]` (Netz). Keine Bilanz-Ableitung; SOC wird ignoriert. |
| **Bilanz**                | PV + Netz (Batterie optional = 0) → abgeleitetes Lastprofil: \(P_\mathrm{Ges} = P_\mathrm{PV} + P_\mathrm{Batt} + P_\mathrm{Grid}\)       |


**Bevorzugter Import:** Leistungsdaten [kW] (`timestamp;power_kw`). Kumulierte **Energiezähler [kWh]** werden ebenfalls akzeptiert und automatisch in mittlere Leistung [kW] umgerechnet (siehe unten).

**Bilanz-Vorzeichen:** Positiv bei Batterie und Netz bedeutet Leistung **in** das Haussystem (Entladen / Netzbezug); negativ = Laden / Einspeisung. Negatives \(P_\mathrm{Ges}\) wird auf 0 gekappt (Warnung). Optional können Vorzeichen je Serie umgekehrt werden.

Gespeicherte Pfade im Hausprofil: `total_profile_csv` (Lastprofil), `pv_profile_csv` (optional PV), `battery_profile_csv` / `grid_profile_csv` (Bilanz), `historical_csv_source` (`separate` / `energiemonitor` / `balance`).

### Historische Jahres-Leistungsprofile [kW] (CSV)

Überschrift **Historische Jahres-Leistungsprofile [kW]** mit Hinweis, dass der Import **optional** ist. Darunter ein **aufklappbarer Bereich** „Historische Jahres-Leistungsprofile [kW] (CSV)“ für Datenimport (getrennte CSVs, Energiemonitor oder Bilanz) und QC-Leistungsplot.

### Gesamt-Lastverhalten

Der Abschnitt **Gesamt-Lastverhalten** ist unabhängig von den CSV-Importen immer sichtbar:

- **Mit** Lastprofil-CSV (direkt, Energiemonitor oder Bilanz): **Monatsverbrauch** (Ist vs. gestapeltes Modell, Energie in kWh) und **stündlicher Verlauf** (Leistung)
- **Ohne** CSV: nur das modellierte Hausprofil (Monats- und Wochencharts)

## Loxone-CSV (Einzelserie)

Exportierte Loxone-Dateien (eine Leistungsserie) werden beim Import erkannt und in das kanonische Format umgerechnet (inkl. stündlicher Mittelung).

Akzeptierte Layouts:


| Layout                   | Beispiel-Kopfzeile                                | Wertspalte                                                                      |
| ------------------------ | ------------------------------------------------- | ------------------------------------------------------------------------------- |
| Getrennt Datum + Zeit    | `Datum;Zeit;Wert` oder `Datum;Zeit;Wert;Leistung` | Spalte `Leistung`, falls vorhanden; sonst die **letzte** Spalte nach Datum/Zeit |
| Kombinierter Zeitstempel | `Datum/Uhrzeit;Wert` bzw. `dd.mm.YYYY HH:MM:SS;…` | Spalte `Leistung`, falls vorhanden; sonst die letzte Spalte                     |


**Trennzeichen / Dezimal:** Üblich ist `;` mit Dezimal-`,` (z. B. `0,03`). Excel-DE-Exporte nutzen oft `,` als Spaltentrenner und ebenfalls `,` als Dezimal — dann stehen Nachkommastellen in Anführungszeichen (`"0,03"`). Earnie erkennt beide Varianten (sowie `,` + Dezimal-`.`).

Dreispaltige Digitalsignale (`Datum;Zeit;0/1`) sind zulässig; beim Verbraucher-Import kann optional mit der Nennleistung skaliert werden (siehe unten).

## Energiezähler-CSV (kWh)

Neben Leistungszeitreihen erkennt Earnie **kumulierte Zählerstände** automatisch und rechnet sie in stündliche mittlere Leistung (kW) um:

```text
Datum;Zeit;Counter [kWh]
01.01.2025;02:00:00;5652,226
01.01.2025;03:00:00;5652,435
```

| Regel | Bedeutung |
| ----- | --------- |
| Wert | Integrierte Energie ∫P·dt in **kWh** (Zählerstand), nicht Momentanleistung |
| Umrechnung | \(P(t_i)=(E_{i+1}-E_i)/\Delta t_i\) mit \(\Delta t_i\) in Stunden (beliebige Abtastung) |
| Erkennung | Kopfzeile mit `[kWh]`, Namen wie `Zähler`/`Counter`/`Ertrag`, sonst Heuristik (selten nahe 0, kaum fallend, große Medianwerte) |
| Leistung bleibt | Kopfzeile mit `[kW]` oder `Leistung` → bisheriger Leistungspfad |
| Zähler-Reset | Negatives Intervall wird **ignoriert** (`P=0`) und als Warnung im Log vermerkt |

Gilt für **Lastprofil [kW] (Gesamt)**, **PV-Erzeugungsprofil [kW]** und Verbraucher-CSVs im Modus Getrennte CSVs.

### Bilanz Netz-Leistung: Leistung oder zwei Energiezähler

Für den Upload **Netz-Leistung** (Modus Bilanz) gilt zusätzlich:

| Variante | Kopfzeile (Wertspalten) | Verhalten |
| -------- | ----------------------- | --------- |
| Leistung | Erste Wertspalte mit `[kW]` (eine bipolare Serie) | Wie bisher: positiv = Netzbezug, negativ = Einspeisung |
| Zwei Zähler | Erste Wertspalte Bezug `[kWh]`, zweite Einspeisung `[kWh]` | Beide als kumulierte Zähler → \(\Delta E/\Delta t\); Netzleistung \(P = P_\mathrm{Bezug} - P_\mathrm{Einspeisung}\) |
| Ungültig | Nur eine Wertspalte mit `[kWh]` | Import wird abgelehnt (Netz braucht Bezug und Einspeisung) |

```text
Datum;Zeit;Bezug [kWh];Einspeisung [kWh]
01.01.2025;00:00:00;1000,000;200,000
01.01.2025;01:00:00;1002,000;200,500
```

→ \(P_\mathrm{Bezug}=2\,\mathrm{kW}\), \(P_\mathrm{Einspeisung}=0{,}5\,\mathrm{kW}\) → Netz \(+1{,}5\,\mathrm{kW}\).

Diese Zwei-Spalten-Regel gilt **nur** für Bilanz **Netz-Leistung**. Batterie, PV und Last behalten den Ein-Zähler-Import oben.

## Gesamt-CSV (`total_profile_csv`)

Optional: Abgleich Ist vs. Modell und Grundlage für die Rest-Grundlast, wenn Verbraucher-CSVs abgezogen werden.

Die Kennzahlen **Ist-Jahresverbrauch** und **Modell-Jahresverbrauch** beziehen sich auf die **letzten 8760 Stunden** der CSV (ca. 12 Monate), auch wenn die Datei länger ist. Monats- und Wochencharts nutzen weiterhin die gesamte Zeitreihe.

Im Abgleich **Ist vs. Modell** (Hauskonfigurator, Abschnitt **Gesamt-Lastverhalten**)
kann die Modell-Basislast gewählt werden (`baseload_distribution` am Hausprofil):

| Modus | Verhalten |
| ----- | --------- |
| **Jahres-Rest gleichmäßig** (`equal`, Standard) | Eine konstante Grundlast aus dem Jahres-Rest Ist − Verbraucher (letzte 8760 h), Untergrenze mindestens **1 %** des konfigurierten Jahresverbrauchs (Chart). SE-Pfad A: flache `baseload_kwh/8760`. |
| **Monats-Rest je Monat** (`monthly`) | Pro Kalendermonat `max(0, Ist − Verbraucher)`; Stunden in dem Monat erhalten den Rest gleichmäßig. Keine 1 %-Untergrenze im Chart. Monate mit Verbrauchern > Ist bleiben ohne Basislast. **Gilt für Charts und SE-Pfad A**, wenn eine Gesamt-CSV vorhanden ist. |

**SE-Pfad B** (Gesamt-CSV und alle Gesteuert/Manual mit aktivem CSV) bleibt der stündliche Meter-Rest — `baseload_distribution` ändert Pfad B nicht.

Die Chart-Modell-Basislast ist damit **nicht** der stündliche Meter-Rest (Pfad B), sondern der gewählte Jahres- oder Monats-Rest plus gestapelte Verbraucher.
## PV-Erzeugungsprofil (`pv_profile_csv`)

Optionaler Jahres-PV-Leistungsverlauf als Summe über alle PV-Anlagen. Im Szenarienkonfigurator kann pro Szenario gewählt werden, ob der Szenario-Explorer dieses Profil statt PV aus Wetterdaten (Open-Meteo) für die Berechnung nutzt. Dafür muss die PV-CSV mindestens ca. **12 Monate** abdecken — kürzere Importe bleiben sichtbar im Hauskonfigurator, werden im SE aber **nicht** verwendet (Fallback Open-Meteo). In den Lastverhaltens-Charts erscheint importiertes PV zusätzlich als **punktierte** Linie.

## Verbraucher-CSV (`profile_csv` + `use_profile_csv`)

Pro Verbraucher:

1. CSV-Pfad oder Upload
2. Checkbox **„Von Basis-Last abziehen“**

- **Aktiv:** Last aus der CSV statt Synthese; Abzug von der Basislast (HK und — bei Pfad B — SE)
- **Inaktiv:** synthetisches Modell/Schedule (Pfad kann gespeichert bleiben, wird aber nicht für die Modellierung genutzt)

| earnie_role | Hauskonfigurator | Szenario-Explorer | Live |
| ----------- | ---------------- | ----------------- | ---- |
| Bekannt | Abzug von Basislast | feste zusätzliche Last aus CSV (nicht Schedule) | wie SE |
| Gesteuert | Abzug von Basislast | CSV-Energie über Horizont als MILP-Ziel; Timing optimieren | CSV ignorieren, Schedule |
| Manuelles Gerät | Abzug von Basislast | wie Gesteuert | Nutzer-Tagesplan wenn aktiv; sonst weder CSV noch Default-Schedule |

**SE-Basislast:** Pfad **B** (stündlicher Meter-Rest), wenn Gesamt-CSV vorhanden und alle Gesteuert/Manual ein aktives CSV haben; sonst Pfad **A**. Unter A: bei `baseload_distribution=monthly` monatsweise Ist − Modellverbraucher, sonst flache `baseload_kwh/8760`.

Synthetische `cons_data_hourly.csv` nutzt die konfigurierte Grundlast (`baseload_kwh / 8760`), außer SE läuft mit Pfad B (oder Pfad A Monats-Rest aus dem Hausprofil).

### Digitale Ein/Aus-Signale (0/1)

Wenn die CSV nach Erkennung überwiegend nur die Werte **0** und **1** enthält (z. B. Schaltzustand eines Geräts), fragt der Hauskonfigurator beim Import einmalig, ob die Werte mit der **Nennleistung (kW)** des Verbrauchers multipliziert werden sollen.

- **Ja:** Die Datei wird als kanonisches Leistungsprofil (0 bzw. Nennleistung) neu geschrieben.
- **Nein:** Die Werte bleiben unverändert (0/1).

Die Haus-Gesamt-CSV (`total_profile_csv`) wird nicht so skaliert — dort gibt es keine einzelne Nennleistung.

## Test-Export aus Live-`cons_data`

Für lokale Import-Tests kann aus der Live-System-Datei `cons_data_hourly.csv` eine **PV-Erzeugungsprofil**-CSV und eine **Energiemonitor**-CSV (nur relevante Spalten) erzeugt werden:

```text
python -m scripts.export_historical_test_csvs --out-dir Historical-Data/export-test
```

Optional: `--cons-data`, `--from`, `--to`. Die Dateien sind Loxone-kompatibel und lassen sich im Hauskonfigurator (getrennte CSVs bzw. Energiemonitor) wieder einlesen. Es sind mindestens 8760 Stunden nötig.

## Von Loxone Energieflussmonitor zum Hausprofil

Kurzweg für die Einrichtung (Details und Rollen-Tabelle: Spec [efm-auto-sync-2.4.l](../spec/efm-auto-sync-2.4.l.md), manueller Blueprint im Repo-Plan `energieflussmonitor_hausprofil_blueprint_a`):

1. In Loxone **Energieflussmonitor** + **Zähler** für Netz / PV / Speicher / Verbraucher anlegen (flach oder bewusst flachhalten).
2. Auf **EHAL-Com** unter **Zähler importieren** die Zähler aus `LoxAPP3.json` laden und gewünschte **generische Verbraucher** übernehmen (optional Live-`flex.{slug}.sens_power_act` = Zähler-Bezeichnung). Freigabe- und Sollwert-Merker (`flex.{slug}.set_enable` / `flex.{slug}.set_power_setpoint`) weiterhin manuell im EHAL-Mapping.
3. **Statistik-CSVs einzeln** je Serie exportieren und im Hauskonfigurator hochladen (Haus: Energiemonitor/Bilanz/getrennt; Verbraucher: Einzelserie → `profile_csv`, ggf. „Von Basis-Last abziehen“). Es gibt **keinen** Multi-Spalten-Import aller EFM-Leistungsflüsse in einem Schritt.

## Abgrenzung Live-Loxone und CSV-Ebenen


| Ebene            | Ort                                                                    | Zweck                            |
| ---------------- | ---------------------------------------------------------------------- | -------------------------------- |
| Runtime          | `scenario_explorer_conf.path_cons_data` → `cons_data_hourly.csv`       | Live + Szenario-Explorer         |
| Hausmodell       | `house_profiles`: `total_profile_csv`, `pv_profile_csv`, `profile_csv` | Planung, Ist-vs-Modell, Synthese |
| Offline-Flex-Log | `path_historical_log` am Verbraucher (Legacy-Overlay / Profil)         | Einzelserie → cons_data          |


Das Feld `path_historical_log` (flexible Verbraucher / Hausprofil) gehört zum Offline-Weg Loxone-Log → `cons_data_hourly.csv` und ist unabhängig von den Hausprofil-Jahres-CSVs. Die früheren Keys `path_consumption` / `path_production` in `config.json` sind entfernt (data-model v3).
