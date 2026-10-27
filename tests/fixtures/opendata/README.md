# Open-Meteo / Energy-Charts parity fixture (Edibert P6)

Recorded with `python -m scripts.opendata_golden record` on the pre-P6 access code, clock frozen at
2026-10-27 18:00 Europe/Vienna. Read by `tests/test_opendata_parity.py` (replay, no network).

- `responses.json.gz`: HTTP responses keyed by URL and parameters (gzip JSON).
- `expected.json`: outputs and request list per entry point.

Data sources and licences:

- Open-Meteo (archive and forecast), https://open-meteo.com/, CC BY 4.0.
- Energy-Charts (Fraunhofer ISE), https://energy-charts.info/, CC BY 4.0.
