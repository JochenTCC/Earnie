# HA + evcc lab setup (2.4.c)

English developer bring-up for the DACH-default stack: **Earnie + Home Assistant + evcc**.

German user path A2 vs B: [`docs/einrichtung/ha-evcc.md`](../einrichtung/ha-evcc.md).

## Architecture

| Service | Role | Port (host) |
|---------|------|-------------|
| `earnie` | Streamlit + `main.py` (earnie-core) | **8506** |
| `homeassistant` | Umbrella; EHAL REST target | **8123** |
| `evcc` | Sidecar device I/O → HA entities | **7070** |

Earnie talks **only** to Home Assistant REST (`Bearer` long-lived token). Prefer stable HA entities that evcc exposes. No OpenEMS / Loxone libs; Separate Works containers.

## First start

```powershell
mkdir ha_lab\config, ha_lab\runtime, ha_lab\homeassistant, ha_lab\evcc
Copy-Item ha_lab\evcc\evcc.example.yaml ha_lab\evcc\evcc.yaml
docker compose --project-directory . -f docker/compose/ha-lab.yml up -d --build
```

1. Open Home Assistant → http://localhost:8123 — complete onboarding.
2. Create a **Long-Lived Access Token** (Profile → Security).
3. Configure evcc (`ha_lab/evcc/evcc.yaml`) for lab meters/charger **or** use HA demo helpers/`input_number` for dry-run.
4. Expose evcc entities into HA (MQTT discovery / official integration — lab choice).
5. Bootstrap Earnie config under `ha_lab/config/` (copy from `share/config` / bootstrap as usual).
6. Merge [`share/config/ehal.ha.snippet.json`](../../share/config/ehal.ha.snippet.json) into `config.json`, set token + URL `http://homeassistant:8123`.
7. In Streamlit (**Loxone-Com** → expander **HA Entity → EHAL Mapping**): scan entities, map M1 fields, save.
8. Disable hub-local surplus/spot strategies (checklist below).

## Earnie-mode checklist (optimizer exclusivity)

- [ ] evcc: no surplus / smart-cost / spot charge planner fighting Earnie
- [ ] Loadpoint mode allows Earnie to set max current (via HA `number` entity)
- [ ] No HA automations writing the same setpoint entities Earnie owns
- [ ] Spot prices + 48h schedule come from Earnie only
- [ ] **Modbus:** exactly one writing southbound owner per physical bus/device (typically evcc)

## Communication check

From the Earnie container (or host with mapped ports):

```text
GET http://homeassistant:8123/api/
Authorization: Bearer <token>
```

Then use Streamlit **Telemetrie testen** after mapping, or:

```powershell
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'
.venv\Scripts\python.exe -c "from integrations.ha_adapter import HaAdapter, HaConfig; ..."
```

Failed writes → capability degrade + `runtime/ehal_write_error.json` + UI banner (same as OpenEMS).

## Config switch vs OpenEMS

Same Earnie Core: set `ehal.backend` to `ha` or `openems` and the matching hub block. Contract-tests in `tests/test_ehal_contract_openems_ha.py` assert Live-shaped parity on fixtures.

## Out of scope here

- HA WebSocket state subscription
- Direct evcc REST/MQTT adapter (lab-only option deferred)
- LLM-assisted mapping (2.5)
