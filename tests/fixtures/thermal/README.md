# Thermische CSV-Fixtures

Minimale Loxone-CSV-Zeitreihen für thermische RC-Tests (`thermal_rc`).

## SwimSpa (Prod-Referenz)

| Datei | Rolle |
|-------|--------|
| `SwimSpa_currenttemperature_fixture.csv` | Ist-Temperatur (Abkühlphase) |
| `Aussentemperatur_Einfahrt_fixture.csv` | Außen-/Einfahrt-Temperatur |
| `SwimSpa_Verbrauchszaehler_fixture.csv` | Leistung (Spalte `Leistung`) |

## Freezer (zweites Referenzmodell, kein NAS-Prod-Row)

| Datei | Rolle |
|-------|--------|
| `Freezer_currenttemperature_fixture.csv` | Ist-Temperatur (Hysterese-Regler) |
| `Freezer_ambient_fixture.csv` | Raumtemperatur (~22 °C) |
| `Freezer_Verbrauchszaehler_fixture.csv` | Kompressor-Leistung |

Parameter und Test-Hilfen: `tests/fixtures/thermal_rc_reference.py`.

## Regenerieren

```powershell
python -m scripts.generate_thermal_fixtures
```

Die Daten sind synthetisch und dienen der CI-Stabilität ohne produktive Loxone-Logs.
