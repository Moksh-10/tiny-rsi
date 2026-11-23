# First isolated Ollama gameplay traces

Four individual smoke episodes on Apple M2 / 16 GiB host RAM, using one
Lima VZ Ubuntu arm64 VM (4 vCPUs, 6 GiB RAM). Guest-local Ollama 0.40.16 ran
`qwen2.5:3b` (3.1B parameters, Q4_K_M). The exact model digest and engine/actor
revision are recorded in each JSONL header and in [manifest.json](manifest.json).
No cloud inference, native Metal inference, training, or weight updates occurred.

## Observed behavior

The initial Angry Birds actor executed one valid action and made five invalid
attempts before the guard stopped it. It repeatedly requested a launch during
flight. The initial climbing actor executed 12 valid actions but mostly held a
stationary pose, reaching zero height.

The state-aware runner restricted action shapes to available controls, gave
separate game instructions and rounded only model-facing geometry. It offered
15/30/60/120-tick macro actions instead of inviting single-tick decisions.

- Angry Birds: six valid actions, zero invalid actions, 4,599 tokens, 42.561
  seconds wall time. All three shots repeated the same high arc; final score 0,
  two pigs remaining, terminal loss.
- Getting Over It: 12 valid actions, zero invalid actions, 8,351 tokens, 65.814
  seconds wall time. Best height 0.321725 simulation meters, no falls, no summit;
  stopped at the decision limit. It repeated the same ungripped hammer pose.

These episodes demonstrate an isolated observation/action loop and replayable
records. They do **not** establish model competence, a win rate, a learned
policy, or recursive self-improvement. The changes were human-engineered tool
and prompt changes. There is one run per game/configuration; settings and
trajectories differ, so the timing/token totals are not a controlled speedup
experiment. Reward/success remain anchored to the native game rules.

## Validation

All four traces were replayed inside the VM against their respective deployed
engine revisions: 40 reset/action responses, including rejected actions, matched
at the replay comparator's float tolerance. Full engine precision remains in
these logs; model prompts used the documented compact copy in the later runs.

Boundary checks passed before gameplay: VM detected as `apple`, no host-sharing
mounts, no actor sudo group/permission, no host Docker socket, host `/Users`
absent, external traffic blocked, guest loopback Ollama reachable. The final
nftables output policy was drop, allowing only loopback and established SSH
replies. No application port forward was configured. The actor also refused a
macOS host invocation before contacting Ollama.

The actor systemd units reported approximately 1.5–2.1 MiB of charged cgroup
peak memory. This is **not** whole-VM or model RSS. Ollama's cgroup peak reached
its configured 4 GiB limit, including file cache from provisioning/inference;
this is not a measurement of model working-set size. The VM was stopped after
verification to release resources.

Both native apps built on macOS; local native/headless tests and Go race/vet
checks passed. Cross-platform CI (macOS/Linux, headless actor, address/undefined
behavior checks and concurrent-save ThreadSanitizer checks) passed on the final
code revision `dc479ef`.

## Next research requirement

Establish competent, reproducible demonstrations and a fixed held-out evaluation
suite before distilling a student. Do not behavior-clone these repeated failing
actions as successful examples. Failure traces can instead support diagnostics
and later preference/correction datasets. A larger teacher, a planning baseline,
and smaller student should be compared under explicit memory/compute budgets.
