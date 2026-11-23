# Environment protocol v1

`game-env` reads one JSON object per newline on stdin and writes one response
per newline on stdout. It does not open a network listener or load game assets.
Malformed requests produce `{ "ok": false, "error": "..." }` and leave the
simulation unchanged. Inputs are limited to 65536 bytes; oversized records are
drained. Unknown fields/actions and nonfinite/out-of-range numbers are rejected.

```json
{"op":"describe"}
{"op":"reset","game":"angry-birds","level":0}
{"op":"act","action":{"type":"launch","x":-75,"y":45,"ticks":120}}
{"op":"act","action":{"type":"wait","ticks":120}}
{"op":"observe"}
{"op":"reset","game":"getting-over-it","level":0}
{"op":"act","action":{"type":"hammer","x":3,"y":-1,"hold":true,"ticks":60}}
```

`describe` reports available games and coordinate/action conventions. Levels
are zero-based: birds 0–11; ascent 0 only. Reset constructs an independent episode
with no player save/progress import. Every action requires integer ticks 1–120.
One interface tick is 1/60 second. Birds uses its existing 60 Hz / four Box2D
substeps; ascent uses two native 120 Hz steps per interface tick.

Bird actions are `launch`, `ability`, and `wait`. Launch pull x/y are pixels,
each [-95,95], Euclidean length [8,95]. Coordinates x right/y down; pull x<0
launches right and y>0 launches up. Launch is only legal while aiming; ability
only when ready. Observation includes phase, score, pigs, birds, ability status,
next bird, and live entities with kind, geometry, health and pixel velocities.
Entity IDs refer to stable indices for that episode, not pointers/body handles.

Ascent requires `hammer`, aim x/y each [-3.15,3.15] meters, boolean `hold`, and
ticks. Aim is relative to the shoulder, clamped by the native physics to a
3.15m reach. Coordinates x right/y up. Observation includes body/tip state,
velocity, grip, ground contact, falls, best height and nearby terrain polygons.

Successful reset/observe/act responses contain `ok`, `protocol`, `game`,
`observation`, `reward`, `terminated`, `truncated`, and `info` (ticks, max_ticks,
track and success). Observe/reset reward is zero. No auto-reset occurs.
Actions after an episode finishes are rejected until explicit reset.

Bird reward = score difference / 1000 minus 0.00001 per advanced tick. Both win
and loss terminate; `info.success` distinguishes them. Ascent reward = increase
in run-best height / 66 minus the same tick cost. Falls preserve run-best as in
the native game; repeated recovery does not repeatedly earn height reward.
Crossing the native victory threshold (body center y > 65.75m) terminates;
the shared `reachedSummit` predicate is used by both UI and headless play. Both games truncate at 18,000 ticks
(300 simulated seconds), unless they terminate on that tick. These are initial
benchmark rewards, not evidence of a learned policy.
