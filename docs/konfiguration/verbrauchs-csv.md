# Historische Verbrauchs-CSV (Hausprofil)

Im **Hauskonfigurator** können Sie Jahresverbrauchs-Zeitreihen als CSV hinterlegen — für das gesamte Haus und optional je Verbraucher.

## Kanonisches Format

```text
timestamp;power_kw
2023-01-01 00:00:00;3.177
```

| Regel | Bedeutung |
| ----- | --------- |
| Trennzeichen | Semikolon (`;`) |
| Zeitstempel | ISO-ähnlich `YYYY-MM-DD HH:MM:SS` |
| Leistung | Verbrauch in **kW**, positiv |
| Länge | Nach Import mindestens **8760 Stunden** (ca. 12 Monate) |
| Abtastung | Beliebig; beim Import → stündlich (Mittelwert bei dichteren Daten, Interpolation bei lückenhaften) |

Beim Upload schreibt Earnie eine normalisierte Datei unter `config/uploads/`.

## Loxone-CSV

Exportierte Loxone-Dateien werden beim Import erkannt und in das kanonische Format umgerechnet (inkl. stündlicher Mittelung).

Akzeptierte Layouts:

| Layout | Beispiel-Kopfzeile | Wertspalte |
| ------ | ------------------ | ---------- |
| Getrennt Datum + Zeit | `Datum;Zeit;Wert` oder `Datum;Zeit;Wert;Leistung` | Spalte **`Leistung`**, falls vorhanden; sonst die **letzte** Spalte nach Datum/Zeit |
| Kombinierter Zeitstempel | `Datum/Uhrzeit;Wert` bzw. `dd.mm.YYYY HH:MM:SS;…` | Spalte **`Leistung`**, falls vorhanden; sonst die letzte Spalte |

Dreispaltige Digitalsignale (`Datum;Zeit;0/1`) sind zulässig; beim Verbraucher-Import kann optional mit der Nennleistung skaliert werden (siehe unten).

## Gesamt-CSV (`total_profile_csv`)

Optional unter **Jahres-Verbrauchs-CSV**: Abgleich Ist vs. Modell und Grundlage für die Rest-Grundlast, wenn Verbraucher-CSVs abgezogen werden.

Die Kennzahlen **Ist-Jahresverbrauch** und **Modell-Jahresverbrauch** beziehen sich auf die **letzten 8760 Stunden** der CSV (ca. 12 Monate), auch wenn die Datei länger ist. Monats- und Wochencharts nutzen weiterhin die gesamte Zeitreihe.

Im Abgleich **Ist vs. Modell** ist die gestapelte Modell-Basislast die konfigurierte Grundlast (`baseload_kwh`, gleichmäßig), nicht der Meter-Rest nach Abzug der Verbraucher-CSVs.

Zusätzlich wird die Grundlast so **an den Ist-Jahresverbrauch angepasst**, dass Modell ≈ Ist: Idealwert = Ist − Verbraucher-Summe (letzte 8760 h). Die Untergrenze dabei ist mindestens **1 %** des konfigurierten Jahresverbrauchs (nicht die Standard-2 %-Floor).

## Verbraucher-CSV (`profile_csv` + `use_profile_csv`)

Pro Verbraucher:

1. CSV-Pfad oder Upload
2. Checkbox **„Aus Gesamt-CSV abziehen / echtes Profil nutzen“**

- **Aktiv:** Last aus der CSV statt Synthese; Abzug von der Gesamt-CSV für die Rest-Grundlast
- **Inaktiv:** synthetisches Modell/Schedule (Pfad kann gespeichert bleiben, wird aber nicht für die Modellierung genutzt)

### Digitale Ein/Aus-Signale (0/1)

Wenn die CSV nach Erkennung überwiegend nur die Werte **0** und **1** enthält (z. B. Schaltzustand eines Geräts), fragt der Hauskonfigurator beim Import einmalig, ob die Werte mit der **Nennleistung (kW)** des Verbrauchers multipliziert werden sollen.

- **Ja:** Die Datei wird als kanonisches Leistungsprofil (0 bzw. Nennleistung) neu geschrieben.
- **Nein:** Die Werte bleiben unverändert (0/1).

Die Haus-Gesamt-CSV (`total_profile_csv`) wird nicht so skaliert — dort gibt es keine einzelne Nennleistung.

Im Bereich **Verbrauchsprofil (Modell)** können Sie zwischen allen Verbrauchern und nur CSV-instrumentierten Verbrauchern umschalten.

## Abgrenzung Live-Loxone

Das Feld `path_historical_log` in `config.json` (flexible Verbraucher) gehört zum Offline-Weg Loxone-Log → `cons_data_hourly.csv` und ist unabhängig von den Hausprofil-CSVs.
