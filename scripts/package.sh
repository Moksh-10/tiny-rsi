#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd "$(dirname "$0")/.." && pwd)"
build_dir="$repo_dir/build"
game=all
ui_tests=ON
while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-ui) ui_tests=OFF; shift ;;
    --game) game=${2:?game required}; shift 2 ;;
    --build-dir) build_dir=${2:?build directory required}; shift 2 ;;
    *) echo 'Usage: package.sh [--skip-ui] [--game all|angry-birds|getting-over-it] [--build-dir PATH]' >&2; exit 2 ;;
  esac
done
case "$game" in all) games=(angry-birds getting-over-it);; angry-birds|getting-over-it) games=("$game");; *) exit 2;; esac
cmake -S "$repo_dir" -B "$build_dir" -DCMAKE_BUILD_TYPE=Release -DSLINGSHOT_UI_TESTS="$ui_tests"
cmake --build "$build_dir" --parallel "${BUILD_JOBS:-4}"
ctest --test-dir "$build_dir" --output-on-failure
mkdir -p "$repo_dir/dist"
for id in "${games[@]}"; do
  if [[ $id = angry-birds ]]; then name=Slingshot-Valley; executable=angry-birds;
  else name=The-Ascent; executable=the_ascent; fi
  directory="$build_dir/games/$id"
  if [[ "$(uname -s)" == Darwin ]]; then
    app="$directory/$executable.app"
    test -x "$app/Contents/MacOS/$executable"
    if [[ $id = angry-birds ]]; then
      for asset in meadow.png canyon.png night.png characters.png materials.png Bangers-Regular.ttf Nunito-Bold.ttf shaders/sdf.fs shaders/scenery.fs; do
        test -s "$app/Contents/MacOS/assets/$asset"
      done
    else
      test -d "$app/Contents/Resources"
    fi
    ditto -c -k --sequesterRsrc --keepParent "$app" "$repo_dir/dist/$name-macOS.zip"
  else
    tar -czf "$repo_dir/dist/$name-Linux.tar.gz" -C "$directory" "$executable" assets
  fi
  printf 'Packaged: %s\n' "$name"
done
