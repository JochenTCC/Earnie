# Home Assistant add-on — dogfood checklist (Ingress / options)

Internal manual check, moved out of the user doc `docs/einrichtung/homeassistant-addon.md`. Test host: HAOS in a VM (Synology). Test environment setup: `docs/dev/homeassistant-addon-testumgebung.md`.

1. Start the add-on (version **2.5.3** or newer) with Ingress. Earnie appears in the sidebar / OPEN WEB UI **without** `:8501` or an IP lookup. Right after start the "Earnie startet noch" page or a short 502 is expected; the UI is reachable after about 30 s.
2. Charts and navigation load (no "Not found", no blank page, no mass of 404s under `/static` or `_stcore`).
3. Optional: `http://<ha-ip>:8501` (nginx) opens the same UI.
4. Fresh data: the Smarthome backend targets HA; authentication via the Supervisor proxy works.
5. Restart: `/config` (addon_config), `/data/earnie_env/runtime` and the merged or newly created `config.json` are preserved.
6. Optional: HA backup of the add-on, then restore. `addon_config` must restore `config.json` (manual gate for Sprint 2).

> **Note:** `2.5.3-alpha.4` set only the Streamlit `baseUrlPath` without nginx prepending the path again, so Ingress and host `:8501` reported "Not found".
