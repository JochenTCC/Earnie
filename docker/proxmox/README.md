# Proxmox LXC — Docker-in-LXC

Artifacts for running Earnie in an unprivileged Proxmox LXC with Docker Compose.

| File | Purpose |
|------|---------|
| `lxc.conf.example` | Example CT settings (`nesting=1`, `keyctl=1`, resources) |
| `bootstrap.sh` | Inside CT: install Docker, pull compose, `up -d` |
| `../compose/proxmox.yml` | Production Compose (same layout as Synology) |

User guide (German): [`docs/einrichtung/proxmox-lxc.md`](../../docs/einrichtung/proxmox-lxc.md)
