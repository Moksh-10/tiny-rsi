# Angry Birds — Slingshot Valley

A native C++20 slingshot game with a twelve-level campaign, three illustrated worlds, a persistent star map, and an expressive flock. Built with raylib 5.5 and Box2D 3.1.1.

## Play

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --parallel
./build/angry-birds
```

On macOS, you can also open `build/angry-birds.app` in Finder. Install Xcode Command Line Tools (`xcode-select --install`) and CMake if needed. Initial configuration downloads the pinned dependencies from GitHub; after building, gameplay is offline.

Start with **Let's Play** or **Choose Level**. Clearing a level unlocks the next, and replaying can improve your best score and stars.

- **Drag the bird back, then release:** aim and launch.
- **Space** or click the playfield during flight: use Dash's speed boost or Bomb's explosion. Red has no special ability.
- **P / Escape:** pause or resume. Escape backs out of other screens; on the home screen it quits.
- **R:** retry the current level.
- **M:** toggle audio. The sound button is also available in the menus.
- The pause screen includes resume, retry, level map, help, sound, and home controls.

The game pauses when it loses focus. Resizing keeps the playfield's proportions and pointer alignment. A turn ends when motion settles, with a ten-second cap.

## Campaign

Three chapters, four levels each:

- **Greenwood Grove:** first flight, a broad timber arch, breakable glass houses, and twin forts.
- **Sunset Canyon:** elevated cliffs and a bridge, an explosive relay, heavy roofs on fragile supports, and a tall central spire.
- **Moonlight Ridge:** a stepped skyline, a glass pyramid, a fortified powder keg, and a final elevated castle.

Wood, glass, stone, and TNT have distinct physics and damage properties. TNT and Bomb create radial damage and impulses. Physics runs at a fixed 60 Hz with four solver substeps; fast birds use continuous collision detection.

## Saves

Unlocks, stars, best scores, and audio preference are saved automatically. Saves live outside the app so replacing the app preserves progress:

- macOS: `~/Library/Application Support/Slingshot Valley/progress.dat`
- Linux: `$XDG_DATA_HOME/slingshot-valley/progress.dat`, or `~/.local/share/slingshot-valley/progress.dat`
- Windows path handling: `%APPDATA%/Slingshot Valley/progress.dat` (Windows builds have not been verified).

Saves are versioned, validated on load, and written using a temporary file followed by rename. A failed save is reported in the UI. `--demo`, UI tests, previews, and smoke tests do not read or change real player saves.

## Verification

```sh
ctest --test-dir build --output-on-failure
./build/angry-birds --test-ui
./build/angry-birds --smoke-test
./build/angry-birds --render-previews build/previews
```

The simulation suite checks all twelve levels for five seconds of pre-shot stability and verifies recorded winning sequences, star ratings, retries, finite physics, launch constraints, abilities, loss, unlocks, save round trips, and corrupt-save rejection. The UI test exercises play → pause → resume → retry → win → results → next level, map locks, help, audio, and loss → retry using internal controls, without desktop automation. Render previews export the renderer's own textures for all menus and all twelve levels.

To include the graphical UI test in CTest, configure with `-DSLINGSHOT_UI_TESTS=ON`. On headless Linux, run it under `xvfb-run -a`. GitHub Actions builds and runs simulation tests on macOS and Ubuntu. Graphical UI tests run under a virtual display on Ubuntu; hosted macOS runners have no usable OpenGL display. Local macOS UI tests also run under address and undefined-behavior sanitizers.

Development shortcuts: `--demo` starts without player saves; `--level 1` through `--level 12` open a level directly. Invalid options exit with code 2.

## Package

```sh
scripts/package.sh
```

On macOS, this verifies the build and creates `dist/Slingshot-Valley-macOS.zip`, containing the app and its assets. This is a local unsigned app, not an App Store or notarized release. The Linux package path exists but is subject to the Linux CI result; local verification was on Apple Silicon macOS.

## Source

- `src/main.cpp`: application flow, input, menus, campaign map, HUD, and results.
- `src/presentation.*`: character sprites, environments, materials, effects, fonts, and synthesized sound/music.
- `src/simulation.*`: physics, turns, impact damage, explosions, and bird abilities.
- `src/levels.*`: authored level compositions, bird loadouts, and star thresholds.
- `src/progress.*`: player records and save validation.
- `tests/simulation_test.cpp`: campaign and persistence regression tests.

Visual references: the official Angry Birds and Rovio game pages. The project includes generated scenery and character art; see `docs/art-direction.md` for prompts and provenance. Font licenses and library notices are bundled with the assets.
