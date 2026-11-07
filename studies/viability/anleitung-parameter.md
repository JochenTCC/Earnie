# Anleitung: Häuser-Generator der Wirtschaftlichkeitsstudie

Stand 05.11.2026. Der Generator leitet Häuser aus wenigen freien Achsen ab und schreibt je Haus ein Earnie-Paket auf
Datenmodell 5. Alle Werte stehen in [`haeuser.json`](haeuser.json), `params.py` prüft die Datei beim Start. Abo-Stufen und
Abo-Preise gehören nicht hierher (Betriebsdaten, nicht Teil dieses Repos).

Befehle laufen im Repo-Root in PowerShell; vorher einmal `$env:PYTHONUTF8='1'` setzen.

## 1. Der Ablauf

```powershell
# 1. Hauspakete erzeugen (überschreibt das Paket des Hauses vollständig, auch results/)
.venv\Scripts\python.exe -m studies.viability.make_houses --stichproben --out studies/viability/packs_s0

# 2. Leiter L0 bis L3 rechnen, ein Haus nach dem anderen
.venv\Scripts\python.exe -m studies.viability.run_houses --ids S1,S3 --packs studies/viability/packs_s0 --houses-parallel 8 --workers 6

# 3. Ergebnisse prüfen
.venv\Scripts\python.exe -m studies.viability.check_houses --packs studies/viability/packs_s0 --run year
```

- Stufe 1 baut eine Hausliste statt der Stichproben: `make_houses --liste LISTE.json --out studies/viability/packs_stufe1`. Die Datei hat die Form `{"haeuser": [...]}`, je Haus alle Achsen und `id`; Schlüssel mit Unterstrich sind Kommentare. Enthält ein Paket schon Ergebnisse, bricht `--liste` ab, statt sie zu löschen; mit `--ueberspringen` lässt es diese Häuser aus (Liste nachträglich erweitert). Für Sensitivitäten darf ein Listenhaus zusätzlich `dach_kwp` (Dachgrenze in kWp statt der Dachregel) und `speicher_kwh` (Speicher in kWh statt kWp mal Speicherachse) tragen; das Raster `all_houses` setzt beides nie.
- `run_houses --alle --ueberspringen` rechnet alle gebauten Pakete und lässt Häuser mit fertigem Lauf aus, so setzt ein abgebrochener Lauf fort. Die Schalter `EARNIE_SE_LOOKAHEAD_H`, `EARNIE_BASE_LEVEL` und `EARNIE_PLAN_VENDOR_MODE` kommen aus der Umgebung und stehen in der ersten Zeile von `run.log`.
- `make_houses` schreibt `house.json` neben das Paket: abgeleitete Werte, was Earnie daraus ableitet, Earnie-Points. Es
  setzt `annual_kwh` im Hausprofil so, dass genau der Haushaltsstrom der Regel als Grundlast bleibt.
- `run_houses` legt je Haus `results/<Lauf>/` an, mit SE-Log, `run.log` und den CSVs der Referenzleiter. `--start-month`/`--end-month`
  wählen den Zeitraum, `--sensitivity` rechnet die 8 Regel-Sätze zusätzlich.
- `--forecast-price-strategy mirror` rechnet einen zweiten Lauf im Forecast-Modus (Untergrenze von L2 − L3, Spalten `*_forecast`, doppelte Laufzeit). Beim ersten Mal braucht er `--allow-network` für die archivierten PV-Prognosen. Für Januar muss die Preisdatei etwa 8 Tage vor dem Jahresanfang beginnen: `python -m studies.poc_cloud.fetch_prices --start 2024-12-20 --end 2026-01-04`.
- `run_houses` rechnet die Referenz ohne PV und Batterie (`historical_reference`) nicht mit, die Studie nutzt sie nicht. L0 bleibt. Ein Szenario ohne `own_reference` bricht deshalb ab.
- Mehr Häuser gleichzeitig nutzen die Kerne besser als mehr Worker je Haus: Die Referenzen sind schnell fertig, danach rechnet
  ein Haus nur noch einen MILP-Prozess je Szenario.
- Ohne `--allow-network` ist das Netz blockiert und ein fehlender Wetter-Cache bricht ab. Mit dem Schalter landen neue
  Wetterdateien auch in `cache/open_meteo`.

## 2. Aufbau der Datei

Schlüssel mit Unterstrich sind Kommentare. Unbekannte und fehlende Schlüssel brechen ab.

| Abschnitt | Inhalt |
|---|---|
| `preisjahr` | Jahr für Preise, Verbrauchsdaten und Brennstoffpreise |
| `annahmen` | Feste Werte: Standort, PR, Akku, E-Auto, Wallbox, Solltemperatur, Heizstab |
| `netz` | Ob SNAP im ganzen Preisjahr gilt. `make_houses` schreibt das nur in die `grid_fees.json` des Pakets, der Katalog in `share/config` bleibt unverändert. Netzverlust und Abgaben kommen aus dem Katalog |
| `geraete` | Waschmaschine, Geschirrspüler, Trockner. Mit `aktiv: true` bekommt jedes Haus je Gerät ein zufälliges Stundenprofil (fester Seed) unter `config/appliances/`, die Energie kommt aus dem Haushaltsstrom. `rolle` sagt, was Earnie damit darf: `known` = feste Last in L0 bis L3 (Stufe 1); `flex` = Energie und Lauftage aus dem Profil, L2 nimmt den günstigsten Preisblock und L3 plant den Start im Fenster `fenster_start` desselben Tages (ab Stufe 2). Bei `flex` muss das Fenster eine gerade Breite in Stunden haben, weil Earnie es als Startstunde ± Verschiebung führt. `make_houses --geraete-rolle known` baut einzelne Pakete mit der anderen Rolle, ohne die Datei zu ändern |
| `regeln` | Werte der Ableitungsregeln: Wohnfläche, Haushaltsstrom, Hüllen, Heizlast, Kollektor, Dach, Mindest-kWp. Speicher: Heizleistung mal `speicher_l_je_kw` zwischen `speicher_min_l` und `speicher_max_l`, mit Kollektor mindestens `speicher_l_je_m2_kollektor`. `speicher_band_c` setzt das Temperaturband je Heizquelle, `speicher_verlust_w` den Verlust aus dem Volumen |
| `brennstoffpreise` | Je Jahr `gas` (ct/kWh) und `pellets` (€/t) |
| `heizsysteme` | H1, H2 und H5 bis H7: Quelle, Kollektor, Heizstab, Speicher, erlaubte Hüllen. Wärmepumpe mit Heizstab (früher H3) ist keine erlaubte Konfiguration und bricht ab |
| `achsen` | Freie Achsen und ihre Stufen. Eine neue Stufe verschiebt die `G`-Nummern von `all_houses`; Hauslisten (`--liste`) tragen Achsen und ID selbst und bleiben gültig |
| `eauto_muster` | Ladefenster je Muster, Muster je Stufe der Achse `eauto` |
| `szenarien`, `standard_szenarien` | Tarife je Szenario; welche ein Haus ohne eigene Angabe rechnet |
| `stichproben` | Die Häuser der Stufe 0, je Haus alle Achsen und optional `szenarien` |

`derive.py` enthält die Regeln. Dort liefert `all_houses` alle gültigen Kombinationen und `stratified_sample` eine
geschichtete Stichprobe mit festem Seed.

## 3. Was bei Änderungen nachzuziehen ist

| Änderung | Danach nötig |
|---|---|
| Achsen, Regeln, Annahmen, Tarif-IDs | `make_houses` neu, dann rechnen |
| Anderer Standort, andere PV- oder Kollektor-Ausrichtung | Einmal mit `--allow-network` bauen und rechnen, damit die Wetterdateien entstehen |
| Anderes Preisjahr | Preis-CSV holen (`python -m studies.poc_cloud.fetch_prices --start 2024-01-01 --end 2025-01-04`), Brennstoffpreise eintragen. Der Generator bricht ab, solange das Jahr nicht das letzte volle Archivjahr ist: Wärmemodell und Grundlast rechnen mit diesem Jahr (`last_full_archive_year`), nicht mit dem Preisjahr |

## 4. Stolperstellen

- **`make_houses` löscht das Paket des Hauses** samt `results/`. Ergebnisse vorher sichern.
- **Jahresränder:** Ein Jahreslauf braucht auch die Wetterdateien der Nachbarjahre.
- **PV-Punkte:** `kwp` im Paket ist nominal × Performance Ratio, die Punkte in `house.json` rechnen mit dem nominalen Wert.
- **Brennstoff in der Leiter:** `saving_l2_l3_eur` und `rule_share` in den CSVs sind reiner Strom. Bei Häusern mit Brennstoff
  zählen `saving_l2_l3_with_fuel_eur` und `rule_share_with_fuel`, die Stufen stehen in `l0_total_eur` bis `l3_total_eur`.
  Läufe von vor dieser Spalte brauchen für die CSVs einen neuen Lauf.
- **Pakete ausgeschiedener Häuser:** `packs_s1/S5` (Wärmepumpe mit Heizstab) bleibt auf der Platte, steht aber nicht mehr in
  `haeuser.json`. `make_houses` kann es nicht mehr bauen.
