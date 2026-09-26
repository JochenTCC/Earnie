#!/bin/sh
# Earnie HA-Add-on Entrypoint.
#
# Liest /data/options.json (Supervisor-Standardpfad für Add-on-Optionen) per
# jq, exportiert die passenden EARNIE_*-Env-Variablen und übergibt danach an
# den bestehenden App-Entrypoint (docker/entrypoint.sh -> bootstrap_runtime ->
# Streamlit). Config liegt unter /config (addon_config); Runtime unter
# /data/earnie_env/runtime.
#
# Ingress: nginx listens on 8501 (ingress_port + optional host port) and
# re-attaches Supervisor ingress_entry before proxying to Streamlit on :8502
# with --server.baseUrlPath. Without that rewrite, HA path-stripping makes
# Streamlit answer "Not found" for both Ingress and bare :8501.
set -e

OPTIONS_FILE=/data/options.json
NGINX_TEMPLATE=/etc/earnie-addon/nginx/ingress.conf.template
NGINX_CONF=/tmp/earnie-ingress-nginx.conf
STREAMLIT_INTERNAL_PORT=8502
OLD_CONFIG_DIR=/data/earnie_env/config
NEW_CONFIG_DIR=/config
RUNTIME_DIR=/data/earnie_env/runtime

# $1 = jq-Filter (z. B. '.timezone'), $2 = Default, falls Option fehlt/leer/null.
# Kein "// empty" hier: jq behandelt JSON false wie null/fehlend (Alternative-
# Operator), das würde z. B. auto_start_main=false stillschweigend ignorieren.
_opt() {
    value=""
    if [ -f "$OPTIONS_FILE" ]; then
        value="$(jq -r "${1}" "$OPTIONS_FILE" 2>/dev/null || true)"
    fi
    if [ -z "$value" ] || [ "$value" = "null" ]; then
        printf '%s' "$2"
    else
        printf '%s' "$value"
    fi
}

# One-time migrate: copy /data/earnie_env/config → /config, keep old dir renamed.
_migrate_config_to_addon_config() {
    if [ -f "$NEW_CONFIG_DIR/config.json" ]; then
        return 0
    fi
    if [ ! -f "$OLD_CONFIG_DIR/config.json" ]; then
        return 0
    fi
    echo "earnie-addon: migriere Konfiguration von ${OLD_CONFIG_DIR} nach ${NEW_CONFIG_DIR}"
    mkdir -p "$NEW_CONFIG_DIR"
    if ! cp -a "$OLD_CONFIG_DIR/." "$NEW_CONFIG_DIR/"; then
        echo "earnie-addon: FEHLER — Kopieren nach ${NEW_CONFIG_DIR} fehlgeschlagen; alter Ordner unverändert." >&2
        exit 1
    fi
    if [ ! -f "$NEW_CONFIG_DIR/config.json" ]; then
        echo "earnie-addon: FEHLER — Migration unvollständig (kein config.json in ${NEW_CONFIG_DIR})." >&2
        exit 1
    fi
    stamp="$(date +%Y%m%d)"
    migrated="${OLD_CONFIG_DIR}.migrated-${stamp}"
    if ! mv "$OLD_CONFIG_DIR" "$migrated"; then
        echo "earnie-addon: FEHLER — Umbenennen von ${OLD_CONFIG_DIR} fehlgeschlagen." >&2
        exit 1
    fi
    echo "earnie-addon: Konfiguration nach /config migriert (Altordner: ${migrated})"
}

# Abort if the sibling channel add-on is already running (same devices).
_guard_sibling_not_running() {
    token="$(printf '%s' "${SUPERVISOR_TOKEN:-}" | tr -d '[:space:]')"
    if [ -z "$token" ]; then
        return 0
    fi
    self_slug="$(python - <<'PY'
import json
import os
import urllib.error
import urllib.request

token = (os.environ.get("SUPERVISOR_TOKEN") or "").strip()
if not token:
    raise SystemExit(0)
request = urllib.request.Request(
    "http://supervisor/addons/self/info",
    headers={"Authorization": f"Bearer {token}"},
    method="GET",
)
try:
    with urllib.request.urlopen(request, timeout=3.0) as response:
        payload = json.loads(response.read().decode("utf-8"))
except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
    raise SystemExit(0)
data = payload.get("data") if isinstance(payload, dict) else None
if not isinstance(data, dict):
    raise SystemExit(0)
slug = str(data.get("slug") or "").strip()
if slug:
    print(slug)
PY
)"
    if [ -z "$self_slug" ]; then
        return 0
    fi
    case "$self_slug" in
        earnie_prerelease) sibling="earnie" ;;
        *_earnie_prerelease) sibling="${self_slug%_earnie_prerelease}_earnie" ;;
        earnie) sibling="earnie_prerelease" ;;
        *_earnie) sibling="${self_slug%_earnie}_earnie_prerelease" ;;
        *) return 0 ;;
    esac
    state="$(OTHER_SLUG="$sibling" python - <<'PY'
import json
import os
import urllib.error
import urllib.request

token = (os.environ.get("SUPERVISOR_TOKEN") or "").strip()
slug = (os.environ.get("OTHER_SLUG") or "").strip()
if not token or not slug:
    raise SystemExit(0)
request = urllib.request.Request(
    f"http://supervisor/addons/{slug}/info",
    headers={"Authorization": f"Bearer {token}"},
    method="GET",
)
try:
    with urllib.request.urlopen(request, timeout=3.0) as response:
        payload = json.loads(response.read().decode("utf-8"))
except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
    raise SystemExit(0)
data = payload.get("data") if isinstance(payload, dict) else None
if not isinstance(data, dict):
    raise SystemExit(0)
print(str(data.get("state") or "").strip())
PY
)"
    if [ "$state" = "started" ]; then
        echo "earnie-addon: FEHLER — Add-on '${sibling}' läuft bereits. Nie beide Kanäle gleichzeitig starten (gleiche Geräte). Bitte das andere Add-on stoppen." >&2
        exit 1
    fi
}

# x86-64-v2 preflight runs in docker/entrypoint.sh (docker/cpu_check.sh); point
# its error hint at the add-on docs instead of the generic container docs.
export EARNIE_CPU_CHECK_DOCS_URL="https://github.com/JochenTCC/Earnie/blob/main/docs/einrichtung/homeassistant-addon.md#voraussetzungen-gono-go"

_migrate_config_to_addon_config
mkdir -p "$RUNTIME_DIR"

# Config: Supervisor addon_config → /config. Runtime stays on /data.
export EARNIE_CONFIG_PATH="$NEW_CONFIG_DIR"
export EARNIE_RUNTIME_PATH="$RUNTIME_DIR"
# Keep ENV_PATH for any code that still joins under earnie_env (runtime parent).
export EARNIE_ENV_PATH=/data/earnie_env
export TZ="$(_opt '.timezone' 'Europe/Vienna')"

# Host/option streamlit_port is the published UI port (nginx). Streamlit itself
# always listens internally on STREAMLIT_INTERNAL_PORT behind nginx.
export EARNIE_UI_STREAMLIT_PORT="$STREAMLIT_INTERNAL_PORT"
export EARNIE_UI_MODES="$(_opt '.ui_modes' 'sunset2sunset,scenario_explorer,live_environment')"

# Narrows the Smarthome-Backend page's targeted scan to Home Assistant itself
# (see runtime_store/install_context.py). SUPERVISOR_TOKEN is injected by the
# Supervisor when homeassistant_api: true (config.yaml).
export EARNIE_INSTALL_CONTEXT=homeassistant_addon

AUTO_START_MAIN="$(_opt '.auto_start_main' 'true')"
if [ "$AUTO_START_MAIN" = "false" ]; then
    export EARNIE_AUTO_START_MAIN=0
else
    export EARNIE_AUTO_START_MAIN=1
fi

# ehal_loxone_http_port: export for runtime env precedence (config.get_ehal_loxone_http_port)
# and merge into config.json system.ehal_loxone_http_port (runtime_store/addon_options.py).
export EARNIE_EHAL_LOXONE_HTTP_PORT="$(_opt '.ehal_loxone_http_port' '8541')"

# Mutual exclusion vs. the other channel (derived from self slug via Supervisor).
_guard_sibling_not_running

cd /app

# Resolve Ingress entry (e.g. /api/hassio_ingress/<token>) for Streamlit baseUrlPath
# and nginx rewrite. Empty → fall back to Streamlit directly on 8501 (no nginx).
INGRESS_ENTRY="$(python - <<'PY'
import json
import os
import urllib.error
import urllib.request

token = (os.environ.get("SUPERVISOR_TOKEN") or "").strip()
if not token:
    raise SystemExit(0)
request = urllib.request.Request(
    "http://supervisor/addons/self/info",
    headers={"Authorization": f"Bearer {token}"},
    method="GET",
)
try:
    with urllib.request.urlopen(request, timeout=3.0) as response:
        payload = json.loads(response.read().decode("utf-8"))
except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
    raise SystemExit(0)
data = payload.get("data") if isinstance(payload, dict) else None
if not isinstance(data, dict):
    raise SystemExit(0)
entry = str(data.get("ingress_entry") or "").strip()
if entry:
    print(entry)
PY
)"

if [ -n "$INGRESS_ENTRY" ] && [ -f "$NGINX_TEMPLATE" ]; then
    # Streamlit wants baseUrlPath without a leading slash.
    export EARNIE_STREAMLIT_BASE_URL_PATH="${INGRESS_ENTRY#/}"
    # Render nginx conf via Python (avoid sed: a prior broken escape expression
    # caused GNU sed "unterminated s' command" and aborted start under set -e;
    # see debug-dumps HA log 20b22c55_…).
    INGRESS_ENTRY="$INGRESS_ENTRY" NGINX_TEMPLATE="$NGINX_TEMPLATE" NGINX_CONF="$NGINX_CONF" python - <<'PY'
import os
from pathlib import Path

template = Path(os.environ["NGINX_TEMPLATE"])
out = Path(os.environ["NGINX_CONF"])
entry = os.environ["INGRESS_ENTRY"]
text = template.read_text(encoding="utf-8")
if "__INGRESS_ENTRY__" not in text:
    raise SystemExit("nginx template missing __INGRESS_ENTRY__ placeholder")
out.write_text(text.replace("__INGRESS_ENTRY__", entry), encoding="utf-8")
PY
    nginx -c "$NGINX_CONF"
    echo "earnie-addon: nginx Ingress proxy on :8501 → Streamlit :${STREAMLIT_INTERNAL_PORT} (baseUrlPath=${EARNIE_STREAMLIT_BASE_URL_PATH})"
else
    # No Ingress entry yet — expose Streamlit on the published port directly.
    export EARNIE_UI_STREAMLIT_PORT=8501
    unset EARNIE_STREAMLIT_BASE_URL_PATH || true
    echo "earnie-addon: no ingress_entry — Streamlit directly on :8501"
fi

exec /bin/sh docker/entrypoint.sh python -m scripts.run_streamlit -- \
    --server.enableCORS false \
    --server.enableXsrfProtection false
