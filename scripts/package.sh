#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd "$(dirname "$0")/.." && pwd)"
skip_ui=false
if [[ "${1:-}" == --skip-ui ]]; then
  skip_ui=true
  shift
fi
build_dir="${1:-$repo_dir/build}"
ui_tests=ON
if [[ "$skip_ui" == true ]]; then ui_tests=OFF; fi
cmake -S "$repo_dir" -B "$build_dir" -DCMAKE_BUILD_TYPE=Release -DSLINGSHOT_UI_TESTS="$ui_tests"
cmake --build "$build_dir" --parallel "${BUILD_JOBS:-4}"
ctest --test-dir "$build_dir" --output-on-failure
mkdir -p "$repo_dir/dist"
if [[ "$(uname -s)" == Darwin ]]; then
  app="$build_dir/angry-birds.app"
  for asset in meadow.png canyon.png night.png characters.png materials.png Bangers-Regular.ttf Nunito-Bold.ttf shaders/sdf.fs shaders/scenery.fs; do
    test -s "$app/Contents/MacOS/assets/$asset"
  done
  ditto -c -k --sequesterRsrc --keepParent "$app" "$repo_dir/dist/Slingshot-Valley-macOS.zip"
  printf 'Packaged: %s\n' "$repo_dir/dist/Slingshot-Valley-macOS.zip"
else
  tar -czf "$repo_dir/dist/Slingshot-Valley-Linux.tar.gz" -C "$build_dir" angry-birds assets
  printf 'Packaged: %s\n' "$repo_dir/dist/Slingshot-Valley-Linux.tar.gz"
fi
