# Preise & aWATTar

## Bezugspreis (Live)

`main.py` und die App laden Stundenpreise von der aWATTar-API (`awattar.url`). Daraus wird der **Bezugspreis in Cent/kWh** berechnet:

```
Marktpreis (API)
  × netzverlust_faktor
  + fix_aufschlag_cent
  × mwst_austria_faktor   (falls konfiguriert)
```

| Feld in `awattar` | Bedeutung |
|-------------------|-----------|
| `url` | API-Endpunkt (Standard Österreich) |
| `fix_aufschlag_cent` | Fixer Aufschlag Netz/Gebühren in Cent/kWh |
| `netzverlust_faktor` | Multiplikator für Netzverluste (z. B. 1.03) |
| `mwst_austria_faktor` | USt-Faktor (z. B. 1.2 für 20 %) |

## Einspeisevergütung

Steht in `runtime_settings.k_push_cent` (Cent/kWh). Wird bei Einspeisung ins Netz als Erlös angesetzt — in der Sidebar als „Einspeisevergütung“ editierbar.

**Hinweis:** Vergütung kann sich ändern (z. B. monatlich). Wert in `config.json` bzw. Sidebar aktuell halten.

## Fehlende Zukunftspreise

Wenn die API für späte Stunden des 24h-Horizonts noch keine Preise liefert, **spiegelt** die Optimierung die gleiche Uhrzeit vom Vortag (in Charts als extrapoliert gekennzeichnet — siehe [Charts](../ui/charts.md)).

## Historische Preise

Für **Historischer Tag** und **Backtesting**: `file_paths_battery_simulation.price_source`, `price_provider`, `price_range` und ggf. `path_price` (Energy-Charts-CSV, Zone `energy_charts_bzn`).
