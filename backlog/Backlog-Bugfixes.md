# Open Bugs

Completed items → [Backlog-Erledigt.md](Backlog-Erledigt.md) (sections `### Bugfix …` / regressions)

Feature roadmap → [Backlog.md](Backlog.md)

## Classification

**Here:** Prod deviation, regression (`xfail`), known misbehavior, review with clear fix/remove outcome.
**Not here:** New behavior, UX, models, research — see feature backlog in `Backlog.md`.
**Versioning:** completed bugfixes → **PATCH** only in `version.py` (no minor bump).

### `## Bugfix Verifications Pending`

Fix is **implemented** (code + tests + optional PATCH in `version.py`), but **prod/live acceptance** is still pending.

- Move item from the thematic bugfix chapter here once the fix is committed — **not** directly to `Backlog-Erledigt.md`.
- Briefly note what changed (commit/version) if helpful.
- After successful verification: remove from this chapter → `Backlog-Erledigt.md` (`### Bugfix …`) with `- [x]`.
- If verification fails: return to open bugfix chapter or formulate follow-up; document PATCH if applicable, but do not archive as done.


## Bugfix Verifications Pending (Do not remove this chapter — even if empty) + Testing Todos

- [ ] **EVCS `set_evcs_mode` with max current** — fixed current charging wrote mode `0`; now `2` (`now`) with `set_evcs_max_current`, PV surplus `1`, idle `0` (`698fc6a`, `v2.4.0-alpha.2`).
- [ ] **SwimSpa filter power also on heating Ist** — shared meter: auto `subtract_consumer_ids` + native-filter inference over shared-meter heating ids (`v2.4.0-alpha.4`).

## New Bugs (Do not remove this chapter — even if empty)

- [ ] Crash in streamlit community cloud when switching to SE with minimum Scenario Configuration:
  - File "/mount/src/earnie/app.py", line 98, in <module>
    main()
    ~~~~^^
File "/mount/src/earnie/app.py", line 91, in main
    navigation.run()
    ~~~~~~~~~~~~~~^^
File "/home/adminuser/venv/lib/python3.14/site-packages/streamlit/navigation/page.py", line 494, in run
    self._page()
    ~~~~~~~~~~^^
File "/mount/src/earnie/ui/pages/page_backtesting.py", line 32, in render
    render_backtesting_block()
    ~~~~~~~~~~~~~~~~~~~~~~~~^^
File "/mount/src/earnie/ui/backtesting.py", line 739, in render_backtesting_block
    cons_ready = render_cons_data_section()
File "/mount/src/earnie/ui/backtesting_cons_data.py", line 52, in render_cons_data_section
    render_time_range_help(key="backtesting_time_ranges_cons_data")
    ~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
File "/mount/src/earnie/ui/backtesting_time_ranges.py", line 92, in render_time_range_help
    "\n".join(f"- {line}" for line in build_time_range_help_lines(log_period=log_period))
                                      ~~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^
File "/mount/src/earnie/ui/backtesting_time_ranges.py", line 50, in build_time_range_help_lines
    sim_start, sim_end = default_simulation_window()
                         ~~~~~~~~~~~~~~~~~~~~~~~~~^^
File "/mount/src/earnie/ui/backtesting_time_ranges.py", line 30, in default_simulation_window
    start, end = resolve_simulation_window(configured_price_range())
                 ~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^
File "/mount/src/earnie/data/data_loader.py", line 63, in resolve_simulation_window
    raise ValueError(
        "Kein Zeitraum für die Simulation: cons_data_hourly.csv fehlt oder ist leer."
    )
- [ ] Zähler Energiebezug can be ignored for consumers (not an Earnie issue)

## Organizational Changes - no bugs (but still no development issue)
