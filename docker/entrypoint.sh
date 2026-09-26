#!/bin/sh
set -e
. /app/docker/cpu_check.sh
_check_x86_64_v2 "$(uname -m)" "${EARNIE_CPUINFO_FILE:-/proc/cpuinfo}" \
    "${EARNIE_CPU_CHECK_DOCS_URL:-https://github.com/JochenTCC/Earnie/blob/main/docs/einrichtung/container.md#cpu-voraussetzung-amd64}" \
    || exit 1
python -m scripts.bootstrap_runtime
exec "$@"
