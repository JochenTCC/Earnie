# Doc review checklist (2.8 quality gate)

Temporary checklist for step 5 of the quality gate (skill `quality-gate`). Started 2026-11-23 for
2.8.0 (before `2.8.0-beta.1`), against `main` @ `a87940cc`. Move to
`docs/dev/done/doc-review-checklist-<version>.md` when the release is created.

**Check** = facts against the code and the 2.8 features (capacity charge / import cap with
observe and optimize modes and margin 0.7 kW, month peak in the planning timezone, price-aware
virtual reserve, "Mit Earnie gespart" tile and savings ledger, Edibert v0.1.16 tariff overview,
support package / debug dump, quarter-hour planning, removed features, links and anchors).
**Style** = German user docs per `german-user-docs.mdc`, English docs plain technical English.

Legend: `ok` = checked, nothing to change · `fixed` = corrected in this pass · `finding` = open
item under `## Document Review Findings` in `backlog/Backlog-Bugfixes.md`.

Automated checks over all rows: relative links and anchors (0 dead after the fixes),
`python -m scripts.*` modules and backticked repo paths (all exist), backticked snake_case keys
(all found in Earnie or Edibert code, or Victron register names), `tests/test_user_docs_audience.py`
and `tests/test_doc_links.py` green.

## User docs (German)

| Document | Check | Style | Notes |
|---|---|---|---|
| `README.md` | fixed | ok | 2.8 features in Funktionen and Roadmap; "Analyse Verbrauch & Kosten" no longer has the SwimSpa comparison |
| `docs/README.md` | ok | ok | TOC complete for the user-doc folders |
| `docs/user-manual/Benutzer-Handbuch-Earnie.md` | fixed | ok | explicit anchor for "Warum weicht Historisch …" (dead link) |
| `docs/einrichtung/betrieb.md` | fixed | ok | month peak in the site timezone; `pv_counter_state.json` holds power + timestamp; doubled wording in `savings_ledger.jsonl` row |
| `docs/einrichtung/container.md` | fixed | ok | alpha pin `2.7.0-alpha.9` |
| `docs/einrichtung/greenfield-dev-stack.md` | fixed | ok | version example |
| `docs/einrichtung/ha-evcc.md` | fixed | ok | SoC warning text on network backends |
| `docs/einrichtung/homeassistant-addon.md` | ok | ok | |
| `docs/einrichtung/loxberry-plugin.md` | ok | ok | |
| `docs/einrichtung/loxone-anbindung.md` | finding | ok | retired plant PV field, incomplete binding stores |
| `docs/einrichtung/openems-lab.md` | ok | ok | |
| `docs/einrichtung/private-env.md` | ok | ok | |
| `docs/einrichtung/proxmox-lxc.md` | ok | ok | |
| `docs/einrichtung/smarthome-backend-wahl.md` | fixed | ok | Merker mapping assistant removed (Signalliste templates) |
| `docs/einrichtung/vmware-vctl.md` | ok | ok | |
| `docs/konfiguration/overview.md` | fixed | ok | filter label "Land" |
| `docs/konfiguration/batterie-pv.md` | fixed | ok | horizon switch under "Sonne & Horizont"; grid meter under "Netzanschluss & Netzentgelt"; virtual reserve and `idle_drain_kw` ok |
| `docs/konfiguration/flexible-verbraucher.md` | finding | ok | internal IDs (SUSI P2, L2) |
| `docs/konfiguration/preise.md` | fixed, finding | ok | anchor for Benutzertarife; Netzbereich group; `monthly_sunny_web_recherche`; Leistungspreis ok; schema lacks `live_bias_*` |
| `docs/konfiguration/speichern-laden.md` | fixed | ok | data model 6, migratable 3–5 |
| `docs/konfiguration/verbrauchs-csv.md` | ok | ok | |
| `docs/konfiguration/waermespeicher-schichtung-teq.md` | ok | ok | |
| `docs/ui/betriebsmodi.md` | fixed, finding | ok | Tarife in nav table; data sources without "Stunde 0"; Leistungspreis section under Chart 2; Preis-Prognose condition; EV-SoC row unclear |
| `docs/ui/charts.md` | fixed, finding | ok | neutral zone; Sankey code path; push interval 10 s; deviation rule IDs from the template; EV-SoC row unclear |
| `docs/ui/smarthome-backend.md` | ok | ok | |
| `docs/referenz/abbreviations.md` | fixed, finding | finding | SA = sunrise anchors, QH added, mapping wording; whole page English |
| `docs/referenz/loxone-signals.md` | fixed, finding | ok | EV `min_current_a`/`max_current_a`; push env name; legacy `flex.` IDs and plant PV field open |
| `docs/referenz/oemag-referenzmarktwert.md` | ok | ok | |
| `docs/referenz/tarife-quellen.md` | ok | ok | |

## English technical docs

| Document | Check | Style | Notes |
|---|---|---|---|
| `DEVELOPER.md` | fixed, finding | ok | tests through `scripts.run_pytest` and the test queue; private-repo path (Shadow spec) |
| `docs/referenz/ehal.md` | fixed, finding | ok | listener `integrations/ehal_request_http.py`; HA REST pull removed; plant PV row, internal IDs, private-repo path open |
| `docs/ui/ehal-com.md` | fixed, finding | ok | inverter Loxone names fixed (no TBD); push env names; legacy `flex.` IDs and plant PV rows open |

## Developer operations (German)

| Document | Check | Style | Notes |
|---|---|---|---|
| `docs/entwicklung/README.md` | ok, finding | ok | private-repo reference (Shadow) |

## Result

33 documents checked; 18 changed with 34 corrections; 8 open findings under
`## Document Review Findings` in `backlog/Backlog-Bugfixes.md`.
