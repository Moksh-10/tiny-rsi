# Research runtime

`src/tiny_rsi` is the sole Python runtime. It provides a guest-only Ollama gameplay
actor, native-environment transport, process vectorization, deterministic
metrics, replay, and bounded experiment proposals. No Go installation is needed.

## Entry points

Run from the repository root after `python -m pip install -e research`, or prefix
commands with `PYTHONPATH=research/src python3 -m tiny_rsi` instead of `tiny-rsi`.

```sh
tiny-rsi play --help
tiny-rsi plan --help
tiny-rsi policy-train --help
tiny-rsi evaluate --help
tiny-rsi policy-experiment --help
tiny-rsi replay --help
tiny-rsi teacher-collect --help
tiny-rsi distill --help
tiny-rsi model-evaluate --help
```

- `play`: actual Ollama model gameplay, with explicit teacher/student/evaluator
  role, model digest, bounded actions/tokens/time, and replayable traces.
- `plan`: physics-search tool baseline. It queries the public native protocol;
  oracle calls and simulated ticks are charged separately from inference.
- `policy-train`: tiny neural/CART policy baseline training. This is not Ollama
  language-model fine-tuning, and the class is named `PolicyBaseline` accordingly.
- `evaluate`: fixed-budget game metrics. Birds train levels are 0–5, validation
  6–7, and held-out 8–11. Climbing has one course, so repeated evaluation is
  explicitly same-course replication, not unseen-course generalization.
- `policy-experiment`: the supporting small-policy experiment loop. Local Ollama
  proposes bounded configurations, then code trains/evaluates candidates and
  applies a fixed promotion gate. It does not self-modify the base language model.
- `replay`: compare recorded native responses against a trusted environment
  executable. Use the original engine revision for historical traces.

## Actual Ollama teacher/student models

[../config/models.json](../config/models.json) defines teacher 3B, student 0.5B,
and evaluator/researcher 3B roles. The latter roles reuse the same model weights
sequentially to conserve storage and RAM. Role names always describe runtime
model invocations, never the coding assistants used to develop this repository.

A planning tool can assist the teacher, but a planner action is not a
teacher-model response. Language-model distillation data must identify the
actual model response, model digest, tool use and action executed. A lightweight
policy baseline checkpoint must never be presented as an Ollama student model.

The fixed native evaluator owns success/progress metrics. An evaluator model's
critique is advisory and cannot change rewards, partitions, budgets or promotion.
Held-out scores must not be returned to the researcher during candidate selection.

## Isolation and launchers

Actual runs require non-root Linux execution, a detected VM, root-owned worker
and seal markers, and no host-sharing filesystems. `sandbox/scripts/verify.sh`
checks guest boundaries before launch. The VM firewall allows loopback and
management SSH replies; external runtime traffic is blocked. Model downloads and
provisioning are explicit maintenance operations followed by resealing.

```sh
scripts/worker.sh start
scripts/worker.sh deploy
MODEL_ROLE=teacher scripts/worker.sh pull
scripts/worker.sh seal
MODEL_ROLE=teacher scripts/worker.sh run angry-birds 32 0
```

The actor stores private JSONL under `/var/lib/game-research/results` inside the
guest. The launcher exports completed traces into ignored `experiments/results`.
Files are created exclusively and existing traces are not overwritten. Source
revisions, engine hashes, model identities, raw actions, invalid requests and
termination reasons are recorded. Model text is data, never executable code.

`lab.sh` is the trusted development launcher for the research modules. It stages
a hashed byte snapshot with no credentials or live host directory, refuses to
replace code while a research unit is active, and runs under bounded systemd
units. Launcher scripts snapshot themselves before executing, so editing source
during a long run cannot corrupt their remaining shell commands.

The optional Gymnasium adapter is installed with `pip install -e 'research[gymnasium]'`.
Base gameplay, data handling and small-policy experiments require only Python's
standard library. Process-vector environments within one guest share its kernel;
they are not separate security sandboxes. The optional execution VM has its own
kernel and uses the same explicitly copied Linux environment binary.

## Verification

```sh
PYTHONPATH=research/src python3 -m unittest discover -s research/tests -p '*test*.py'
ctest --test-dir build-headless --output-on-failure
bash -n scripts/*.sh sandbox/scripts/*.sh
```

The native protocol integration tests live under `environments/native/tests`;
per-game physics/persistence tests live with each game. Archived early baselines
are under [../experiments/baselines](../experiments/baselines).

## Actual language-model distillation

`teacher-collect` calls the configured Ollama teacher, exposes a bounded planning
recommendation as a tool result, and executes the model's returned action. Its
public student prompt excludes that recommendation. `distill` requires verified
teacher-response rows, trains frozen-base CPU LoRA for the actual 0.5B language
model, and exports adapter provenance plus merged Safetensors. Heavy imports are
lazy; the standard package and tests do not require Torch.

`scripts/training.sh setup` provisions the separate guest training virtualenv,
checks dependency plans for GPU packages, downloads a pinned and SHA256-verified
0.5B base, and builds a fixed llama.cpp converter/quantizer. It requires at least
20 GiB free host space and refuses maintenance during any agent job. Explicit
CPU-index Torch avoids accidental CUDA downloads on Linux ARM64.

The installed Ollama version rejects direct `ADAPTER` imports. Deployment must
merge LoRA into the pinned base, convert/quantize both the untrained and trained
models with the same recipe, then import standalone GGUF models. Identical
prompts, templates, quantization, game cases and budgets are required for paired
comparison. `model-evaluate` records actual model identities; without a matching
training/conversion manifest it cannot claim a verified weight update or promote
a candidate. The evaluator-model critic is advisory and excludes held-out data.

A source implementation and mocked tests do not prove successful training or
improvement. Real completed training metrics, imported model digests and game
results must be produced before those claims are made.
