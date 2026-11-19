#!/usr/bin/env bash

# Sourced by Hive when the flight sheet is applied, so it must never call exit.
# Reads key=value settings from the flight sheet's "Extra config arguments" (CUSTOM_USER_CONFIG), one per line or
# separated by spaces. Each value is checked, because h-run.sh sources the file this writes.
# No setting picks a model: that is done on the rig's page, so every rig can share one flight sheet.

comfyui_hive_valid() {
    case "$1" in
        port)                           [[ $2 =~ ^[1-9][0-9]*$ ]] ;;
        allow)                          [[ $2 =~ ^[0-9./,]+$ ]] ;;
        peers)                          [[ $2 =~ ^[0-9.:,]+$ ]] ;;
        bind)                           [[ $2 =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ && $2 != 0.0.0.0 ]] ;;
        data_dir)                       [[ $2 =~ ^/[A-Za-z0-9._/-]+$ ]] ;;
        gpus)                           [[ $2 =~ ^[0-9]+$ ]] ;;
        torch_index)                    [[ $2 =~ ^(cu[0-9]+|cpu)$ ]] ;;
        comfyui_version)                [[ $2 =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] ;;
        hf_token)                       [[ $2 =~ ^hf_[A-Za-z0-9]+$ ]] ;;
        reset_oc|allow_docker)          [[ $2 =~ ^[01]$ ]] ;;
        *)                              return 2 ;;
    esac
}

comfyui_hive_config() {
    local item key value result
    local conf=""

    for item in $CUSTOM_USER_CONFIG; do
        key=${item%%=*}
        value=${item#*=}
        if [[ $item != *=* ]]; then
            echo "comfyui-hive: ignoring '$item': expected key=value"
            continue
        fi
        comfyui_hive_valid "$key" "$value"
        result=$?
        if [[ $result -eq 2 ]]; then
            echo "comfyui-hive: ignoring unknown setting '$key'"
        elif [[ $result -ne 0 ]]; then
            echo "comfyui-hive: ignoring invalid value for '$key'"
        else
            conf+="CH_${key^^}=${value}"$'\n'
        fi
    done

    # It holds hf_token
    ( umask 077; printf '%s' "$conf" > "$CUSTOM_CONFIG_FILENAME" )
}

comfyui_hive_config
unset -f comfyui_hive_valid comfyui_hive_config
