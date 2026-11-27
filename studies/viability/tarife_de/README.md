# German tariffs for the viability study

Study data, not catalog entries: the public catalog (`share/config/tariffs.json`, `grid_fees.json`) is frozen
(`tests/test_catalog_frozen.py`). `make_houses` copies both files into every pack when the parameter file sets
`netz.nutzer_tarife` to this folder (`haeuser_de.json`).

| File | Content |
|---|---|
| `user_tariffs.json` | `user_de_tibber_simple_fix`: Tibber Simple Fix, energy share net of grid fees and levies (derivation in `source`) |
| `user_grid_fees.json` | Netze BW 2026: standard work price (`user_de_netze_bw_2026`) and section 14a module 3 (`user_de_netze_bw_2026_modul3`), concession fee, levy set 2026, grid base fee and iMSys metering |

Dynamic import (`de_tibber_tibber_dynamic`) and feed-in (`de_tibber_tibber_einspeisung_monats_marktwert`) come
from the catalog. Prices before 2026 are priced with the 2026 values; the section 14a module 1 credit
(124 EUR/a) is not modelled (no negative yearly amounts).
