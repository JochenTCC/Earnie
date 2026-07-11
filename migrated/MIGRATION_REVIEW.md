# Migration Review (1.26.0 P5)

Manuelle Prüfung vor Deploy auf NAS.

## Hinweise

- Globaler battery_wear → batteries[] '5_0_kwh_speicher'.
- Export-Tarif 'export_fixed_3_70ct' mit k_push_cent=3.7 angelegt.
- house_profile_id 'example_efh' (thermal) mit Geo ergänzt.

## Nächste Schritte

1. Entwurf mit produktiver Konfiguration vergleichen.
2. `tariffs.json` und `house_profiles.json` in `config/` übernehmen.
3. `config.json` → `runtime_settings` nur noch IDs prüfen.
4. Live-Optimierung und Backtesting-Baseline testen.
5. Globalen Block `battery_wear` und `awattar` erst in P6 entfernen.
