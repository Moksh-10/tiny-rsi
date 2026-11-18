#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd "$(dirname "$0")/.." && pwd)"
build_dir="${1:-$repo_dir/build}"
cmake -S "$repo_dir" -B "$build_dir" -DCMAKE_BUILD_TYPE=Release
cmake --build "$build_dir" --parallel
ctest --test-dir "$build_dir" --output-on-failure
mkdir -p "$repo_dir/dist"
if [[ "$(uname -s)" == Darwin ]]; then
  app="$build_dir/angry-birds.app"
  for asset in meadow.png canyon.png night.png characters.png Bangers-Regular.ttf Nunito-Bold.ttf; do
    test -s "$app/Contents/MacOS/assets/$asset"
  done
  "$app/Contents/MacOS/angry-birds" --test-ui
  ditto -c -k --sequesterRsrc --keepParent "$app" "$repo_dir/dist/Slingshot-Valley-macOS.zip"
  printf 'Packaged: %s\n' "$repo_dir/dist/Slingshot-Valley-macOS.zip"
else
  tar -czf "$repo_dir/dist/Slingshot-Valley-Linux.tar.gz" -C "$build_dir" angry-birds assets
  printf 'Packaged: %s\n' "$repo_dir/dist/Slingshot-Valley-Linux.tar.gz"
fi
