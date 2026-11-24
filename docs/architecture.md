# Architecture and research boundaries

The repository separates game implementation, environment transport, model
research, VM management and experimental evidence. The CMake root composes the
two games and the native environment; it contains no game implementation.

## Runtime responsibilities

C++ games own physics and human-facing rendering. `environments/native` links
both physics libraries and exposes the bounded JSONL reset/observe/act protocol.
It needs neither a display nor game assets. Python's `tiny_rsi.environment`
maintains bounded subprocess I/O; each vector member owns an independent C++
process. Shared guest processes are a throughput mechanism, not a security claim.

The Ollama actor consumes public observations and emits validated motor actions.
Teacher/student/evaluator/researcher are actual served model roles configured in
`config/models.json`. The physics planner is an optional tool. Small neural/tree
policies are supporting baselines, not the language-model teacher/student pair.

Model-generated configuration is restricted to a finite schema. Model output
cannot select a shell command, arbitrary program, filesystem mount, evaluator,
reward function, held-out partition or network endpoint. Native success metrics
remain authoritative even when an evaluator model offers a critique.

## Isolation and resources

Lima VZ runs a Linux kernel separate from macOS. No host folders, SSH agents,
Docker sockets or application ports are shared. Trusted host scripts copy
explicit source/binary snapshots over management SSH; runtime inference and
agent execution remain inside the guest. The host stores the VM's backing disk,
but that is not a mounted host filesystem exposed to its agents.

The default inference guest uses 4 vCPUs/6 GiB, and the optional execution guest
2 vCPUs/2 GiB. Ollama is limited to one loaded model and a 4 GiB service budget.
Research processes run as an unprivileged user with bounded memory, time,
process count, disk output and CPU. Network sealing is required after downloads.
Use sequential model loading and retain only useful checkpoints. New-worker
creation requires a 12 GiB host free-space floor.

## Provenance and claims

Runs identify engine, code, models, data and evaluation budgets. Immutable
historical results live under `experiments/baselines`; generated results and
checkpoints live under ignored `experiments/results`. Folder migration does not
rewrite historical JSONL or reinterpret a planner trace as a model trajectory.

Improving a tiny policy baseline is not evidence that Ollama weights changed.
Few-shot context adaptation is not weight training. A language-model distillation
claim requires a trained checkpoint imported into Ollama, a new model digest,
and fixed-budget evaluation against the untrained model. Candidate selection
uses validation only; sealed held-out results are downstream of selection.
