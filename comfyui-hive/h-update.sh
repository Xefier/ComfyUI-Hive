#!/usr/bin/env bash

# Sourced by h-run.sh: the miner updates itself to the newest release, so the flight sheet's installation URL can stay
# the same for good. By itself when "Update automatically" is on in the page (it is, until turned off), or when Update
# is pressed there. Never while a request or a download runs or the rig may be rented: it waits for the rig to be idle.
#
# The page and this script talk through files: the page writes its setting to $CH_UPDATE_SETTINGS and makes
# $CH_UPDATE_ASKED when Update is pressed; this writes what it found and why it waits to $CH_UPDATE_STATUS.

CH_UPDATE_API="${COMFYUI_HIVE_UPDATE_API:-https://api.github.com/repos/Xefier/ComfyUI-Hive/releases?per_page=1}"
CH_UPDATE_FILES="${COMFYUI_HIVE_UPDATE_FILES:-https://github.com/Xefier/ComfyUI-Hive/releases/download}"
CH_UPDATE_EVERY=900  # seconds between looking for a newer release
CH_UPDATE_STATUS="$CH_RUN_DIR/update.json"
CH_UPDATE_ASKED="$CH_RUN_DIR/update-now"
CH_UPDATE_SETTINGS="$CH_PAGE_DATA/update.json"
CH_UPDATE_LATEST=""
CH_UPDATE_ERROR=""
CH_UPDATE_CHECKED=0

# Whether version $1 is newer than $2
update_newer() {
    [[ $1 != "$2" && $(printf '%s\n%s\n' "$1" "$2" | sort -V | tail -n 1) == "$1" ]]
}

# For the page: this version, the newest release, and why an update waits ($1). The texts are this script's own, so
# nothing in them needs escaping.
update_status() {
    local newer=false
    [[ -n $CH_UPDATE_LATEST ]] && update_newer "$CH_UPDATE_LATEST" "$CUSTOM_VERSION" && newer=true
    printf '{"current": "%s", "latest": "%s", "newer": %s, "waiting": "%s", "error": "%s", "checked": %s}\n' \
        "$CUSTOM_VERSION" "$CH_UPDATE_LATEST" "$newer" "$1" "$CH_UPDATE_ERROR" "$CH_UPDATE_CHECKED" > "$CH_UPDATE_STATUS.tmp" \
        && mv "$CH_UPDATE_STATUS.tmp" "$CH_UPDATE_STATUS"
}

# Asks GitHub for the newest release. Without an answer the last one known stays.
update_check() {
    local tag
    CH_UPDATE_CHECKED=$(date +%s)
    tag=$(curl -fsL --max-time 15 "$CH_UPDATE_API" 2>/dev/null | sed -n 's/.*"tag_name": *"\([^"]*\)".*/\1/p' | head -n 1)
    if [[ ! $tag =~ ^v[0-9]+(\.[0-9]+)*$ ]]; then
        CH_UPDATE_ERROR="The newest release could not be looked up"
        return 1
    fi
    CH_UPDATE_LATEST=$tag
    CH_UPDATE_ERROR=""
}

# Why an update has to wait, or nothing when the rig is idle and not rented. The page says both in page.json.
update_blocker() {
    local page="$CH_RUN_DIR/page.json"
    if ! page_running || [[ ! -f $page ]]; then
        echo "the page is starting"
    elif ! grep -q '"rental"' "$page"; then
        echo "the worker program from the hub is too old to say whether the rig is rented: update the hub"
    elif ! grep -q '"rental": *false' "$page"; then
        echo "the rig may be rented"
    elif ! grep -q '"activity": *"ready"' "$page"; then
        echo "a request or a download is running"
    fi
}

# Downloads release $1 and puts it in the miner's folder, which is swapped whole: the scripts running now keep their
# own files until they end. What only the old folder has (Hive's config for the miner) is kept.
update_install() {
    local tag=$1 work="$CH_DATA_DIR/update-download" fresh="$CH_DIR.new" old="$CH_DIR.old" script
    local name="$CUSTOM_NAME-$tag.tar.gz"
    rm -rf "$work" "$fresh" "$old"
    mkdir -p "$work"
    if ! curl -fsL --retry 2 --max-time 600 -o "$work/$name" "$CH_UPDATE_FILES/$tag/$name"; then
        CH_UPDATE_ERROR="$name could not be downloaded"
    elif ! tar -xzf "$work/$name" --no-same-owner -C "$work" 2>> "$LOG_FILE"; then
        CH_UPDATE_ERROR="$name could not be unpacked"
    elif [[ ! -f $work/$CUSTOM_NAME/h-run.sh || ! -f $work/$CUSTOM_NAME/page.py ]] \
            || ! grep -q "^CUSTOM_VERSION=$tag\$" "$work/$CUSTOM_NAME/h-manifest.conf" 2>/dev/null; then
        CH_UPDATE_ERROR="$name is not this miner at $tag"
    else
        CH_UPDATE_ERROR=""
        for script in "$work/$CUSTOM_NAME"/*.sh; do
            bash -n "$script" 2>> "$LOG_FILE" || CH_UPDATE_ERROR="$name has a script that does not parse"
        done
    fi
    if [[ -z $CH_UPDATE_ERROR ]]; then
        chmod +x "$work/$CUSTOM_NAME"/*.sh
        if mv "$work/$CUSTOM_NAME" "$fresh"; then
            cp -an "$CH_DIR/." "$fresh/" 2>/dev/null
            if mv "$CH_DIR" "$old" && mv "$fresh" "$CH_DIR"; then
                rm -rf "$work"
                return 0
            fi
            [[ -d $CH_DIR ]] || mv "$old" "$CH_DIR"
        fi
        CH_UPDATE_ERROR="The miner's folder could not be replaced"
    fi
    rm -rf "$work" "$fresh"
    log "Not updated to $tag: $CH_UPDATE_ERROR"
    return 1
}

# Everything stopped as when the flight sheet is switched, then this script again from the new folder, as the same
# process: Hive sees the miner keep running.
update_restart() {
    trap '' INT TERM HUP
    rm -f "$CH_RUN_DIR/run.pid" "$CH_UPDATE_STATUS"
    bash "$CH_DIR/h-stop.sh" >> "$LOG_FILE" 2>&1
    rm -rf "$CH_DIR.old"
    cd "$CH_DIR" || exit 1
    exec bash ./h-run.sh
}

# Called on every turn of h-run.sh's loop, and once before anything is started ($1 = start: nothing runs yet that an
# update could interrupt, and h-run.sh has just made sure the rig isn't rented).
self_update() {
    local start=$1 now auto=1 asked=0 blocker=""
    now=$(date +%s)
    grep -q '"auto": *false' "$CH_UPDATE_SETTINGS" 2>/dev/null && auto=0
    [[ -f $CH_UPDATE_ASKED ]] && asked=1
    # Every so often, and soon after Update was pressed
    if (( now - CH_UPDATE_CHECKED >= CH_UPDATE_EVERY )) || (( asked && now - CH_UPDATE_CHECKED >= 60 )); then
        update_check
    fi
    if [[ -z $CH_UPDATE_LATEST ]] || ! update_newer "$CH_UPDATE_LATEST" "$CUSTOM_VERSION"; then
        rm -f "$CH_UPDATE_ASKED"
        update_status ""
        return 0
    fi
    if (( ! auto && ! asked )); then
        update_status ""
        return 0
    fi
    [[ -n $start ]] || blocker=$(update_blocker)
    if [[ -n $blocker ]]; then
        update_status "$blocker"
        return 0
    fi
    log "Updating from $CUSTOM_VERSION to $CH_UPDATE_LATEST"
    rm -f "$CH_UPDATE_ASKED"
    if update_install "$CH_UPDATE_LATEST"; then
        notify info "Updated from $CUSTOM_VERSION to $CH_UPDATE_LATEST: starting again"
        update_restart
    fi
    # Not tried again before the next look for a release
    CH_UPDATE_LATEST=""
    update_status ""
}
