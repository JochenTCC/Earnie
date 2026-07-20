# SE consumption mini-profiles

Static house-profile fixtures for the **profile_spec ≈ Historisch hourly** invariant
(Szenario-Explorer Jahres Verbrauch family of bugs).

Used by `tests/test_se_consumption_invariants.py`. No MILP, no full config pack.

| File | Intent |
|------|--------|
| `ev_power_capped.json` | Low `nominal_power_kw` vs high SOC need (2026-07-20 bug) |
| `ev_power_ok.json` | Control: wallbox power can deliver SOC energy |
| `thermal_overnight.json` | `thermal_annual` across sunset/midnight window |
| `known_plus_manual.json` | `earnie_role` known + manual in overlay |
| `greenfield_like.json` | Rest (known) + EV + thermal_annual smoke |
| `mixed_csv_thermal.json` | CSV `thermal_rc` overlay; test injects `profile_csv` |

Do not regenerate from prod dumps — keep these minimal and intentional.
