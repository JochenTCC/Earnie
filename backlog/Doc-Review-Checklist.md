# Docs review checklist (since `v2.3.2`)
## Priority 1 — User-facing
- [x] `docs/user-manual/Benutzer-Handbuch-Earnie.md` — large rewrite; main handbook
- [x] `docs/ui/ehal-com.md` — **new** (~290 lines); replaces `docs/ui/loxone-kommunikation.md`
- [x] `docs/referenz/loxone-signale.md` — heavy rewrite; Virtual In/Out assets; **merged** former `loxone-earnie-library.md` (2026-08-06)
- [x] ~~`docs/einrichtung/loxone-earnie-library.md`~~ — merged into `loxone-signale.md`
- [x] `docs/einrichtung/loxberry-plugin.md` — **new**; LoxBerry plugin setup
- [x] `docs/einrichtung/adapter-wahl.md` — **new**; adapter selection
- [x] `docs/einrichtung/ha-evcc.md` — **new**; HA / evcc path
- [x] `docs/einrichtung/openems-lab.md` — **new**; OpenEMS lab path
- [x] `docs/einrichtung/loxone-anbindung.md` — medium rewrite; Loxone connection
- [x] `docs/README.md` — TOC / entry updates
- [x] `README.md` — landing page; logos

## 2.5.0 — QH MILP wording (2026-08-16)
- [x] `README.md` / `docs/README.md` — Daemon + MILP are 15‑min slots (no “hourly MILP”)
- [x] `docs/user-manual/Benutzer-Handbuch-Earnie.md` — Live-Betrieb: Viertelstunden-Slots
- [x] `docs/ui/charts.md` — Chart-1 bar width 15 min across horizon
- [x] `.github/ISSUE_TEMPLATE/bug.yml` — version placeholder `2.5.0`
- [x] `docs/spec/swimspa-filter.md` / `docs/spec/ui-menu-structure.md` — QH matrix granularity
- [x] `docs/konfiguration/preise.md` — already documents QH plan vs hourly settlement (`settlement_mtu`)
- [x] `docs/konfiguration/batterie-pv.md` — `standby_power_kw` already documented
