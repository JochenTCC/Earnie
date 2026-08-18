## Feature: Auto-Discovery for Third-Party Integrations (Loxone / Home Assistant / OpenEMS)

**Context:** EHAL extension – local Earnie instance automatically detects compatible third-party systems on the home network and suggests a connection (instead of manual configuration).

### Goal
An `integration_scanner.py` module that runs during onboarding or on manual trigger, finds possible integrations on the local network, and presents them to the user for confirmation (no automatic connection).

### Detection Strategies per System

| System | Method | Details |
|---|---|---|
| **Home Assistant** | Passive: mDNS | Advertises itself as `_home-assistant._tcp.local` |
| **Loxone** | Passive: UDP broadcast discovery | Miniserver's own discovery protocol (same as Loxone Config) |
| **Loxone** | Passive: SSDP/UPnP | M-SEARCH request to `239.255.255.250:1900` |
| **OpenEMS** | Active: port scan | No mDNS available → target ports **8080** (Apache Felix) and **8085** (UI websocket), verify via HTTP signature against the Felix console |
| **All** | Fallback: active subnet scan | If passive methods yield nothing (e.g., VLAN segmentation blocks mDNS) |

### Key Constraints
- **User confirmation required** – detected systems are suggested, never auto-connected
- Passive methods (mDNS/SSDP) as default; active scan only with explicit user consent (risk: firewall/IDS alerts, e.g. on UniFi setups)
- OpenEMS ports are configurable → port scan may miss non-standard installations; default Docker setup should be reliably detected
- Purely local LAN operation, no cloud dependency → not privacy-critical

### Open Questions
- Where exactly to place this within the EHAL architecture (new submodule vs. extension of existing adapters)?
- How to handle non-standard port configurations for OpenEMS?

