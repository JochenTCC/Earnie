# Hardware registry & Banner Layer C (2.4.i spike)

**Status:** Design + non-enforcing spike (2026-07-28).  
**Related:** Banner A + light B (`ui/truth_banner.py`, shipped 2.2.0); plan outline `.cursor/plans/banner_der_wahrheit_0dfdf6a6.plan.md`; Entwicklungsplan §6 (hardware lock).

This document answers backlog **2.4.i**: how a user obtains a one-time registry bound to hardware, and what technical prerequisites Layer C needs. Enforcement (signed GHCR builds, refuse-to-start / watermark) is **deferred**.

---

## 1. User flow — one-time registry

1. User runs Earnie (GHCR image or local install) and opens **Info / About**, or runs:

   ```text
   python -m scripts.print_hardware_fingerprint
   ```

2. They see a **hardware fingerprint** (SHA-256 hex, display may truncate to 16 chars) derived from southbound system ID(s) + host machine id.

3. User sends that fingerprint once (existing contact mailto today; Cloud portal later) and receives an entitlement file `earnie_registry.json` bound to that fingerprint.

4. User places the file in the env runtime directory (default name `earnie_registry.json`), or sets `EARNIE_REGISTRY_PATH`.

5. Soft checker reports `unbound` | `valid` | `mismatch` | `invalid_sig`. **Unbound remains valid private use** — no start block in this spike.

6. **Future Layer C only:** official sealed images may require a valid entitlement *or* show an indelible watermark. Source forks stay unsupported; we do not claim forks keep the banner.

**End-user how-to (German):** [`docs/user-manual/Benutzer-Handbuch-Earnie.md`](../user-manual/Benutzer-Handbuch-Earnie.md) § Hardware-Registry.  
**Issuer procedure (generation):** Earnie-Projekt `Entwicklungsplan/Hardware-Registry-Ausstellung.md`.

---

## 2. Fingerprint composition

Canonical parts (omit empty values):

| Key | Source (spike) |
|-----|----------------|
| `host` | Linux `/etc/machine-id`; Windows `MachineGuid` (fail soft) |
| `loxone` | `EARNIE_LOXONE_SERIAL` (env); live Miniserver scrape later |
| `ha` | `EARNIE_HA_INSTANCE_ID` (env placeholder) |
| `openems` | `EARNIE_OPENEMS_EDGE_ID` (env placeholder) |

**Algorithm:**

1. Build lines `key=value` for non-empty stripped parts.
2. Sort lines lexicographically by key.
3. Join with `\n` (UTF-8).
4. `fingerprint = SHA-256(hex)` of that payload.
5. If **no** parts: fingerprint is SHA-256 of the empty string (deterministic sentinel). Documented so empty installs are detectable, not random.

Display helper may show the first 16 hex chars; entitlement and verify always use the full 64-char hex.

Implementation: `runtime_store/hardware_identity.py`.

---

## 3. Entitlement JSON (dev PoC)

Schema: `share/registry/entitlement.schema.json`.

| Field | Meaning |
|-------|---------|
| `fingerprint` | Full SHA-256 hex of bound hardware |
| `issued_at` | ISO-8601 UTC |
| `expires_at` | ISO-8601 UTC or `null` (one-time forever) |
| `issuer` | e.g. `earnie-dev` |
| `sig_alg` | spike: `hmac-sha256` |
| `sig` | Hex HMAC over canonical payload (see below) |

**Signing payload (UTF-8, no trailing newline):**

```text
fingerprint={fp}\nissued_at={…}\nexpires_at={null|iso}\nissuer={…}\nsig_alg=hmac-sha256
```

**Dev only:** verify with `EARNIE_REGISTRY_DEV_SECRET`. Not for production. Prod Layer C will use asymmetric keys + offline public key in the image.

Issuer script: `python -m scripts.issue_dev_registry_token --fingerprint … --out path`.

Loader / soft status: `runtime_store/registry_entitlement.py` → `registry_status()`.

---

## 4. Technical prerequisites (Layer C later)

| Layer | Prerequisite | After 2.4.i |
|-------|--------------|-------------|
| Identity | Stable southbound IDs + host fallback | Spike helper |
| Entitlement | Signed JSON + issuer key | Dev HMAC schema + scripts |
| Distribution | GHCR attestation (cosign/Sigstore); `permissions: id-token: write` + `packages: write` on `.github/workflows/release.yml` | Documented only — **release.yml unchanged** |
| Verifier | Check image attestation + entitlement; refuse **or** indelible watermark | Soft UI status only |
| Offline / air-gap | Bundled public key; no phone-home required for verify | Called out; not implemented |
| Policy | LICENSE §2 commercial exceptions stay manual | Non-goal |

### GHCR attestation outline (not wired)

After multi-arch push in release workflow:

1. Add `id-token: write` to job permissions.
2. Install cosign; `cosign attest` / `cosign sign` the pushed digests (`ghcr.io/jochentcc/earnie-energy:<version>`).
3. Future verifier inside official image: resolve own image digest, verify attestation against project identity; combine with entitlement check.
4. Air-gapped official installs need the public key (or offline attestation blob) shipped with the image — do not require phone-home.

---

## 5. Soft UI (spike)

Info / About shows fingerprint + registry status caption. Status `mismatch` / `invalid_sig` → quiet caption note. Never `st.error` refuse; never change unofficial-origin (Layer B) logic; never block `app.py` / `main.py` startup.

---

## 6. Explicit non-goals (this chapter and Layer C honesty)

- Cosign/Sigstore in production CI (this chapter)
- Refusing app start / indelible watermark (this chapter)
- Cloud portal for issuing tokens
- Live Miniserver HTTP serial scrape as a hard dependency
- Phone-home, Cython/Nuitka kill switches
- Blocking or claiming control over source forks
- LICENSE / commercial-exception rewrite

Layer A/B remain **tamper-resistant, not tamper-proof**. Layer C enforces attribution on *official* distribution only.

---

## 7. Deferred follow-up

**Layer C enforcement:** cosign in CI + startup verifier + production signing keys + watermark vs refuse decision. Tracked under backlog `2.+1` after archiving 2.4.i.
