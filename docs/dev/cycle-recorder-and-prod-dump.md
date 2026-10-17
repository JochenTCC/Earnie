# Cycle recorder and prod dump as regression fixture

Developer notes, moved out of the user doc `docs/einrichtung/betrieb.md`. Spec: [`docs/workflow/regression-suite.md`](../workflow/regression-suite.md) §14.

## Cycle recorder (ring buffer for regression tests)

Earnie stores the full optimization inputs of every cycle in a ring buffer under `runtime/recorder/`. This allows bugs that only show up days later to be reproduced as a reference case (golden master). The files contain **load profiles** and stay **local**; Earnie never uploads them.

Settings in `runtime/local_settings.json`:

```json
{
  "recorder_enabled": true,
  "recorder_retention_days": 7
}
```

- **Default:** on (`true` / key missing). Disable with `"recorder_enabled": false`.
- **Retention:** number of days Earnie keeps the segment files `cycles_YYYY-MM-DD.jsonl.gz` (default 7). Config snapshots live under `recorder/configs/`.
- **Debug dump:** a debug dump automatically attaches the current recorder window (`recorder/` in the ZIP, `manifest.recorder` with `from` / `to` / `cycle_count` / `config_hashes`). Hand the dump only to the maintainer.

## Prod dump as regression fixture

A saved debug ZIP can be adopted into `tests/fixtures/prod_dumps/<id>/`:

```bash
python scripts/archive_prod_dump.py \
  --id my_case_2026-07-16 \
  --title "Short description" \
  --symptom "Observed symptom" \
  --source runtime/chart_debug/debug_dump_….zip
```

Details: `tests/fixtures/prod_dumps/README.md`.
