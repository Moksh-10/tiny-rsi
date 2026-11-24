# Graphics and runtime design — v0.3

## Resolution and rendering

The logical playfield stays at 1280×720 so level geometry, UI layout and pointer coordinates remain consistent. The offscreen render target follows the physical drawable size, including Retina scaling, and is capped at 3840×2160. Letterboxing preserves the aspect ratio. F11 toggles borderless fullscreen. `--render-scale 1`, `2`, or `3` explicitly select 720p, 1440p, or 4K rendering.

The scene uses a color-only framebuffer. A 4K RGBA8 attachment is 33,177,600 bytes (31.64 MiB); there is no unused depth attachment. Replacement allocates the new target before releasing the previous one, so resizing can temporarily hold two attachments. Allocations occur only when the computed target size changes. Invalid or over-budget targets and invalid render-pass nesting are rejected.

Text uses signed-distance font atlases with derivative-based edge smoothing, preserving sharp edges without a huge font bitmap at every resolution. Character and material textures retain source detail and have mipmaps for minification. Nine-slice material rendering decouples source border pixels from logical border thickness. Source backgrounds retain their existing native dimensions; 4K scene rendering does not turn them into newly authored 4K illustrations.

Scenery has a single-pass color-grade shader. Entity shadows and bounded explosion rings add depth and feedback. Physics transforms are interpolated between fixed 60 Hz steps so higher-refresh rendering stays smooth without changing gameplay.

## Resource ownership and memory

Images, GPU textures, font atlases, shaders, audio clips, streams and framebuffers have move-only resource owners. Destruction and move replacement release each owned handle once; borrowed raylib structs do not transfer ownership. Construction failures release already-acquired resources. CPU atlas images and per-glyph image payloads are released after GPU upload. Live owner counts support cleanup tests; they do not measure deferred driver allocations.

Effects use inline fixed storage: 1,024 particles, 128 score popups and 32 shockwaves. Excess cosmetic effects are dropped rather than growing the heap. The flight trail reserves its 900-point limit in advance. Level entities and feedback buffers reserve storage before play.

Music is synthesized into a reusable 2,048-frame sample block and submitted to one double-buffered audio stream. Three complete 16-second tracks are no longer preloaded. Short interaction effects remain preloaded. The audio API copies submitted samples before the reusable block is filled again.

## Thread ownership

Rendering, resource uploads, audio API calls, effects and simulation run on the main thread. Graphics/audio entry points check the owning thread before native access. There is no parallel rendering or shared mutable physics world.

The save worker owns file I/O. The main thread publishes an immutable value copy of player progress. A mutex protects one pending snapshot and revision counters; a condition variable wakes the worker. New requests replace an older pending snapshot, keeping queue memory bounded. File I/O runs outside the mutex. Completion and errors are read through synchronized status snapshots. Shutdown joins the worker after draining the final pending save; no threads are detached.

Save writes use process- and sequence-specific temporary filenames, followed by rename. Independent writers cannot overwrite each other's temporary files. Rename gives complete-file replacement on the verified macOS/Linux platforms; it is not a guarantee against power-loss without filesystem durability synchronization.

## Verification

`runtime-tests` covers fixed-pool overflow/reuse, Retina/ultrawide target planning, memory limits, resource moves and exception cleanup, wrong-thread access, eight concurrent save producers (801 total submissions), final-snapshot persistence, shutdown draining, I/O failure and concurrent atomic writers.

`--test-ui` additionally checks actual GPU target resizing through 720p, 1440p and 4K, rejects an 8K allocation, verifies color-only attachments and one live target, injects an asset-construction failure after uploads, and rejects a foreign-thread render call before GPU access. Existing campaign and navigation tests remain in place.

Configure `-DTINY_RSI_SANITIZER=address` for AddressSanitizer plus UndefinedBehaviorSanitizer, or `-DTINY_RSI_SANITIZER=thread` for ThreadSanitizer. These modes are also checked in CI. The race suite targets the application's concurrent save path; it is not a blanket claim that every external platform framework has been race-tested.

## Repeatable benchmark

```sh
./build/games/angry-birds/angry-birds --benchmark --render-scale 3 --benchmark-output build/benchmark-4k.json
```

The benchmark disables frame pacing, runs 60 warmup frames and measures 300 frames of the final level with physics, periodic effects, streamed audio and presentation. It reports wall-clock frame times, peak process RSS, estimated texture storage, the color attachment and audio PCM storage. These are local measurements, not universal frame-rate guarantees or GPU-timestamp measurements. Do not run builds or other benchmarks concurrently when comparing results.
