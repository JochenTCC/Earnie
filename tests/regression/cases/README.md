# Public regression cases

Golden-master cases for the release regression suite (epic **Regression** P1+P2).

| ID | Level | Source |
|---|---|---|
| `REG-O-winter-jan` | L1 | Seeded recorder (January window) |
| `REG-O-autumn-nov` | L1 | Seeded recorder (November window) |
| `REG-S-negative-prices` | L1 | Synthetic negative `k_act` overlay |
| `REG-O-summer-june` | L2 | `tests/fixtures/backtesting/` low-EV day |
| `REG-O-ev-deadline` | L2 | Fixture high-EV day |
| `REG-O-heat-swimspa` | L2 | Fixture SwimSpa / two-day window |
| `REG-O-prod-*` | L1-invariants | Wrappers around `tests/fixtures/prod_dumps/` (tier-1 only) |

Shared recorder data lives under `tests/regression/fixtures/` (not duplicated per case).

**Customer cases** live in the private sibling repo `Earnie-regression-private` (`$EARNIE_REGRESSION_PRIVATE_DIR` or `..\Earnie-regression-private\cases`). See [`docs/einrichtung/private-env.md`](../../../docs/einrichtung/private-env.md) and `python -m scripts.run_regression --intake … --private`.

**Live refresh:** replace seed-based L1 windows with real `runtime/recorder/` cycles when dogfood has them; re-run `--update-golden` and re-check ±0.05 % tolerances.

```powershell
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'
.venv\Scripts\python.exe -m scripts.run_regression --workers 4
.venv\Scripts\python.exe -m scripts.run_regression --update-golden --case REG-O-winter-jan
```
