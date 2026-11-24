# Verification — 18 November 2026

Verified locally on Apple Silicon macOS with Apple Clang, C++20, raylib 5.5 and Box2D 3.1.1.

## Gameplay regression suite

- All twelve initial level layouts remain within eight pixels of their authored object positions after five seconds without a shot.
- Every level has a tested winning sequence that earns three stars within the three-bird budget.
- Tiny and invalid pulls do not consume birds; a second bird cannot launch during an active turn.
- Bird abilities are available only for the correct bird in flight and can activate once per shot.
- Missing every shot reaches loss; retry restores the selected level, targets, score, and flock.
- Win bonuses are awarded once.
- The same shot produces matching physics positions and object survival when the render loop updates at 30, 60, and 120 FPS.
- Unlock boundaries, best-score preservation, complete-campaign progression, save round trips, and corrupt-save rejection pass.

## Internal UI-flow test

The game calls its actual button handlers and render methods with test input. It checks home → play → pause → resume → retry → win → results → next level, locked and unlocked map nodes, help and back navigation, sound toggle, loss, and try again. It does not use desktop automation or inject OS input.

## Rendering and packaging

The game's own render target exports all menu screens and all twelve level scenes to `build/previews/`. Layout review covered typography, character sprites, material textures, playfield alignment, level composition, and overlays.

AddressSanitizer and UndefinedBehaviorSanitizer runs cover the campaign and internal graphical UI tests. The extracted macOS archive was smoke-tested from `/tmp`; its dynamic dependencies are system libraries/frameworks, with game assets bundled inside the app.

The GitHub workflow checks macOS builds/simulation/package generation and Ubuntu builds/simulation/graphical flow under Xvfb. Hosted macOS runners lack a usable OpenGL display, so a separate startup check verifies graceful failure there. Local macOS graphical checks use the real graphics context.

## Release scope

This is a complete offline desktop campaign build. It is not signed or notarized for public macOS distribution. The locally packaged binary is arm64. Windows, browser export, and native mobile builds are outside the verified release scope.

## v0.3 update — 19 November 2026

The graphics/runtime revision adds physical-pixel rendering up to 4K, distance-field text, source-detail mipmapped materials, interpolated physics, color-only framebuffers, move-only native resources, bounded effects, streamed music, and a coalescing save worker. The complete local address/undefined-behavior and race-check suites pass. Cross-platform CI includes normal builds plus address and thread sanitizer jobs.

See `docs/runtime-design.md` for lifecycle/threading rules and `docs/performance.md` for the measured performance and explicit memory tradeoffs. No computer-use automation was used for this verification; visual checks used exported render targets.
