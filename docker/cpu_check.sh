# Sourced by docker/entrypoint.sh (all container targets incl. HA add-on).
#
# NumPy >= 2.4 and pyarrow x86 wheels need x86-64-v2 (SSE4.2, POPCNT, ...).
# Without it Python dies with a NumPy RuntimeError or SIGILL deep in an import
# (dump 20260925: HA OS VM with Proxmox CPU type kvm64). Fail early
# with an actionable message instead. /proc/cpuinfo shows the (VM) CPU the
# container really runs on.
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
