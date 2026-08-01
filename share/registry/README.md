# Hardware registry entitlement (2.4.q first approach)

JSON Schema: [`entitlement.schema.json`](entitlement.schema.json).

**Official verify:** Ed25519 with bundled public key
[`earnie_registry_pubkey.pem`](earnie_registry_pubkey.pem).

**Issue (operator only):** PKCS8 private key via
`EARNIE_REGISTRY_PRIVATE_KEY_PATH` — never commit the private key; store it
offline / in a password manager. See Earnie-Projekt
`Entwicklungsplan/Hardware-Registry-Ausstellung.md`.

**Local/test fallback:** HMAC with `EARNIE_REGISTRY_DEV_SECRET` and
`--hmac` on the issuer script. Example file
[`examples/dev_entitlement.json`](examples/dev_entitlement.json) uses secret
`example-dev-secret` and the empty-parts fingerprint.

See [`docs/spec/hardware-registry-layer-c.md`](../../docs/spec/hardware-registry-layer-c.md).
