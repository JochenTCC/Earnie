# LoxBerry plugin (Earnie) — packaging notes

Thin Docker wrapper for LoxBerry **4.x** (aarch64). Source tree: this folder (`packaging/loxberry/`).

Plugin SemVer (`plugin.cfg` `VERSION`) is **independent** of Earnie `version.py`. The compose file always uses `ghcr.io/jochentcc/earnie-energy:latest`. Refresh the image with Plugin Admin → **Image aktualisieren** or `sbin/earnie_ctl.sh pull`.

## Manual ZIP for Plugin Admin

From the repo root (Unix/macOS or Git Bash), package **only** this directory so `plugin.cfg` is at the ZIP root:

```bash
cd packaging/loxberry
zip -r ../../../earnie-loxberry-plugin-0.1.0.zip . \
  -x "*.git*" -x "*~" -x "*.DS_Store"
```

PowerShell (repo root):

```powershell
Compress-Archive -Path packaging\loxberry\* -DestinationPath earnie-loxberry-plugin-0.1.0.zip -Force
```

Install the ZIP under LoxBerry → Plugin Management → Install from ZIP.

## Version bump checklist

1. Bump `VERSION` in `plugin.cfg`, `release.cfg`, and `prerelease.cfg` to the same value.
2. Update `ARCHIVEURL` in `release.cfg` / `prerelease.cfg` to the new GitHub Release asset URL.
3. Rebuild the ZIP with the new version in the filename.
4. Publish a GitHub Release (e.g. tag `loxberry-plugin-v0.1.0`) and attach the ZIP asset named in `ARCHIVEURL`.
5. After the asset is live, AutoUpdate can pick up the new `VERSION` from `release.cfg` on `main`.

Until the first Release asset exists, use **manual ZIP** install only; `ARCHIVEURL` is a placeholder target.

## REPLACE tags

LoxBerry rewrites these in text files on install:

| Tag | Typical use |
|-----|-------------|
| `REPLACELBPDATADIR` | Compose volumes, systemd `WorkingDirectory`, ctl compose path |
| `REPLACELBPSBINDIR` | PHP `sudo …/earnie_ctl.sh` |

Do not hardcode `/opt/loxberry/...` paths in shipped files.

## Persistence / uninstall

- Runtime data: `$LBPDATA/earnie/earnie_env/{config,runtime}`
- `uninstall/uninstall.sh` stops/removes the container and systemd unit; it does **not** delete `earnie_env` or the GHCR image
- LoxBerry may still remove the plugin data directory on uninstall — copy `earnie_env` elsewhere first if you need a backup
