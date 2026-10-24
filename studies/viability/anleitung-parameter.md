# Anleitung: Parameter des Häuser-Generators

Stand 24.10.2026. Alle Werte stehen in **einer Datei**: [`haeuser.json`](haeuser.json). Der Lader `params.py` prüft sie
beim Start; `archetypes.py`, `make_houses.py` und `calibrate_wp.py` lesen sie. Abo-Stufen und Preise gehören nicht
hierher (Betriebsdaten, nicht Teil dieses Repos).

Befehle laufen im Repo-Root in PowerShell; vorher einmal `$env:PYTHONUTF8='1'` setzen.

## 1. Der Ablauf

```powershell
# 1. Hauspakete erzeugen (überschreibt das Paket des Hauses vollständig, auch results/)
.venv\Scripts\python.exe -m studies.viability.make_houses --ids A09-m,A18-m --out studies/viability/packs --pv-pr 0.8

# 2. Rechnen (erstes Mal mit Netz, damit Verbrauchsdaten und Wetter erzeugt werden)
.venv\Scripts\python.exe -m studies.poc_cloud.run_poc --study-dir studies/viability/packs/A09-m `
  --cache-dir studies/viability/cache/open_meteo --allow-network --harvest `
  --start-month 1 --end-month 12 --out studies/viability/packs/A09-m/results/year
```

Die Kosten B0/B1/E0/E1 stehen danach in `packs/<ID>/results/<Lauf>/summary.json` (`ref:duo`, `duo`, `ref:dynamisch`,
`dynamisch`). Die Bewertung gegen Abo-Stufen übernimmt ein separates, nicht öffentliches Auswerteskript.

- `--ids` nimmt Haus-IDs aus der Datei (z. B. `A09-m`), `--all` erzeugt alle 52.
- `--pv-pr` setzt die PV Performance Ratio (Standard 1,0 = Earnie-Standard ohne Verluste).
- `--start-month`/`--end-month` wählen den Zeitraum (1 bis 12); für einen Test genügt ein Monat.
- Ohne `--allow-network` blockiert der Runner das Netz. Das ist gewollt: Ein fehlender Cache bricht dann sofort ab.

## 2. Eigene Variante, ohne die Standarddatei zu ändern

```powershell
Copy-Item studies/viability/haeuser.json studies/viability/meine-variante.json
# meine-variante.json bearbeiten, dann bei allen Skripten mit angeben:
.venv\Scripts\python.exe -m studies.viability.archetypes --params studies/viability/meine-variante.json
.venv\Scripts\python.exe -m studies.viability.make_houses --params studies/viability/meine-variante.json --ids A09-m --out studies/viability/packs_var
```

- `--params` gilt für `archetypes`, `make_houses` und `calibrate_wp`. Auch die Umgebungsvariable `EARNIE_STUDY_PARAMS`
  wählt die Datei; die Kommandozeile hat Vorrang.
- **Dieselbe Datei in allen Schritten verwenden.** `run_poc` liest sie nicht, es rechnet das fertige Paket.
- Eigene Pakete in ein eigenes `--out`-Verzeichnis legen, damit sie die Standardpakete nicht überschreiben.

## 3. Aufbau der Datei

Schlüssel mit Unterstrich (`_hinweis`, `_stufen` …) sind Kommentare und werden ignoriert.

| Abschnitt | Schlüssel | Bedeutung |
|---|---|---|
| `annahmen` | `ev_kwh_pro_100km`, `ev_akku_kwh`, `wallbox_kw` | E-Auto-Annahmen |
| | `heizstab_kw`, `heizstab_kwh_jahr` | Heizstab |
| | `pv_neigung_grad`, `pv_azimut_sued_grad` | PV-Ausrichtung (Süd = 0) |
| | `standort` | `[Breite, Länge]` |
| | `haushalte`, `standard_haushalt` | Haushaltsstrom ohne WP, E-Auto, Heizstab in kWh/a, z. B. `{"k": 2500, "m": 3500, "g": 4500}` |
| `umsetzung` | `netzbereich` | Netzbereich aus `share/config/grid_fees.json` (z. B. `AT-VBG`) |
| | `akku_leistung_kw_pro_kwh`, `akku_verschleiss_eur_pro_kwh` | Akku-Annahmen |
| | `heizstab_startstunde`, `heizstab_spielraum_h`, `ev_ziel_soc_prozent` | Betriebsannahmen |
| `waermepumpe` | `stufen` | Ziel-kWh/a → Gebäudeklasse (3 Bestand, 4 Altbau) |
| | `basis`, `flaeche_bereich_m2` | Wärmepumpentyp, Personen, Solltemperatur; Suchbereich für die Wohnfläche |
| `szenarien` | `duo`, `dynamisch` | je `import_tariff_id` und `export_tariff_id` aus `share/config/tariffs.json` |
| `haeuser` | Liste | die Vorlagen, siehe unten |

### Ein Haus ist eine Zeile unter `haeuser`

```json
{"id": "A09", "name": "PV 8 kWp + 10 kWh", "pv_kwp": 8, "pv_layout": "south", "battery_kwh": 10, "evs": [], "heat_pump_kwh": 0, "heating_rod": false}
{"id": "A23", "name": "Grosshaus", "pv_kwp": 20, "battery_kwh": 20, "evs": [12000, 12000], "heat_pump_kwh": 7000}
```

- `id` ohne Bindestrich (der trennt das Haushalts-Suffix); `id` und `name` sind Pflicht, alles andere hat den Standard
  „nicht vorhanden“.
- `evs: [12000, 18000]` heißt zwei E-Autos mit 12.000 bzw. 18.000 km/a.
- `pv_layout: "east_west"` teilt die PV in zwei gleich große Hälften.
- Häuser ohne E-Auto laufen in allen Haushaltsgrößen (`A09-k`, `-m`, `-g`), Häuser mit E-Auto nur mit dem
  Standard-Haushalt.
- Tabelle der Häuser ansehen: `.venv\Scripts\python.exe -m studies.viability.archetypes`

## 4. Die Prüfung beim Laden

`params.py` bricht mit einer Meldung ab, die den Pfad nennt, bei: unbekannten Schlüsseln (Tippfehler), falschen Typen
oder Wertebereichen, doppelten Haus-IDs, einem Standard-Haushalt, der nicht in `haushalte` steht, und einer
Wärmepumpen-Größe, die in `waermepumpe.stufen` fehlt.

## 5. Was bei Änderungen nachzuziehen ist

| Änderung | Danach nötig |
|---|---|
| Haus, Haushalt, Akku, PV, E-Auto, Heizstab, Tarif-IDs | `make_houses` neu, dann rechnen |
| Neue Wärmepumpen-Größe (z. B. 5.000 kWh/a) | in `waermepumpe.stufen` eintragen, `calibrate_wp` ausführen (schreibt `wp_calibration.json`), dann `make_houses` |
| Anderer Standort | `calibrate_wp` neu, dann mit `--allow-network --harvest` rechnen, damit die Wetterdateien entstehen |
| Andere PV-Neigung/Ausrichtung | mit `--allow-network --harvest` rechnen (neue Wetterdateien) |
| Anderes Preisjahr | **nicht** über die Datei möglich: Das Jahr 2025 steckt in `fetch_prices.py`, `run_poc.py` (Zeitraum der Verbrauchsdaten), der Preis-CSV und dem Wetter-Cache. Ein Jahreswechsel ist ein Umbau |
| Anderer Tarif | Tarif-ID unter `szenarien`; hat der Tarif eine Monatstabelle, muss sie 2025 samt 31.12.2024 abdecken (beim Duo-Tarif ergänzt der Generator Dezember 2024) |

Das Szenario-Schema ist fest: genau `duo` und `dynamisch`.

## 6. Stolperstellen aus dem Pilot

- **Wetterdateien aus anderen Läufen:** `--harvest` kopiert nur Dateien, die während dieses Laufs entstanden sind.
  Entstanden sie vorher (z. B. durch `calibrate_wp`), liegen sie nur in `data/cache/open_meteo` und müssen von Hand nach
  `studies/viability/cache/open_meteo` kopiert werden (Dateien mit dem Präfix `<Breite>_<Länge>_`).
- **Jahresränder:** Ein Jahreslauf braucht auch die Wetterdateien für 2024 und 2026; erst ein Jahreslauf mit Netz
  erzeugt sie vollständig.
- **`make_houses` löscht das Paket des Hauses** inklusive vorhandener Ergebnisse (`results/`). Ergebnisse vorher
  sichern, wenn sie erhalten bleiben sollen.
- **Hausprofile ohne steuerbare Verbraucher** erzeugen im Log eine Warnung zur Verbrauchsbilanz (+56 %); sie betrifft
  nur die historische Referenz.
