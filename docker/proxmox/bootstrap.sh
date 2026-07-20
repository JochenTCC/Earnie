#!/usr/bin/env bash
# Bootstrap Earnie inside a Proxmox LXC (Docker Compose).
# Run as root inside the CT after nesting=1,keyctl=1 are set.
# See docs/einrichtung/proxmox-lxc.md
set -euo pipefail

EARNIE_DIR="${EARNIE_DIR:-/opt/earnie}"
COMPOSE_URL="${COMPOSE_URL:-https://raw.githubusercontent.com/JochenTCC/Earnie/main/docker/compose/proxmox_productive.yml}"
IMAGE="${IMAGE:-ghcr.io/jochentcc/earnie-energy:latest}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root inside the LXC." >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive

echo "==> Installing Docker (docker.io + compose plugin if available)"
apt-get update -y
apt-get install -y ca-certificates curl docker.io
apt-get install -y docker-compose-v2 2>/dev/null || apt-get install -y docker-compose 2>/dev/null || true
systemctl enable --now docker

if ! docker info >/dev/null 2>&1; then
  echo "Docker is not usable. Check LXC features nesting=1,keyctl=1 and reboot the CT." >&2
  exit 1
fi

echo "==> Preparing ${EARNIE_DIR}"
mkdir -p "${EARNIE_DIR}/config" "${EARNIE_DIR}/runtime"
cd "${EARNIE_DIR}"

if [[ ! -f compose.yaml ]]; then
  if [[ -f /tmp/proxmox_productive.yml ]]; then
    cp /tmp/proxmox_productive.yml compose.yaml
  elif [[ -f /tmp/proxmox.yml ]]; then
    cp /tmp/proxmox.yml compose.yaml
  else
    echo "==> Downloading compose from ${COMPOSE_URL}"
    curl -fsSL "${COMPOSE_URL}" -o compose.yaml
  fi
fi

echo "==> Pulling ${IMAGE} and starting stack"
docker compose --project-directory "${EARNIE_DIR}" -f compose.yaml pull
docker compose --project-directory "${EARNIE_DIR}" -f compose.yaml up -d

echo
echo "Earnie is starting."
echo "  Edit:  ${EARNIE_DIR}/config/.env and ${EARNIE_DIR}/config/config.json"
echo "  UI:    http://$(hostname -I 2>/dev/null | awk '{print $1}'):8501"
echo "  Logs:  docker compose -f ${EARNIE_DIR}/compose.yaml logs -f"
echo "  After config edits: docker compose -f ${EARNIE_DIR}/compose.yaml restart earnie-productive"
