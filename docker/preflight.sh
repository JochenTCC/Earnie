# Sourced by docker/entrypoint.sh (all container targets incl. HA add-on).
#
# H0: NumPy >= 2.4 and pyarrow x86 wheels need x86-64-v2 (SSE4.2, POPCNT, ...).
# H1: writable config/runtime dirs; clock not before image BUILD_DATE (brief NTP wait);
#     warn on low RAM / free disk.
#
# $1 = arch (uname -m), $2 = cpuinfo path, $3 = docs URL for the hint.
_check_x86_64_v2() {
    [ "$1" = "x86_64" ] || return 0
    [ -r "$2" ] || return 0
    cpu_flags=" $(grep -m1 '^flags' "$2" | cut -d: -f2) "
    missing=""
    for flag in cx16 lahf_lm popcnt pni sse4_1 sse4_2 ssse3; do
        case "$cpu_flags" in
            *" $flag "*) ;;
            *) missing="$missing $flag" ;;
        esac
    done
    [ -z "$missing" ] && return 0
    cat >&2 <<EOF
earnie: FEHLER - die CPU unterstützt den Befehlssatz x86-64-v2 nicht (fehlt:${missing}).
earnie: Earnie braucht x86-64-v2 (NumPy, pyarrow). Meist läuft Earnie bzw. Home Assistant in einer VM
earnie: mit CPU-Typ "kvm64"/"qemu64". Proxmox: VM herunterfahren -> Hardware -> Prozessoren ->
earnie: Typ "host" (oder "x86-64-v2-AES") -> VM kalt neu starten (Neustart aus der VM heraus reicht nicht).
earnie: Details: $3
EOF
    return 1
}

_preflight_runtime_dir() {
    if [ -n "${EARNIE_RUNTIME_PATH:-}" ]; then
        printf '%s\n' "$EARNIE_RUNTIME_PATH"
    else
        printf '%s\n' "${EARNIE_ENV_PATH:-.}/runtime"
    fi
}

_preflight_config_dir() {
    if [ -n "${EARNIE_CONFIG_PATH:-}" ]; then
        case "$EARNIE_CONFIG_PATH" in
            */config.json) printf '%s\n' "${EARNIE_CONFIG_PATH%/config.json}" ;;
            *) printf '%s\n' "$EARNIE_CONFIG_PATH" ;;
        esac
    else
        printf '%s\n' "${EARNIE_ENV_PATH:-.}/config"
    fi
}

# Abort if config or runtime dir is missing / not writable.
_check_writable_data_dirs() {
    runtime_dir="$(_preflight_runtime_dir)"
    config_dir="$(_preflight_config_dir)"
    for dir in "$config_dir" "$runtime_dir"; do
        if ! mkdir -p "$dir" 2>/dev/null; then
            cat >&2 <<EOF
earnie: FEHLER - Datenverzeichnis nicht anlegbar: $dir
earnie: Prüfe Volume-/Bind-Mounts und Schreibrechte (Synology-Freigabe, LXC-UID, Add-on /config).
EOF
            return 1
        fi
        probe="$dir/.earnie_write_test"
        if ! touch "$probe" 2>/dev/null; then
            cat >&2 <<EOF
earnie: FEHLER - Datenverzeichnis nicht beschreibbar: $dir
earnie: Prüfe Volume-/Bind-Mounts und Schreibrechte (Synology-Freigabe, LXC-UID, Add-on /config).
EOF
            return 1
        fi
        rm -f "$probe"
    done
    return 0
}

# Parse ISO-8601 UTC (…Z or …+00:00) to Unix epoch via GNU date; empty → skip.
_build_date_epoch() {
    file="${EARNIE_BUILD_DATE_FILE:-/app/docker/BUILD_DATE}"
    [ -r "$file" ] || return 0
    raw="$(tr -d '[:space:]' <"$file")"
    [ -n "$raw" ] || return 0
    date -u -d "$raw" +%s 2>/dev/null || date -u -d "${raw%Z}" +%s 2>/dev/null || true
}

# Abort if system clock is before image build date (wait briefly for NTP).
_check_clock_vs_build_date() {
    build_epoch="$(_build_date_epoch)"
    [ -n "$build_epoch" ] || return 0
    max_wait="${EARNIE_PREFLIGHT_CLOCK_WAIT_SEC:-30}"
    waited=0
    while [ "$waited" -lt "$max_wait" ]; do
        now="$(date -u +%s)"
        if [ "$now" -ge "$build_epoch" ]; then
            return 0
        fi
        sleep 5
        waited=$((waited + 5))
    done
    now="$(date -u +%s)"
    if [ "$now" -ge "$build_epoch" ]; then
        return 0
    fi
    cat >&2 <<EOF
earnie: FEHLER - Systemuhr liegt vor dem Image-Build-Datum (Uhr=$now, Build=$build_epoch).
earnie: Warte kurz auf NTP (Raspberry Pi ohne RTC) oder stelle die Host-Uhr korrekt ein, dann Container neu starten.
EOF
    return 1
}

_warn_low_resources() {
    runtime_dir="$(_preflight_runtime_dir)"
    if [ -r /proc/meminfo ]; then
        mem_kb="$(awk '/^MemTotal:/ {print $2; exit}' /proc/meminfo)"
        if [ -n "$mem_kb" ] && [ "$mem_kb" -lt 2097152 ]; then
            echo "earnie: WARNUNG - weniger als 2 GB RAM (${mem_kb} kB). Empfohlen: mind. 2 GB, besser 4 GB." >&2
        fi
    fi
    if [ -d "$runtime_dir" ]; then
        avail_kb="$(df -k "$runtime_dir" 2>/dev/null | awk 'NR==2 {print $4}')"
        if [ -n "$avail_kb" ] && [ "$avail_kb" -lt 512000 ]; then
            echo "earnie: WARNUNG - weniger als 500 MB freier Speicher unter $runtime_dir (${avail_kb} kB frei)." >&2
        fi
    fi
}

# Run all H0/H1 checks. Args: arch, cpuinfo path, docs URL (same as _check_x86_64_v2).
run_preflight() {
    _check_x86_64_v2 "$1" "$2" "$3" || return 1
    _check_writable_data_dirs || return 1
    _check_clock_vs_build_date || return 1
    _warn_low_resources
    return 0
}
