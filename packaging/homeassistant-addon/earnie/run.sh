#!/bin/sh
# Earnie HA-Add-on Entrypoint.
#
# Liest /data/options.json (Supervisor-Standardpfad für Add-on-Optionen) per
# jq, exportiert die passenden EARNIE_*-Env-Variablen und übergibt danach an
# den bestehenden App-Entrypoint (docker/entrypoint.sh -> bootstrap_runtime ->
# Streamlit). Dateibasierte Konfiguration (config.json unter
# /data/earnie_env/config) funktioniert davon unabhängig weiter.
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

# Standard-Add-on-Konvention: eigenes Volume unter /data statt /config
# (siehe Entwicklungsplan-Doku, Persistenz-Korrektur ggü. Erstentwurf).
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

# ehal_loxone_http_port Option: bootstrap merges it into config.json
# system.ehal_loxone_http_port (runtime_store/addon_options.py). Env-Hook
# bleibt Phase-2-Backlog.

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
