# Slingshot Valley

A playable Angry Birds-style prototype in C++20, using raylib 5.5 and Box2D 3.1.1. All artwork is drawn in code; no asset downloads or accounts are required.

## Build and run on macOS

Install Xcode Command Line Tools (`xcode-select --install`) and CMake (`brew install cmake`) if needed. The first configure downloads the pinned library sources from GitHub and requires internet access.

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --parallel
./build/angry-birds
```

Drag the bird on the slingshot backward, then release. Pull distance controls power. Destroy all four pigs with three birds. Wood and stone take impact damage; spare birds earn bonus points.

- **R** or **RETRY**: reset the level
- **P**: pause/resume
- **Escape**: quit

The window is resizable; mouse coordinates follow the scaled playfield. A shot resolves when the scene settles or after 12 seconds.

## Verify

```sh
ctest --test-dir build --output-on-failure
./build/angry-birds --smoke-test
```

The simulation test runs without a window and checks stability, launch rules, collision damage, shot resolution, reset, loss after missed shots, and a winning two-shot sequence. The smoke test opens a window and exits after 60 frames.

## Structure

- `src/simulation.*`: Box2D world, level layout, fixed 60 Hz simulation with four substeps, impact damage, and turn state.
- `src/main.cpp`: raylib rendering, procedural artwork, pointer input, trajectory preview, and UI.
- `tests/simulation_test.cpp`: headless gameplay checks.

This first version has one level and one bird type. Audio, saved progress, more levels, touch-device packaging, and browser exports are future work. The trajectory preview shows free flight and ends at the ground; it does not predict collisions.
