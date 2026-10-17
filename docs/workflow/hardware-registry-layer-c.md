# Hardware registry & Banner Layer C

**Status:** Soft first approach shipped under **2.4.q** (Ed25519 entitlement verify; 2026-08-01). Spike **2.4.i** archived.  
**Related:** Banner A + light B (`ui/truth_banner.py`); Entwicklungsplan §6 (hardware lock).

This document describes how a user obtains a one-time registry bound to hardware, and what remains deferred for full Layer C. Enforcement (signed GHCR builds, refuse-to-start / watermark) stays under backlog **`2.+1`**.

---

## 1. User flow — one-time registry

1. User runs Earnie (GHCR image or local install) and opens **Info / About**, or runs:

   ```text
   python -m scripts.print_hardware_fingerprint
   ```

2. They see the **full 64-char hardware fingerprint** (copyable in Info / About; short form may appear in captions) derived from southbound system ID(s) + host machine id.

3. User sends that fingerprint once (**Registry per E-Mail anfordern** mailto, or general contact) and receives an entitlement file `earnie_registry.json` bound to that fingerprint.

4. User places the file in the env runtime directory (default name `earnie_registry.json`), or sets `EARNIE_REGISTRY_PATH`.

5. Soft checker reports `unbound` | `valid` | `mismatch` | `invalid_sig`. **Unbound remains valid private use** — no start block.

6. **Future Layer C only:** official sealed images may require a valid entitlement *or* show an indelible watermark. Source forks stay unsupported; we do not claim forks keep the banner.

**End-user how-to (German):** [`docs/user-manual/Benutzer-Handbuch-Earnie.md`](../user-manual/Benutzer-Handbuch-Earnie.md) § Hardware-Registry.  
**Issuer procedure (generation):** Earnie-Projekt `Entwicklungsplan/Hardware-Registry-Ausstellung.md`.

---

## 2. Fingerprint composition

Canonical parts (omit empty values):

| Key | Source |
|-----|--------|
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

## 3. Entitlement JSON (2.4.q first approach)

Schema: `share/registry/entitlement.schema.json`.

| Field | Meaning |
|-------|---------|
| `fingerprint` | Full SHA-256 hex of bound hardware |
| `issued_at` | ISO-8601 UTC |
| `expires_at` | ISO-8601 UTC or `null` (one-time forever) |
| `issuer` | e.g. `earnie` |
| `sig_alg` | official: `ed25519`; local/test fallback: `hmac-sha256` |
| `sig` | Hex signature over canonical payload |

**Signing payload (UTF-8, no trailing newline):**

```text
fingerprint={fp}\nissued_at={…}\nexpires_at={null|iso}\nissuer={…}\nsig_alg=ed25519
```

**Official path:** issue with Ed25519 private key (`EARNIE_REGISTRY_PRIVATE_KEY_PATH`, operator-only — never in git/image). Verify with bundled public key `share/registry/earnie_registry_pubkey.pem` (override: `EARNIE_REGISTRY_PUBLIC_KEY_PATH`).

**Local/test fallback:** HMAC with `EARNIE_REGISTRY_DEV_SECRET` and issuer `--hmac`. Not for customer hand-outs.

Issuer script: `python -m scripts.issue_dev_registry_token --fingerprint … --out path`.

Loader / soft status: `runtime_store/registry_entitlement.py` → `registry_status()`.

---

## 4. Technical prerequisites (Layer C later)

| Layer | Prerequisite | After 2.4.q |
|-------|--------------|-------------|
| Identity | Stable southbound IDs + host fallback | Soft helper |
| Entitlement | Signed JSON + issuer key | **Ed25519** + bundled pubkey; HMAC test fallback |
| Distribution | GHCR attestation (cosign/Sigstore); `permissions: id-token: write` + `packages: write` on `.github/workflows/release.yml` | Documented only — **release.yml unchanged** |
| Verifier | Check image attestation + entitlement; refuse **or** indelible watermark | Soft UI status only |
| Offline / air-gap | Bundled public key; no phone-home for entitlement verify | **Public key bundled**; Cosign still deferred |
| Policy | LICENSE §2 commercial exceptions stay manual | Non-goal |

### GHCR attestation outline (not wired)

After multi-arch push in release workflow:

1. Add `id-token: write` to job permissions.
2. Install cosign; `cosign attest` / `cosign sign` the pushed digests (`ghcr.io/jochentcc/earnie-energy:<version>`).
3. Future verifier inside official image: resolve own image digest, verify attestation against project identity; combine with entitlement check.
4. Air-gapped official installs need the public key (or offline attestation blob) shipped with the image — do not require phone-home.

---

## 5. Soft UI (2.4.q)

Info / About shows full copyable fingerprint, registry status caption (`unbound` / `valid`→bound / `mismatch` / `invalid_sig`), dedicated registry mailto, and a mild warning on `mismatch` / `invalid_sig`. The attribution caption (Banner der Wahrheit) appends a short registry suffix and is colored green when `valid`, red otherwise. Never refuse-to-start; never change unofficial-origin (Layer B) logic; never block `app.py` / `main.py` startup.

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

**Layer C enforcement:** cosign in CI + startup verifier + watermark vs refuse decision. Tracked under backlog `2.+1`.
