#!/usr/bin/env bash

# Runs ComfyUI and the chat page (page.py) in the foreground of Hive's miner screen, so switching flight sheet starts
# and stops them. Nothing here installs a system service: with another flight sheet active, nothing of it is running or
# holds GPU memory. No model is downloaded here: only the page does that, when someone asks for a model on it.

cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1
. ./h-common.sh
. ./h-log.sh

mkdir -p "$CUSTOM_LOG_BASEDIR" "$CH_RUN_DIR"
touch "$LOG_FILE"

on_stop() {
    trap '' INT TERM HUP
    log "Stopping"
    rm -f "$CH_RUN_DIR/run.pid"
    bash ./h-stop.sh 2>&1 | tee -a "$LOG_FILE"
    exit 0
}
trap on_stop INT TERM HUP

# A previous run that died without cleaning up
if [[ -f $CH_RUN_DIR/guard.pid ]]; then
    kill "$(< "$CH_RUN_DIR/guard.pid")" 2>/dev/null
    rm -f "$CH_RUN_DIR/guard.pid"
fi
bash ./h-stop.sh >> "$LOG_FILE" 2>&1

echo "$$" > "$CH_RUN_DIR/run.pid"
date +%s > "$CH_RUN_DIR/started"
ch_set_state starting
setsid bash ./h-guard.sh "$$" </dev/null >/dev/null 2>&1 &
echo "$!" > "$CH_RUN_DIR/guard.pid"

# Waits until the rig is safe to use instead of exiting: Hive would only start this again
wait_for_blocker() {
    local reported=""
    local blocker
    while true; do
        blocker=$("$@")
        [[ -z $blocker ]] && return 0
        if [[ $blocker != "$reported" ]]; then
            notify warn "$blocker"
            reported=$blocker
        fi
        ch_set_state waiting
        pause 30
    done
}

find_settings_problem() {
    # The models are far too big for the OS drive: without the DOCKER drive, wait rather than fill it
    if [[ $CH_DATA_DIR == "$CH_DEFAULT_DATA_DIR" ]] && ! mountpoint -q "${COMFYUI_HIVE_TEST_ROOT:-}/var/lib/docker" 2>/dev/null; then
        echo "Waiting: no drive is mounted at /var/lib/docker, where the models go. Mount the DOCKER drive, or set data_dir=<folder on a big drive>"
        return
    fi
    [[ -n $(ch_lan_address) ]] || { echo "No private LAN address found: set bind=<address> in the flight sheet"; return; }
    command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L 2>/dev/null | grep -q '^GPU' \
        || echo "No NVIDIA GPU found: this miner only supports NVIDIA"
}

# Never takes a GPU from a rental. A rented container can be idle, so running containers count as well as GPU processes.
find_gpu_user() {
    local apps containers
    apps=$(nvidia-smi --query-compute-apps=pid,process_name --format=csv,noheader 2>/dev/null)
    if [[ -n $apps ]]; then
        echo "Waiting: the GPU is in use by: ${apps//$'\n'/; }"
        return
    fi
    if [[ $CH_ALLOW_DOCKER != 1 ]] && command -v docker >/dev/null 2>&1; then
        containers=$(docker ps --format '{{.Names}}' 2>/dev/null)
        if [[ -n $containers ]]; then
            echo "Waiting: Docker containers are running (possibly a rental): ${containers//$'\n'/, }. If they are safe to share with, set allow_docker=1"
        fi
    fi
}

# Mining limits slow generation and can make it unstable. Hive applies these from the OC profile, not the flight sheet.
check_gpu_tuning() {
    if [[ $CH_RESET_OC == 1 ]]; then
        log "Resetting GPU clock locks and power limits (reset_oc=1)"
        nvidia-smi -rgc >> "$LOG_FILE" 2>&1
        nvidia-smi -rmc >> "$LOG_FILE" 2>&1
        nvidia-smi --query-gpu=index,power.default_limit --format=csv,noheader,nounits 2>/dev/null |
            while IFS=', ' read -r index limit; do
                nvidia-smi -i "$index" -pl "$limit" >> "$LOG_FILE" 2>&1
            done
        return
    fi
    nvidia-smi --query-gpu=index,power.limit,power.default_limit --format=csv,noheader,nounits 2>/dev/null |
        while IFS=', ' read -r index limit default; do
            if [[ ${limit%.*} -lt ${default%.*} ]]; then
                log "GPU $index power is limited to ${limit} W of ${default} W: remove the OC profile or set reset_oc=1"
            fi
        done
}

# Reading the rules back counts: on some Hive kernels iptables adds a chain it can't then read ("is incompatible")
apply_firewall() {
    local command=$1 allow=$2 cidr port
    "$command" -N "$CH_CHAIN" 2>/dev/null
    "$command" -F "$CH_CHAIN" || return 1
    "$command" -A "$CH_CHAIN" -i lo -j ACCEPT || return 1
    for cidr in $allow; do
        "$command" -A "$CH_CHAIN" -s "$cidr" -j ACCEPT || return 1
    done
    "$command" -A "$CH_CHAIN" -j DROP || return 1
    for port in "$CH_PORT" "$CH_PAGE_PORT"; do
        "$command" -I INPUT -p tcp --dport "$port" -j "$CH_CHAIN" || return 1
    done
    "$command" -S "$CH_CHAIN" >/dev/null || return 1
    for port in "$CH_PORT" "$CH_PAGE_PORT"; do
        "$command" -C INPUT -p tcp --dport "$port" -j "$CH_CHAIN" || return 1
    done
}

# A second layer: ComfyUI and the page only listen on the private address anyway, so a default setup still runs without
# working firewall rules. An explicit allow= is a limit that was asked for, so without rules to enforce it nothing starts.
open_firewall() {
    local allow=${CH_ALLOW//,/ }
    if [[ -z $allow ]]; then
        allow=$(ip -o -4 route show scope link 2>/dev/null |
            awk '$3 !~ /^(docker|br-|veth|virbr)/ && $1 ~ /\// {print $1}' | tr '\n' ' ')
    fi

    local command
    if [[ -n ${allow// /} ]]; then
        for command in iptables iptables-legacy; do
            command -v "$command" >/dev/null 2>&1 || continue
            if apply_firewall "$command" "$allow" >> "$LOG_FILE" 2>&1; then
                log "Firewall set with $command: ports $CH_PORT and $CH_PAGE_PORT are open to: $allow"
                return 0
            fi
            log "$command could not set the firewall rules"
            ch_remove_firewall
        done
    fi

    if [[ -n $CH_ALLOW ]]; then
        log "allow=$CH_ALLOW can't be enforced on this rig without working firewall rules"
        return 1
    fi
    notify warn "No working firewall on this rig: anything on the LAN can reach ports $CH_PORT and $CH_PAGE_PORT"
    return 0
}

# The watchdog's low hashrate, minimum power and load checks all mean something else here: an idle GPU is not a failed
# miner. h-stop.sh starts it again, and only if it was running.
stop_watchdog() {
    if systemctl is-active --quiet "$CH_WATCHDOG"; then
        touch "$CH_RUN_DIR/watchdog-stopped"
        systemctl stop "$CH_WATCHDOG"
        log "Hive watchdog stopped"
    fi
}

free_space() {
    df -h --output=avail "$CH_DATA_DIR" 2>/dev/null | tail -n 1 | tr -d ' '
}

# uv installs Python and the packages, all under the data folder: nothing goes into the system
install_uv() {
    mkdir -p "$CH_TOOLS_DIR/bin"
    export UV_CACHE_DIR="$CH_TOOLS_DIR/uv-cache"
    export UV_PYTHON_INSTALL_DIR="$CH_TOOLS_DIR/python"
    [[ -x $CH_UV ]] && return 0
    log "Downloading uv, which installs Python and the packages"
    ( curl -fsSL --retry 3 https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-unknown-linux-gnu.tar.gz |
        tar -xz --strip-components=1 -C "$CH_TOOLS_DIR/bin" ) &
    wait $!
}

# Python first, on its own: the page runs on it (standard library only) while the rest installs
install_python() {
    install_uv || return 1
    [[ -x $CH_VENV/bin/python ]] && return 0
    log "Installing Python 3.12"
    "$CH_UV" venv --python 3.12 "$CH_VENV" >> "$LOG_FILE" 2>&1 &
    wait $!
}

# ComfyUI at CH_COMFYUI_VERSION, PyTorch from CH_TORCH_INDEX, and ComfyUI's packages. Done again only when one of
# those changes.
install_comfyui() {
    local stamp="$CH_VENV/.installed"
    local wanted="$CH_COMFYUI_VERSION $CH_TORCH_INDEX"
    [[ -f $stamp && $(< "$stamp") == "$wanted" && -f $CH_COMFYUI/main.py ]] && return 0

    ch_set_state installing
    log "Installing ComfyUI $CH_COMFYUI_VERSION, PyTorch ($CH_TORCH_INDEX) and their packages, about 8 GB. Free space: $(free_space)"
    local download="$CH_DATA_DIR/comfyui-download"
    rm -rf "$download"
    mkdir -p "$download"
    ( curl -fsSL --retry 3 "https://github.com/comfyanonymous/ComfyUI/archive/refs/tags/$CH_COMFYUI_VERSION.tar.gz" |
        tar -xz --strip-components=1 -C "$download" ) &
    wait $! || { log "Could not download ComfyUI $CH_COMFYUI_VERSION"; return 1; }
    rm -rf "$CH_COMFYUI"
    mv "$download" "$CH_COMFYUI" || return 1

    "$CH_UV" pip install --python "$CH_VENV/bin/python" \
        --index-url "https://download.pytorch.org/whl/$CH_TORCH_INDEX" torch torchvision torchaudio >> "$LOG_FILE" 2>&1 &
    wait $! || return 1
    "$CH_UV" pip install --python "$CH_VENV/bin/python" -r "$CH_COMFYUI/requirements.txt" >> "$LOG_FILE" 2>&1 &
    wait $! || return 1
    "$CH_VENV/bin/python" -c 'import torch; print("PyTorch", torch.__version__, "CUDA", torch.cuda.is_available())' \
        >> "$LOG_FILE" 2>&1 || { log "PyTorch does not run on this system"; return 1; }
    echo "$wanted" > "$stamp"
}

# Where ComfyUI finds the models: one folder outside its own, so a new ComfyUI version keeps them
write_model_paths() {
    local folder
    {
        echo "comfyui_hive:"
        echo "    base_path: $CH_MODELS"
        echo "    is_default: true"
        for folder in checkpoints diffusion_models text_encoders vae loras clip_vision latent_upscale_models \
                      upscale_models model_patches embeddings audio_encoders controlnet; do
            echo "    $folder: $folder/"
            mkdir -p "$CH_MODELS/$folder"
        done
    } > "$CH_DATA_DIR/extra_model_paths.yaml"
}

page_running() {
    [[ -f $CH_RUN_DIR/page.pid ]] && kill -0 "$(< "$CH_RUN_DIR/page.pid")" 2>/dev/null
}

# The chat page. It keeps running while ComfyUI restarts, and is started again if it stops.
start_page() {
    page_running && return 0
    local address name
    address=$(ch_lan_address)
    # What the other rigs' pages call this one: the worker's name in Hive
    name=$(. /hive-config/rig.conf 2>/dev/null; echo "$WORKER_NAME")
    mkdir -p "$CH_PAGE_DATA" "$CH_OUTPUTS" "$CH_INPUTS" "$CH_MODELS"
    HF_TOKEN="$CH_HF_TOKEN" PYTHONUNBUFFERED=1 setsid "$CH_VENV/bin/python" "$CH_DIR/page.py" \
        --bind "$address" --port "$CH_PAGE_PORT" --comfy "http://$address:$CH_PORT" --gpu "$CH_GPUS" --allow-docker "$CH_ALLOW_DOCKER" \
        --catalog "$CH_DIR/catalog.json" --workflows "$CH_DIR/workflows" --models "$CH_MODELS" \
        --outputs "$CH_OUTPUTS" --inputs "$CH_INPUTS" --data "$CH_PAGE_DATA" \
        --state-file "$CH_RUN_DIR/state" --page-file "$CH_RUN_DIR/page.json" --log "$LOG_FILE" \
        --version "$CUSTOM_VERSION" --name "$name" --peers "$CH_PEERS" >> "$LOG_FILE" 2>&1 &
    echo "$!" > "$CH_RUN_DIR/page.pid"
    log "The page is at http://$address:$CH_PAGE_PORT/"
}

start_comfyui() {
    # Looked up on every start, in case the rig's DHCP lease changed its address
    local address
    address=$(ch_lan_address)
    [[ -n $address ]] || { log "No private LAN address found"; return 1; }
    echo "$address" > "$CH_RUN_DIR/address"
    CH_API="http://$address:$CH_PORT"
    log "ComfyUI listening on $address:$CH_PORT"

    export HOME="$CH_DATA_DIR/home"
    export CUDA_VISIBLE_DEVICES="$CH_GPUS"
    export PYTHONUNBUFFERED=1
    export HF_HUB_DISABLE_TELEMETRY=1
    mkdir -p "$HOME" "$CH_DATA_DIR/user" "$CH_DATA_DIR/temp"
    write_model_paths

    # Its own process group, so h-stop.sh ends everything it starts
    setsid "$CH_VENV/bin/python" "$CH_COMFYUI/main.py" --listen "$address" --port "$CH_PORT" \
        --extra-model-paths-config "$CH_DATA_DIR/extra_model_paths.yaml" \
        --output-directory "$CH_OUTPUTS" --input-directory "$CH_INPUTS" \
        --user-directory "$CH_DATA_DIR/user" --temp-directory "$CH_DATA_DIR/temp" \
        --disable-auto-launch >> "$LOG_FILE" 2>&1 &
    SERVER_PID=$!
    echo "$SERVER_PID" > "$CH_RUN_DIR/server.pid"

    local i
    for (( i = 0; i < 300; i++ )); do
        curl -fs --max-time 2 "$CH_API/system_stats" >/dev/null 2>&1 && return 0
        kill -0 "$SERVER_PID" 2>/dev/null || return 1
        pause 1
    done
    return 1
}

wait_for_blocker find_settings_problem
wait_for_blocker find_gpu_user

until open_firewall; do
    notify warn "Could not enforce allow=, retrying in 60 s."
    ch_set_state waiting
    pause 60
done

stop_watchdog

tail -n 0 -F "$LOG_FILE" 2>/dev/null &
echo "$!" > "$CH_RUN_DIR/tail.pid"

ch_set_state installing
until install_python; do
    notify warn "Could not install Python, retrying in 60 s. See the miner log."
    pause 60
done
start_page

until install_comfyui; do
    notify warn "Could not install ComfyUI, retrying in 60 s. See the miner log."
    ch_set_state waiting
    pause 60
done

check_gpu_tuning

while true; do
    ch_set_state starting
    start_page
    if start_comfyui; then
        ch_set_state ready
        notify info "ComfyUI is ready: the page is at http://$(ch_lan_address):$CH_PAGE_PORT/"
        # The page is started again if it stops
        while kill -0 "$SERVER_PID" 2>/dev/null; do
            start_page
            pause 15
        done
    fi
    kill -TERM -- "-$SERVER_PID" 2>/dev/null
    notify warn "ComfyUI stopped, restarting in 10 s. See the miner log."
    ch_set_state restarting
    pause 10
done
