#!/usr/bin/env bash

# Saying things and waiting, for h-run.sh after h-common.sh.
# Not in h-common.sh: Hive's own agent sources that with h-stats.sh, and names like these could meet its own.

# The miner log, which Hive shows
LOG_FILE="$CUSTOM_LOG_BASENAME.log"

log() {
    echo "[comfyui-hive] $(date '+%F %T') $*" | tee -a "$LOG_FILE"
}

# Shows on the Hive dashboard
notify() {
    log "$2"
    command -v message >/dev/null 2>&1 && message "$1" "comfyui-hive: $2" >/dev/null 2>&1
    # Whether the dashboard took it says nothing about what the caller was doing
    return 0
}

# Sleeps in a way a stop signal interrupts at once
pause() {
    sleep "$1" &
    wait $!
}
