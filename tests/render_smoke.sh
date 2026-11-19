#!/usr/bin/env bash
set -euo pipefail

executable="${1:?Pass the native game executable}"
output="${2:-/tmp/ascent-render}"
mkdir -p "$output"
for scene in intro heights summit pause settings help victory; do
    if ! "$executable" --smoke-test "--scene=$scene" "--capture=$output/$scene.png" > "$output/$scene.log" 2>&1; then
        cat "$output/$scene.log"
        exit 1
    fi
    if ! test -s "$output/$scene.png"; then
        echo "Missing capture for $scene" >&2
        exit 1
    fi
    echo "PASS: $scene"
done
