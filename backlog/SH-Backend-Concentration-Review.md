# SH-backend concentration review

Review for Backlog 2.7: *Any SH-Backend communication should be concentrated at one code*.

**Verdict:** There is already an intended single entry for plant live I/O — [`integrations/ehal_live.py`](../integrations/ehal_live.py) → `*Adapter`. Communication is **not fully concentrated**: Loxone flex / EV / thermal / powerstation / Huawei paths still call [`loxone_client`](../integrations/loxone_client.py) / [`loxone_writes`](../integrations/loxone_writes.py) from `optimizer/`, `main.py`, and `data/`. Refactor is warranted as a **phased follow-up**, not a greenfield rewrite.

## Existing façade

| Entry | Role |
|-------|------|
| `ehal_live.get_adapter()` | Active backend (Loxone / HA / OpenEMS) |
| `LoxoneAdapter` / `HaAdapter` / `OpenemsAdapter` | Hub HTTP or push/publish for M1 telemetry/setpoints |
| `ehal_write.write_field` | Loxone loud setpoint ledger (`status.json`; Miniserver polls) |

`CONTRIBUTING.md` already documents: new hub → `integrations/<hub>_adapter.py` + wire in `ehal_live.py`.

## Scatter (outside façade)

| Area | Callers | Path today |
|------|---------|------------|
| Daemon flex / Huawei | `main.py` | `loxone_client.send_*` beside `ehal_live.write_*` |
| EV / charging | `optimizer/charging_*.py`, `charge_immediate.py`, … | `fetch_loxone_generic_value` (push inbox) |
| Thermals | `optimizer/thermal_*.py` | `loxone_client` temps / meters |
| Absent | `optimizer/absent_mode.py` | Loxone via `loxone_client`; HA/OpenEMS via adapter `read_*` bypassing `read_telemetry` |
| Powerstation | `optimizer/powerstation_live.py` | Loxone `_publish_setpoint_traced`; HA via adapter |
| Live data | `data/live_consumption.py`, … | `loxone_client` |
| Backend flags | `ehal_live` **and** `config` | Duplicate `is_*_backend` helpers |

No production MQTT/WebSocket for hubs. Price/weather HTTP under `integrations/` / `data/` is out of SH scope.

## Keep outside the live façade

| Layer | Why |
|-------|-----|
| `loxone_structure`, MCP probe, `integration_scanner`, `ha_supervisor` | Setup / discovery |
| `loxone_request_http` + push inbox | Inbound transport; adapters **read** the inbox |
| `ui/ehal_*_mapping`, greenfield import | HITL (may call thin probe helpers) |
| `ehal/*` registry / catalog / qualified IDs | Pure mapping rules, no network I/O |

## Phased refactor — done (2026-10-11)

1. **Phase A — API surface:** `integrations/ehal_live_ops.py` + re-exports on `ehal_live`.
2. **Phase B — Call-site migration:** `optimizer/*`, `data/*`, `main.py`, `runtime_store/power_interval_sampler.py` use `ehal_live`.
3. **Phase C — Collapse Loxone internals:** Import ban outside `integrations/` (`tests/test_no_loxone_client_outside_integrations.py`).
4. **Phase D — Dedupe backend flags:** `ehal_live.is_*_backend` canonical; `config.is_ehal_*` removed.

UI constructing a temporary `HaAdapter` for entity discovery is acceptable if wrapped as e.g. `ehal_live.probe_ha_entities(...)`.
