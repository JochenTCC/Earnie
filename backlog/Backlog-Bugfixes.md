# Open Bugs

Completed items → [Backlog-Erledigt.md](Backlog-Erledigt.md) (sections `### Bugfix …` / `### Document Review …` / regressions)

Feature roadmap → [Backlog.md](Backlog.md)

## Classification

**Here:** Prod deviation, regression (`xfail`), known misbehavior, review with clear fix/remove outcome; plus `## Document Review Findings` (docs corrections).
**Not here:** New behavior, UX, models, research — see feature backlog in `Backlog.md`.
**Versioning:** completed bugfixes → **PATCH** only in `version.py` (no minor bump). Docs-only findings: no version bump unless asked.
**Document Review Findings:** After the agent corrects the docs → move straight to `Backlog-Erledigt.md` (skip Verifications Pending). See skill `doc-review-findings`.

### `## Bugfix Verifications Pending`

Fix is **implemented** (code + tests + optional PATCH in `version.py`), but **prod/live acceptance** is still pending.

- Move item from the thematic bugfix chapter here once the fix is committed — **not** directly to `Backlog-Erledigt.md`.
- Briefly note what changed (commit/version) if helpful.
- After successful verification: remove from this chapter → `Backlog-Erledigt.md` (`### Bugfix …`) with `- [x]`.
- If verification fails: return to open bugfix chapter or formulate follow-up; document PATCH if applicable, but do not archive as done.


## Bugfix Verifications Pending (Do not remove this chapter — even if empty) + Testing Todos

- [ ] **Live golden dump (private REG):** when the fixed version is running on productive NAS, capture a debug dump (with `recorder/`) around a cheap-slot Delta 3 refill and intake as a private golden case confirming charge ≤ HK ∩ live (Delta 3 standby HK/live limits fix; verified 2026-10-21).
- [ ] **F20 (Schreibtest 0 W warning without a complete live scenario) - fixed, verify live:** `ui/ehal_write_test.py::power_limit_unknown_notice` explains why every power value is rejected when the live scenario has no battery maximum (unit tested). The bench scenario is complete (max power > 0), so the warning was **not** exercised live; needs a pack with an incomplete live scenario. (F23 - Live-Lesen value / receipt time - is verified and archived.)
- [ ] **HA: a forced `set_ess_active_power` is never released (L18, decision needed):** confirmed in the bench 2026-10-22: after a force charge (`-2000 W`) Earnie returns to automatic by *omitting* `set_ess_active_power` and publishing `set_ess_mode = 0`; the ledger keeps the old `-2000`, the HA `number` keeps it, and the battery keeps charging (`ess_power -2000 W`, SoC rising) over two further automatic cycles. The mode now arrives in HA (`number.earnie_ess_house_set_ess_mode` 1 -> 0) but nothing acts on it: the generated carrier has no automation for the mode, and the Huawei `ha_ess_force` automation triggers on the active power only (it releases at `|power| < 1`). Options: (a) publish `set_ess_active_power = 0` on automatic (releases Huawei, but is a hold-at-0 W on devices where 0 is a force value - the sim), (b) drop the stale ledger entry plus an HA-side reset, (c) the carrier generates a mode-0 automation that resets the active-power `number`. Decide, then fix with a test. Same sticky pattern exists on the Loxone path, where the Loxone program is documented to treat mode 0 as release.


## New Bugs (Do not remove this chapter — even if empty)

Found by the HA testbed baseline run (2026-10-21; evidence and finding ids F1–F18 in [`docs/dev/ha-contract-testbed.md`](../docs/dev/ha-contract-testbed.md) §3a):


Found by the first live run of the bench (2026-10-22; finding ids L1–L13 in the same doc, § 3f):

- [ ] **Carrier skip message names the wrong cause (L13):** `integrations/ha_carrier_yaml.py` logs `unknown or incompatible unit_of_measurement … (need numeric)` when the published setpoint value is not numeric; the generated template never reads the unit for that decision. Fix the wording (+ test on the YAML).



## Minor changes (no bugs but still not worth to put it in backlog.md - do not remove this chapter - even if empty)

- [ ] Set default "Temperaturabsenkung" in annual-rc to 2.5°C
- [ ] Review and modify text in SE review pop-up dialogue


## Document Review Findings (Do not remove this chapter — even if empty)

- [ ] **Cloud demo vs „einmalig“ for SE star review** (`docs/einrichtung/betrieb.md`, `private-env.md`): with `EARNIE_CLOUD_DEMO=1` each browser session uses a temp workspace, so `feature_reviews.json` is session-scoped — “once per install” wording may overstate permanence on Community Cloud. Confirm whether docs should say once per session there.
- [ ] **`verify_loxone_setup` error wording** (`docs/einrichtung/loxone-anbindung.md`): „Miniserver-Callback auf `status.json` fehlt“ may not match push-only VI polling; check against script messages.
- [ ] **`Earnie_Batterie_Sollleistung` in Automatik tip** (`docs/einrichtung/loxone-anbindung.md`): catalog name vs qualified VI / optional Namenskatalog — align wording.
- [ ] **Einspeisegrenze wording** (`docs/konfiguration/batterie-pv.md`): clarify „Ohne geplante Wechselrichter“ and which two values „beide unbekannt“ refers to; confirm `1000` kW vs EHAL 1 000 000 W.
- [ ] **Handbook vs activation-flag bindings** (`docs/user-manual/Benutzer-Handbuch-Earnie.md`): after the export/Signalliste rewrite, residual Merker/Entity mapping wording may be stale — Allgemeine Verbraucher „Loxone-Leistungsmerker zuordnen“; Hausprofil / EHAL-Com Abwesenheitsmodus still names Loxone Merker / HA-Entity / OpenEMS channel as if stored in Earnie; Haus-Wärme „über EHAL-Bindings“ could point to Signalliste instead.
- [ ] **Broken handbook fragments in `ui/doc_links.py` / inbound docs:** `kurz-checkliste-vom-initial-zustand-zum-go-live` vs heading „vom ersten Start zum Go-Live“; `analyse-verbrauch-kosten` vs GitHub `analyse-verbrauch--kosten`; `gesamtkosten-und-verbrauch-jahres-verbrauch-kwh` vs likely double-hyphen slug; `betriebsmodi.md` / `charts.md` link `#gesamtkosten-jahres-verbrauch-kwh` (missing in handbook). Fix fragments or add `<a id>` anchors.
