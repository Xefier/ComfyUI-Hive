#!/usr/bin/env bash

# Sourced by Hive's agent, which reads $khs and $stats. Must stay quick and must not exit.
# There is no hashrate. While a job runs the GPU reports the sampler's speed in steps per second (it/s), and 0
# otherwise; the algo field says what the rig is doing (comfyui ready, generating 12/20 wan2.2-14b t2v, downloading 42%
# ...), and accepted/rejected count the jobs done and failed since the miner started. page.py writes the numbers.

. "$(dirname "${BASH_SOURCE[0]}")/h-common.sh"

ch_gpu_stats="${GPU_STATS_JSON:-/run/hive/gpu-stats.json}"
ch_state=$(cat "$CH_RUN_DIR/state" 2>/dev/null)
ch_started=$(cat "$CH_RUN_DIR/started" 2>/dev/null)
ch_page=$(cat "$CH_RUN_DIR/page.json" 2>/dev/null)
[[ -n $ch_page ]] || ch_page='{}'

ch_algo="comfyui ${ch_state:-stopped}"
ch_activity=$(jq -r '.activity // empty' <<< "$ch_page" 2>/dev/null)
[[ $ch_state == ready && -n $ch_activity ]] && ch_algo="comfyui $ch_activity"
ch_speed=$(jq -r 'if .generating then (.it_s // 0) else 0 end' <<< "$ch_page" 2>/dev/null)
[[ $ch_speed =~ ^[0-9.eE+-]+$ ]] || ch_speed=0
ch_done=$(jq -r '.done // 0' <<< "$ch_page" 2>/dev/null)
ch_failed=$(jq -r '.failed // 0' <<< "$ch_page" 2>/dev/null)
[[ $ch_done =~ ^[0-9]+$ ]] || ch_done=0
[[ $ch_failed =~ ^[0-9]+$ ]] || ch_failed=0

ch_temp='[]'
ch_fan='[]'
ch_bus='[]'
if [[ -f $ch_gpu_stats ]]; then
    # Hive lists onboard graphics too; only cards count
    ch_cards='[.brand | to_entries[] | select(.value != "cpu") | .key] as $i'
    ch_temp=$(jq -c "$ch_cards | [\$i[] as \$k | .temp[\$k] | tonumber]" "$ch_gpu_stats" 2>/dev/null)
    ch_fan=$(jq -c "$ch_cards | [\$i[] as \$k | .fan[\$k] | tonumber]" "$ch_gpu_stats" 2>/dev/null)
    ch_bus=$(jq -c "$ch_cards | [\$i[] as \$k | .busids[\$k] | split(\":\")[0] | tonumber? // 0]" "$ch_gpu_stats" 2>/dev/null)
fi
[[ -n $ch_temp ]] || ch_temp='[]'
[[ -n $ch_fan ]] || ch_fan='[]'
[[ -n $ch_bus ]] || ch_bus='[]'

ch_count=$(jq -r 'length' <<< "$ch_temp" 2>/dev/null)
[[ ${ch_count:-0} -gt 0 ]] || ch_count=1
# ComfyUI uses one GPU (gpus=), so only that one has a speed
ch_gpu=$CH_GPUS
[[ $ch_gpu -lt $ch_count ]] || ch_gpu=0
khs=$(awk -v v="$ch_speed" 'BEGIN { printf "%.6f", v / 1000 }')

ch_uptime=0
[[ $ch_started =~ ^[0-9]+$ ]] && ch_uptime=$(( $(date +%s) - ch_started ))

stats=$(jq -nc \
    --argjson speed "$ch_speed" --argjson count "$ch_count" --argjson gpu "$ch_gpu" \
    --argjson temp "$ch_temp" --argjson fan "$ch_fan" --argjson bus "$ch_bus" \
    --argjson uptime "$ch_uptime" --argjson done "$ch_done" --argjson failed "$ch_failed" \
    --arg ver "${CUSTOM_VERSION:-}" --arg algo "$ch_algo" \
    '{hs: [range(0; $count) | if . == $gpu then $speed else 0 end], hs_units: "hs", temp: $temp, fan: $fan,
      bus_numbers: $bus, uptime: $uptime, ver: $ver, ar: [$done, $failed], algo: $algo}')
