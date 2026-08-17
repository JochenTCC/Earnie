#!/bin/sh
# Earnie HA-Add-on Entrypoint.
#
# Liest /data/options.json (Supervisor-Standardpfad für Add-on-Optionen) per
# jq, exportiert die passenden EARNIE_*-Env-Variablen und übergibt danach an
# den bestehenden App-Entrypoint (docker/entrypoint.sh -> bootstrap_runtime ->
# Streamlit). Dateibasierte Konfiguration (config.json unter
# /data/earnie_env/config) funktioniert davon unabhängig weiter.
set -e

OPTIONS_FILE=/data/options.json

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

LOXONE_USER_OPT="$(_opt '.loxone_user' '')"
if [ -n "$LOXONE_USER_OPT" ]; then
    export LOXONE_USER="$LOXONE_USER_OPT"
fi

LOXONE_PASS_OPT="$(_opt '.loxone_pass' '')"
if [ -n "$LOXONE_PASS_OPT" ]; then
    export LOXONE_PASS="$LOXONE_PASS_OPT"
fi

LOXONE_IP_OPT="$(_opt '.loxone_ip' '')"
if [ -n "$LOXONE_IP_OPT" ]; then
    export LOXONE_IP="$LOXONE_IP_OPT"
fi

export EARNIE_UI_STREAMLIT_PORT="$(_opt '.streamlit_port' '8501')"
export EARNIE_UI_MODES="$(_opt '.ui_modes' 'sunset2sunset,scenario_explorer,live_environment')"

AUTO_START_MAIN="$(_opt '.auto_start_main' 'true')"
if [ "$AUTO_START_MAIN" = "false" ]; then
    export EARNIE_AUTO_START_MAIN=0
else
    export EARNIE_AUTO_START_MAIN=1
fi

# ehal_loxone_http_port ist als Option vorhanden (config.yaml), hat aber noch
# keinen Env-Hook im Hauptrepo (Default 8541 reicht für MVP 0.1, siehe
# Entwicklungsplan-Doku "Offene Punkte" #1). Nur config.json
# system.ehal_loxone_http_port wirkt aktuell.

cd /app
exec /bin/sh docker/entrypoint.sh python -m scripts.run_streamlit -- \
    --server.enableCORS false \
    --server.enableXsrfProtection false
