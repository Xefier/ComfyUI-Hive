#!/usr/bin/env bash

# Puts the rig back as it was: no ComfyUI, page or download running, no firewall rules, watchdog running if it was
# before. Safe to run any number of times. h-run.sh runs it when stopped, h-guard.sh if h-run.sh is killed outright.
# Hive itself won't: for a custom miner it looks for h-stop.sh in /hive/miners/custom, not in this folder.

. "$(dirname "${BASH_SOURCE[0]}")/h-common.sh"

if [[ -f $CH_RUN_DIR/tail.pid ]]; then
    kill "$(< "$CH_RUN_DIR/tail.pid")" 2>/dev/null
    rm -f "$CH_RUN_DIR/tail.pid"
fi

# The page first: it may be downloading, and a download stopped mid-file resumes on the next start
if [[ -f $CH_RUN_DIR/page.pid ]]; then
    ch_stop_group "$(< "$CH_RUN_DIR/page.pid")" 10
    rm -f "$CH_RUN_DIR/page.pid"
fi
if [[ -f $CH_RUN_DIR/server.pid ]]; then
    ch_stop_group "$(< "$CH_RUN_DIR/server.pid")" 15
    rm -f "$CH_RUN_DIR/server.pid"
fi
# ComfyUI, the page, and the install (uv, the venv's python), and only ours: the match is on this miner's own paths
pkill -KILL -f "$CH_VENV/bin/python" 2>/dev/null
pkill -KILL -f "$CH_DIR/page.py" 2>/dev/null
pkill -KILL -f "^$CH_UV " 2>/dev/null

ch_remove_firewall
rm -f "$CH_RUN_DIR/address" "$CH_RUN_DIR/page.json"

if [[ -f $CH_RUN_DIR/watchdog-stopped ]]; then
    systemctl start "$CH_WATCHDOG" && echo "Hive watchdog started"
    rm -f "$CH_RUN_DIR/watchdog-stopped"
fi

ch_set_state stopped
