#!/bin/sh
set -e
. /app/docker/preflight.sh
run_preflight "$(uname -m)" "${EARNIE_CPUINFO_FILE:-/proc/cpuinfo}" \
    "${EARNIE_CPU_CHECK_DOCS_URL:-https://github.com/JochenTCC/Earnie/blob/main/docs/einrichtung/container.md#cpu-voraussetzung-amd64}" \
    || exit 1
python -m scripts.bootstrap_runtime
exec "$@"
