#!/usr/bin/env bash

# Shared by h-run.sh, h-stop.sh, h-guard.sh and h-stats.sh.

# Hive's miner screen doesn't always have the admin folders on its PATH
export PATH="$PATH:/usr/sbin:/sbin"

CH_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$CH_DIR/h-manifest.conf"

CH_RUN_DIR="${COMFYUI_HIVE_TEST_ROOT:-}/run/comfyui-hive"
CH_CHAIN="COMFYUI_HIVE"
CH_WATCHDOG="hive-watchdog"

# ComfyUI's own port (its editor and API); the chat page is on the next one
CH_PORT=8188
CH_ALLOW=""
CH_BIND=""
# Outside the miner folder: custom-get deletes that folder when a new version of this miner is installed. On the rigs'
# big DOCKER drive, since the models are tens of GB each and the OS drive is small. Only data_dir= puts it elsewhere.
CH_DATA_DIR=""
CH_GPUS=0
# cu128 needs NVIDIA driver 570 or newer, which an RTX 5090 needs anyway
CH_TORCH_INDEX=cu128
# The ComfyUI release installed. The workflows in workflows/ were made for it (tools/build.py)
CH_COMFYUI_VERSION=v0.45.0
CH_HF_TOKEN=""
CH_RESET_OC=0
CH_ALLOW_DOCKER=0

[[ -f $CUSTOM_CONFIG_FILENAME ]] && . "$CUSTOM_CONFIG_FILENAME"

CH_DEFAULT_DATA_DIR="${COMFYUI_HIVE_TEST_ROOT:-}/var/lib/docker/comfyui-hive"
[[ -n $CH_DATA_DIR ]] || CH_DATA_DIR=$CH_DEFAULT_DATA_DIR
CH_PAGE_PORT=$((CH_PORT + 1))
CH_TOOLS_DIR="$CH_DATA_DIR/tools"
CH_UV="$CH_TOOLS_DIR/bin/uv"
CH_VENV="$CH_DATA_DIR/venv"
CH_COMFYUI="$CH_DATA_DIR/comfyui"
CH_MODELS="$CH_DATA_DIR/models"
CH_OUTPUTS="$CH_DATA_DIR/outputs"
CH_INPUTS="$CH_DATA_DIR/inputs"
# The page's own records: jobs, downloads, the last model picked
CH_PAGE_DATA="$CH_DATA_DIR/page"

# The address h-run.sh is serving on. ComfyUI doesn't listen on 127.0.0.1 here, so this is how to reach it on the rig too.
CH_ADDRESS=$(cat "$CH_RUN_DIR/address" 2>/dev/null || echo 127.0.0.1)
CH_API="http://$CH_ADDRESS:$CH_PORT"

ch_is_private() {
    [[ $1 =~ ^(10\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[01])\.) ]]
}

# Where to listen: bind= from the flight sheet, or else this rig's private LAN address. Empty if it has none, because
# ComfyUI has no authentication and must never listen on a public address or on 0.0.0.0.
ch_lan_address() {
    if [[ -n $CH_BIND ]]; then
        echo "$CH_BIND"
        return
    fi
    local address
    address=$(ip -4 route get 1.1.1.1 2>/dev/null | grep -oP 'src \K[0-9.]+' | head -n 1)
    if ch_is_private "$address"; then
        echo "$address"
        return
    fi
    ip -o -4 addr show scope global 2>/dev/null |
        awk '$2 !~ /^(docker|br-|veth|virbr)/ { split($4, a, "/"); print a[1] }' |
        while read -r address; do
            if ch_is_private "$address"; then
                echo "$address"
                break
            fi
        done
}

ch_remove_firewall() {
    local command port i
    for command in iptables iptables-legacy; do
        command -v "$command" >/dev/null 2>&1 || continue
        for port in "$CH_PORT" "$CH_PAGE_PORT"; do
            for (( i = 0; i < 20; i++ )); do
                "$command" -D INPUT -p tcp --dport "$port" -j "$CH_CHAIN" 2>/dev/null || break
            done
        done
        "$command" -F "$CH_CHAIN" 2>/dev/null
        "$command" -X "$CH_CHAIN" 2>/dev/null
    done
    # iptables can create a chain on a kernel where it then can't read or delete it
    command -v nft >/dev/null 2>&1 && nft delete chain ip filter "$CH_CHAIN" 2>/dev/null
}

# Ends a process group this miner started with setsid: asks, waits up to $2 seconds, then kills what is left
ch_stop_group() {
    local pid=$1 seconds=${2:-10} i
    kill -TERM -- "-$pid" 2>/dev/null
    for (( i = 0; i < seconds; i++ )); do
        kill -0 "$pid" 2>/dev/null || break
        sleep 1
    done
    kill -KILL -- "-$pid" 2>/dev/null
}

ch_set_state() {
    mkdir -p "$CH_RUN_DIR"
    echo "$1" > "$CH_RUN_DIR/state"
}
