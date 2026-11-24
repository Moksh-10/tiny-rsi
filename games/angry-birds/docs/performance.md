# v0.3 performance checks

Measured on the development Apple M2 Mac. These are local observations, not promises for every GPU or display.

## Final 4K workload

The built-in benchmark used a 3840×2160 color target, 60 warmup frames and 300 measured frames. It ran the final level with physics, periodic effects, streamed music updates and presentation, with VSync/frame limiting disabled.

- Mean wall-clock frame: **5.51 ms**.
- 95th percentile: **9.13 ms**.
- 99th percentile: **10.46 ms**.
- Peak process RSS: **180.5 MiB**.
- Color render attachment: **31.64 MiB**.
- Estimated texture storage, including mipmaps/font atlases: **31.58 MiB**.
- Audio PCM/sample-block storage: **0.75 MiB**.

Raw output: `docs/benchmarks/v0.3-m2-4k.json`.

Frame times are application/driver wall times, not isolated GPU timestamps. Particle positions, OS activity and driver scheduling can vary across runs. The 60 FPS frame budget is 16.67 ms; this measured workload's 99th percentile was below that budget.

## Memory tradeoffs

The old build retained three complete music tracks. Its estimated audio PCM storage was 19,203,832 bytes; the streamed implementation reports 784,120 bytes, about **96% less**. Backend/driver overhead is additional to this estimate.

Overall process peak memory did **not** decrease. A menu smoke test measured 161.5 MiB in the old build and 179.0 MiB in v0.3 when explicitly rendering at 720p. The new build also changed the native window/HiDPI backing policy, full-resolution textures, mipmaps, shaders and graphics driver state, so this is not an isolated comparison of one allocator or subsystem. Native-resolution v0.3 menu smoke measured 179.7 MiB.

The improvement is sharper rendering with explicit resource ownership and bounded storage, not an unsupported claim of universally lower RSS. The 4K scene has nine times the old fixed render target's pixel count. Its color attachment has no unused depth buffer. Effects are capped at 1,024 particles, 128 popups and 32 shockwaves; resizing may temporarily retain both old and new color attachments.

## Correctness gates

- All twelve levels retain their stability checks and verified three-star solutions.
- Normal runtime, simulation and graphical flow suites pass.
- AddressSanitizer/UndefinedBehaviorSanitizer pass the simulation, runtime and graphical flow suites locally.
- ThreadSanitizer passes the save-worker concurrency, shutdown, atomic-file and ownership tests.
- Actual GPU resize tests cover 720p, 1440p and 4K; 8K allocations are rejected.
- Asset construction failures release previously acquired GPU/CPU handles.
- Foreign-thread rendering is rejected before any GPU call.

Repeat the benchmark using the command in `docs/runtime-design.md` and keep compilers or other benchmarks idle during measurement.
