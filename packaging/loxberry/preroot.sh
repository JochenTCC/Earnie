#!/bin/bash
# preroot.sh — runs as ROOT before plugin folder replace (upgrade).

systemctl stop earnie 2>/dev/null || true
exit 0
