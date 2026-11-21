#!/usr/bin/env bash

# Builds the miner's package, comfyui-hive-<version>.tar.gz, from what is committed in two repositories: the Hive
# scripts of this one, and the page program (page.py, trainer.py, rigtools.py, cleanup.py, page.html, the catalog and the workflows) of xefier-comfyui,
# which is the only place that program is kept. The version is CUSTOM_VERSION of h-manifest.conf.
#
#   bash release.sh [folder to put the package in, this one by default]
#
# XEFIER_COMFYUI names the other repository's clone when it isn't at ../../../xefier-comfyui.

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
here=$(pwd)
program=${XEFIER_COMFYUI:-../../../xefier-comfyui}
target=$(cd "${1:-.}" && pwd)
parts=(comfyui-hive/page.py comfyui-hive/trainer.py comfyui-hive/rigtools.py comfyui-hive/cleanup.py comfyui-hive/page.html comfyui-hive/catalog.json comfyui-hive/workflows)

git -C "$program" rev-parse --git-dir >/dev/null 2>&1 \
    || { echo "No clone of xefier-comfyui at $program: set XEFIER_COMFYUI to it" >&2; exit 1; }
# Only what is committed goes in: say so when something that would go in isn't
git diff --quiet HEAD -- comfyui-hive || echo "Note: comfyui-hive/ has changes that aren't committed, and aren't in the package" >&2
git -C "$program" diff --quiet HEAD -- "${parts[@]}" \
    || echo "Note: xefier-comfyui's page program has changes that aren't committed, and aren't in the package" >&2

version=$(git show HEAD:comfyui-hive/h-manifest.conf | sed -n 's/^CUSTOM_VERSION=//p')
[[ -n $version ]] || { echo "No CUSTOM_VERSION in h-manifest.conf" >&2; exit 1; }
name="comfyui-hive-$version.tar.gz"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

git archive HEAD comfyui-hive | tar -x -C "$work"
git -C "$program" archive HEAD "${parts[@]}" | tar -x -C "$work"
# Which commit the page program is of, for whoever looks into a rig's folder
git -C "$program" rev-parse --short=7 HEAD > "$work/comfyui-hive/PROGRAM"
for script in "$work"/comfyui-hive/*.sh; do
    bash -n "$script"
done
[[ -f $work/comfyui-hive/page.py && -f $work/comfyui-hive/catalog.json ]] || { echo "The page program is missing" >&2; exit 1; }

# Hive runs it as root and wants the scripts executable; a relative name, as a drive letter isn't one tar takes
cd "$work"
tar --owner=0 --group=0 --numeric-owner --mode=777 -czf "$name" comfyui-hive
mv "$name" "$target/"
echo "$target/$name"
