# Monthly tariff scan (cloud routine)

Runbook for the scheduled Claude Code cloud routine that keeps the shipped tariff catalog
(`share/config/tariffs.json`) current. The routine prompt only points here, so changes to the
procedure go through a normal PR on this file.

Schedule: first Austrian working day of each month, 17:00 Europe/Vienna. The trigger fires on
days 1–5; step 0 exits early on every other day.

## Hard rules

- Work on a fresh branch `tariffs/scan-YYYY-MM` from `origin/main`. Never push to `main`, never merge.
- Only touch `share/config/tariffs.json` (and, if a primary-source URL changed, the matching line in
  `docs/referenz/tarife-quellen.md`). Never change `version.py`, schemas, code or tests.
- Values come **only from primary sources** (OeMAG, E-Control, the supplier's own site or price sheet).
  Aggregators and search-result snippets are leads, not sources — they have been observed to confuse
  the OeMAG Marktpreis with the E-Control Referenzmarktwert.
- Monthly curve values are written **only** via `python -m scripts.update_tariff_curves`, never by
  hand-editing JSON. Tariffs with `monthly_seed` are recomputed by the script.
- Stage B findings (price-sheet changes) are **reported, not applied**.
- If nothing changed and there are no findings, do not open a PR; end with a one-line summary.

## Step 0 — first-working-day guard

```python
import datetime as dt
from zoneinfo import ZoneInfo

def easter(y):  # anonymous Gregorian algorithm
    a, b, c = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = (h + l - 7 * m + 114) % 31 + 1
    return dt.date(y, month, day)

today = dt.datetime.now(ZoneInfo("Europe/Vienna")).date()
e = easter(today.year)
holidays = {dt.date(today.year, 1, 1), dt.date(today.year, 1, 6), dt.date(today.year, 5, 1),
            dt.date(today.year, 11, 1), e + dt.timedelta(1), e + dt.timedelta(39),
            e + dt.timedelta(50), e + dt.timedelta(60)}
first = today.replace(day=1)
while first.weekday() >= 5 or first in holidays:
    first += dt.timedelta(1)
print("RUN" if today == first else "SKIP")
```

On `SKIP`: stop immediately, no branch, no output beyond one line.

## Step 1 — setup

```bash
pip install -e ".[dev]" openpyxl
git fetch origin && git switch -c tariffs/scan-$(date +%Y-%m) origin/main
python -m scripts.update_tariff_curves --check   # must report no drift before we start
```

## Stage A — monthly curves (applied)

| Series | Primary source | Notes |
| ------ | -------------- | ----- |
| OeMAG Marktpreis (§ 13 ÖSG) → `--oemag` | <https://www.oem-ag.at/marktpreis> | Use the PV / "alle außer Wind" row, not wind. Published at the start of the following month. |
| E-Control Referenzmarktwert PV (§ 13 EAG) → `--refmarkt` | <https://www.e-control.at/documents/1785851/10823410/Referenzmarktwert_Entwicklung.xlsx> | Column „Photovoltaikanlagen“, Cent/kWh; the sheet carries the publication date. Published ~2nd–9th of the following month, so the newest month may not exist yet on day 1. |
| aWATTar SUNNY → `--set export:monthly_sunny_web_recherche:YYYY-MM=…` | <https://www.awattar.at/tariffs/sunny> | Current month's price, published by the 1st. Net = gross. |

1. Compare every published month with the catalog. Pass new months **and** revised past months.
2. Run the script with `--catalog-as-of <today ISO>`:

   ```bash
   python -m scripts.update_tariff_curves --oemag 2026-09=… --refmarkt 2026-09=… \
       --set export:monthly_sunny_web_recherche:2026-10=… --catalog-as-of 2026-10-01
   ```

3. Warnings about placeholder months or seeds ≤ 0 go into the PR body; do not work around them.
4. If a SUNNY value replaces a placeholder or estimate, update that tariff's `notes`
   ("Bekannte Monate …") accordingly.
5. Verify:

   ```bash
   python -m scripts.update_tariff_curves --check
   python -m scripts.validate_tariffs --tariffs share/config/tariffs.json --skip-scenarios
   python -m scripts.run_pytest tests/test_update_tariff_curves.py tests/test_monthly_float_rates.py \
       tests/test_tariff_plausibility.py tests/test_validate_tariffs_cli.py tests/test_tariff_pricing.py -q
   ```

## Stage B — price-sheet review (reported only)

For each tariff in `import_tariffs` / `export_tariffs` (skip seeded `monthly_table` tariffs — stage A
covers them), open the source named in `notes` or the supplier's product page and compare:
`settlement_fee_cent_kwh`, `markup_percent`, `monthly_fee_eur`, `fix_cent_kwh`, `k_push_cent`,
`settlement_mtu`, `prices_include_vat`, product name/label.

Priority when time is short: tariffs whose `notes` say "unverifiziert", "Follow-up", "noch zu klaeren"
or "Naeherung"; then AT tariffs; then DE/CH.

Mind net vs. gross: spot tariffs store fees **net** (`prices_include_vat: false`); fixed tariffs follow
their own `prices_include_vat` flag.

Report each finding as a row: tariff id · field · catalog value · source value · source URL (+ date
on the sheet) · confidence. Unreachable sources are findings too.

## Output

- Commit (English, conventional): `tariffs: monthly scan YYYY-MM (OeMAG, RefMarkt PV, SUNNY)`.
- Push the branch and open a PR against `main`:
  - **Stage A:** the script's change report (old → new), sources with retrieval date, and the
    "not yet published" months.
  - **Stage B:** the findings table, or "no deviations found".
  - Open issues: script warnings, placeholders, contradictions (e.g. a tariff's `notes` say it
    follows RefMarkt but its `monthly_seed` uses OeMAG).
