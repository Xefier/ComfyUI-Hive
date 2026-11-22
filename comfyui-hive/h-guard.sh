#!/usr/bin/env bash

# Runs beside h-run.sh in its own session, so it survives h-run.sh being killed outright. Without it, a hard kill would
# leave ComfyUI holding the GPU under the next flight sheet (a rental, say). It also keeps the Hive
# watchdog stopped and disabled, in case something in Hive starts or enables it again.

. "$(dirname "${BASH_SOURCE[0]}")/h-common.sh"

run_pid=$1
ch_dir="$(dirname "${BASH_SOURCE[0]}")"

while kill -0 "$run_pid" 2>/dev/null; do
    systemctl is-active --quiet "$CH_WATCHDOG" && systemctl stop "$CH_WATCHDOG"
    [[ $(systemctl is-enabled "$CH_WATCHDOG" 2>/dev/null) == enabled ]] && systemctl disable "$CH_WATCHDOG"
    sleep 15
done

# h-run.sh removes run.pid when it stops properly, and a new run replaces it: both have cleaned up already
[[ -f $CH_RUN_DIR/run.pid && $(< "$CH_RUN_DIR/run.pid") == "$run_pid" ]] || exit 0
rm -f "$CH_RUN_DIR/run.pid" "$CH_RUN_DIR/guard.pid"
bash "$ch_dir/h-stop.sh"
