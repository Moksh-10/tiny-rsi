# Tiny RSI

A local research platform for Ollama agents playing two native C++ games. The goal
is to study teacher/student model distillation and bounded automated improvement
under limited compute. Game execution runs inside Linux VMs, without host mounts.

## Repository layout

```text
config/models.json             Ollama teacher/student/evaluator/researcher roles
games/angry-birds/              Slingshot Valley: source, assets, tests, game docs
games/getting-over-it/          The Ascent: source, assets, tests, game docs
environments/native/           Shared headless C++ JSONL protocol and contract tests
research/src/tiny_rsi/          Python actors, planning tools, learners and evaluation
research/tests/                 Mock/numerical research runtime tests
sandbox/lima/                   Inference and execution VM configurations
sandbox/scripts/                Guest sealing and boundary verification
scripts/                       Trusted host launchers and native packaging
experiments/baselines/          Versioned historical traces and measured evidence
experiments/results/            Local generated runs and checkpoints (Git ignored)
cmake/                         Shared native dependencies and sanitizer settings
docs/                          Platform architecture and research boundaries
```

Both games live under `games/`; neither game owns the research runtime. C++ is
used for simulation/rendering. Python handles model interaction, tools, data,
training and evaluation. Go is not required.

## Build the games

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --parallel 4
ctest --test-dir build --output-on-failure
./build/games/angry-birds/angry-birds
```

On macOS, open `build/games/getting-over-it/the_ascent.app` for the climbing game.
See each game's README for controls and graphics options. `scripts/package.sh
--skip-ui` packages both games; `--game angry-birds` selects one.

For research without graphics dependencies:

```sh
cmake -S . -B build-headless -DGAMES_BUILD_UI=OFF -DCMAKE_BUILD_TYPE=Release
cmake --build build-headless --parallel 4
ctest --test-dir build-headless --output-on-failure
```

The shared environment executable is `build-headless/bin/game-env`.

## Python runtime

Python 3.10+ is required. The base runtime has no third-party Python dependencies.

```sh
python3 -m venv research/.venv
. research/.venv/bin/activate
python -m pip install -e research
tiny-rsi --help
python -m unittest discover -s research/tests -p '*test*.py'
```

Development can also use `PYTHONPATH=research/src python3 -m tiny_rsi --help`.
Actual model/game-agent execution requires the provisioned, sealed Linux guest.
Unit tests use mocks and synthetic numerical data; native contract tests exercise
physics without a model.

## Run local Ollama agents in a VM

Install Lima (`brew install lima` on Apple Silicon macOS), then:

```sh
scripts/worker.sh start
scripts/worker.sh deploy
MODEL_ROLE=teacher scripts/worker.sh pull
MODEL_ROLE=student scripts/worker.sh pull
scripts/worker.sh seal
MODEL_ROLE=teacher scripts/worker.sh run angry-birds 32
MODEL_ROLE=student scripts/worker.sh run getting-over-it 32
```

Deployment requires a clean committed revision and transfers a Git archive, not
a live host mount. The default inference guest reserves 6 GiB RAM; the optional
execution guest reserves 2 GiB. Ollama loads one model at a time. Both defaults
fit within the 16 GiB host budget. New-worker creation requires 12 GiB free disk.
Use `scripts/worker.sh stop` or `scripts/lab.sh stop execution` to free resources.

## Model roles and current scope

Teacher, student, evaluator and researcher refer to **actual Ollama model
invocations**, configured in [config/models.json](config/models.json). Development
assistants are only writing and testing the code; they are not these models.
The evaluator model may critique a trajectory, but native game outcomes and the
fixed evaluation code remain authoritative.

The repository also contains a physics-search planner and tiny neural/tree
policy baselines. They are explicitly supporting tools/experiments, **not** the
intended Ollama teacher or student models. `plan`, `policy-train`, and
`policy-experiment` expose those baselines. Their measured gains do not establish
that an Ollama language model's weights improved. Language-model distillation is
a separate implementation path, and few-shot prompting is not weight training.

Read [the research runtime guide](research/README.md),
[architecture and isolation boundaries](docs/architecture.md), and
[the native protocol](environments/native/PROTOCOL.md).
Historical traces retain their original model identities, code revisions and
paths; reorganizing the repository does not rewrite past evidence.
