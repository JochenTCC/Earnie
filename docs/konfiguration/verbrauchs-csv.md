# Historische Verbrauchs-CSV (Hausprofil)

Im **Hauskonfigurator** können Sie Jahresverbrauchs-Zeitreihen als CSV hinterlegen — für das gesamte Haus und optional je Verbraucher. Zusätzlich kann ein **PV-Ertragsprofil** (Summe aller Anlagen) importiert werden.

## Kanonisches Format

```text
timestamp;power_kw
2023-01-01 00:00:00;3.177
```

| Regel | Bedeutung |
| ----- | --------- |
| Trennzeichen | Semikolon (`;`) |
| Zeitstempel | ISO-ähnlich `YYYY-MM-DD HH:MM:SS` |
| Leistung | Verbrauch bzw. PV-Ertrag in **kW**, positiv |
| Länge | Nach Import mindestens **8760 Stunden** (ca. 12 Monate) |
| Abtastung | Beliebig; beim Import → stündlich (Mittelwert bei dichteren Daten, Interpolation bei lückenhaften) |

Beim Upload schreibt Earnie eine normalisierte Datei unter `earnie_env/config/uploads/` (im Container: `config/uploads/`). Pro Rolle (Gesamtverbrauch, PV, je Verbraucher) gibt es **genau eine** Datei — ein erneuter Upload überschreibt denselben Pfad.

## Importmodus (Hausprofil)

Unter **Historische Jahresprofile (CSV)** wählen Sie:

| Modus | Inhalt |
| ----- | ------ |
| **Getrennte CSVs** | Verbrauch (für Ist-vs-Modell) und optional PV-Ertrag als eigene Dateien |
| **Loxone Energiemonitor** | Eine Statistik-Datei; Spalten `Leistung Verbrauch [kW]` (Pflicht) und `Leistung Produktion [kW]` (optional) werden übernommen |

Ignoriert beim Energiemonitor-Import: `Leistung Energieversorger`, `Leistung Batterie`, `Ladestand Batterie` (SOC wird nicht importiert) sowie Zähler-Spalten.

Gespeicherte Pfade im Hausprofil: `total_profile_csv` (Verbrauch), `pv_profile_csv` (optional PV), `historical_csv_source` (`separate` / `energiemonitor`).

## Loxone-CSV (Einzelserie)

Exportierte Loxone-Dateien (eine Leistungsserie) werden beim Import erkannt und in das kanonische Format umgerechnet (inkl. stündlicher Mittelung).

Akzeptierte Layouts:

| Layout | Beispiel-Kopfzeile | Wertspalte |
| ------ | ------------------ | ---------- |
| Getrennt Datum + Zeit | `Datum;Zeit;Wert` oder `Datum;Zeit;Wert;Leistung` | Spalte **`Leistung`**, falls vorhanden; sonst die **letzte** Spalte nach Datum/Zeit |
| Kombinierter Zeitstempel | `Datum/Uhrzeit;Wert` bzw. `dd.mm.YYYY HH:MM:SS;…` | Spalte **`Leistung`**, falls vorhanden; sonst die letzte Spalte |

Dreispaltige Digitalsignale (`Datum;Zeit;0/1`) sind zulässig; beim Verbraucher-Import kann optional mit der Nennleistung skaliert werden (siehe unten).

## Gesamt-CSV (`total_profile_csv`)

Optional: Abgleich Ist vs. Modell und Grundlage für die Rest-Grundlast, wenn Verbraucher-CSVs abgezogen werden.

Die Kennzahlen **Ist-Jahresverbrauch** und **Modell-Jahresverbrauch** beziehen sich auf die **letzten 8760 Stunden** der CSV (ca. 12 Monate), auch wenn die Datei länger ist. Monats- und Wochencharts nutzen weiterhin die gesamte Zeitreihe.

Im Abgleich **Ist vs. Modell** ist die gestapelte Modell-Basislast die konfigurierte Grundlast (`baseload_kwh`, gleichmäßig), nicht der Meter-Rest nach Abzug der Verbraucher-CSVs.

Zusätzlich wird die Grundlast so **an den Ist-Jahresverbrauch angepasst**, dass Modell ≈ Ist: Idealwert = Ist − Verbraucher-Summe (letzte 8760 h). Die Untergrenze dabei ist mindestens **1 %** des konfigurierten Jahresverbrauchs (nicht die Standard-2 %-Floor).

## PV-Ertrag (`pv_profile_csv`)

Optionaler Jahres-PV-Ertrag als Summe über alle PV-Anlagen. Im Szenarieneditor kann pro Szenario gewählt werden, ob der Szenario-Explorer dieses Profil statt PV aus Wetterdaten (Open-Meteo) für die Berechnung nutzt. In den Verbrauchs-Charts erscheint importiertes PV zusätzlich als **punktierte** Linie.

## Verbraucher-CSV (`profile_csv` + `use_profile_csv`)

Pro Verbraucher:

1. CSV-Pfad oder Upload
2. Checkbox **„Aus Gesamt-CSV abziehen / echtes Profil nutzen“**

- **Aktiv:** Last aus der CSV statt Synthese; Abzug von der Gesamt-CSV für die Rest-Grundlast im Hauskonfigurator
- **Inaktiv:** synthetisches Modell/Schedule (Pfad kann gespeichert bleiben, wird aber nicht für die Modellierung genutzt)

Szenario-Explorer und synthetische `cons_data_hourly.csv` nutzen dieselbe **konfigurierte** Grundlast wie Verbrauchsprofil (Modell): `baseload_kwh / 8760` (nicht den Meter-Rest aus der Gesamt-CSV).

Im Szenario-Explorer (Tabelle **Gesamtkosten und -Verbrauch**) kommt die Spalte **Jahres Verbrauch** der Zeile **Historisch** aus dem Ist-Zähler (`cons_data`); die übrigen Zeilen aus dem Hausprofil-Modell. Siehe [Benutzer-Handbuch](../user-manual/Benutzer-Handbuch-Earnie.md#gesamtkosten-jahres-verbrauch-kwh).

### Digitale Ein/Aus-Signale (0/1)

Wenn die CSV nach Erkennung überwiegend nur die Werte **0** und **1** enthält (z. B. Schaltzustand eines Geräts), fragt der Hauskonfigurator beim Import einmalig, ob die Werte mit der **Nennleistung (kW)** des Verbrauchers multipliziert werden sollen.

- **Ja:** Die Datei wird als kanonisches Leistungsprofil (0 bzw. Nennleistung) neu geschrieben.
- **Nein:** Die Werte bleiben unverändert (0/1).

Die Haus-Gesamt-CSV (`total_profile_csv`) wird nicht so skaliert — dort gibt es keine einzelne Nennleistung.

Im Bereich **Verbrauchsprofil (Modell)** können Sie zwischen allen Verbrauchern und nur CSV-instrumentierten Verbrauchern umschalten.

## Test-Export aus Live-`cons_data`

Für lokale Import-Tests kann aus der Live-System-Datei `cons_data_hourly.csv` eine **PV-Ertrag**-CSV und eine **Energiemonitor**-CSV (nur relevante Spalten) erzeugt werden:

```text
python -m scripts.export_historical_test_csvs --out-dir Historical-Data/export-test
```

Optional: `--cons-data`, `--from`, `--to`. Die Dateien sind Loxone-kompatibel und lassen sich im Hauskonfigurator (getrennte CSVs bzw. Energiemonitor) wieder einlesen. Es sind mindestens 8760 Stunden nötig.

## Abgrenzung Live-Loxone und CSV-Ebenen

| Ebene | Ort | Zweck |
| ----- | --- | ----- |
| Runtime | `scenario_explorer_conf.path_cons_data` → `cons_data_hourly.csv` | Live + Szenario-Explorer |
| Hausmodell | `house_profiles`: `total_profile_csv`, `pv_profile_csv`, `profile_csv` | Planung, Ist-vs-Modell, Synthese |
| Offline-Flex-Log | `path_historical_log` am Verbraucher (Legacy-Overlay / Profil) | Einzelserie → cons_data |

Das Feld `path_historical_log` (flexible Verbraucher / Hausprofil) gehört zum Offline-Weg Loxone-Log → `cons_data_hourly.csv` und ist unabhängig von den Hausprofil-Jahres-CSVs. Die früheren Keys `path_consumption` / `path_production` in `config.json` sind entfernt (data-model v3).
