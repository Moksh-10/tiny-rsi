# Two-game agent research platform

This repository contains Slingshot Valley (C++20 / Box2D) and The Ascent
(C++17 custom climbing physics), plus a guest-only Go actor using the Ollama API.
The initial evaluation track is **structured state**, not screenshots. Inference
and agent gameplay run inside a Linux VM. There is no weight training yet.

## Quick start: Apple Silicon macOS

Prerequisites: Git, CMake, a C++ compiler, Go >=1.22, Python >=3.9, Lima >=2.3.
`brew install lima` installs the VM manager. Expect several GB of downloads.
The default guest reserves 4 vCPUs, 6 GiB RAM and a 24 GiB virtual disk.

From the repository root, after committing the revision to deploy:

```sh
agent/scripts/worker.sh start
agent/scripts/worker.sh deploy
agent/scripts/worker.sh pull
agent/scripts/worker.sh seal
agent/scripts/worker.sh run angry-birds 32
agent/scripts/worker.sh run getting-over-it 32
agent/scripts/worker.sh stop
```

`MODEL=qwen2.5:3b` is the default. Set `MODEL` on both `pull` and `run` to try
another Ollama model. It must support text generation and schema-constrained
JSON well enough to produce valid actions. The runner detects installed models,
records their digests/capabilities, and rejects unavailable models. It does not
promise that every Ollama model can play effectively. No cloud API key is used.

`deploy` sends a Git archive of a clean committed revision, without `.git`,
credentials, build caches or live host mounts. Source/binaries remain root-owned
inside the guest. `pull` is a trusted maintenance operation that opens guest
egress; `seal` must be run again before gameplay. Do not deploy or pull during a
rollout. The marker is an operational prerequisite, not a proof against a
malicious guest administrator. The trusted host launcher and guest root remain
part of the trust boundary.

The model-facing action schema is state-dependent and offers tick choices 15,
30, 60 and 120; the underlying environment accepts every integer 1–120.
Model-facing geometry is rounded to 0.001 units to reduce prompt cost; logs and
replays preserve full engine precision. For a level other than zero, use e.g.
`agent/scripts/worker.sh run angry-birds 32 5`.

Each episode has decision, token, wall-time, action-size and simulation-time
limits. Five rejected actions stop an episode. Defaults: 32 decisions, 30,000
prompt-plus-output tokens, 20 minutes, 120 ticks per action, 18,000 ticks total.
A conservative preflight reserves prompt/output capacity; a completed API call
can still cross the total token limit, after which the runner stops. There is
one in-flight call. Ollama context is limited to 8192 tokens and output to 256.

## Isolation

Lima uses Apple Virtualization.framework (VZ) on this Mac; Lima is open source,
while the Apple framework is part of macOS. This is a VM with its own Linux
kernel, not a container sharing the host kernel. Firecracker is a future Linux
KVM deployment backend, not a macOS dependency.

The project-specific `.workers/lima` directory avoids personal Lima defaults.
The template disables host mounts, application port forwards, SSH-agent/X11
forwarding, automatic public-key imports, proxy propagation, host DNS resolution
and host-loopback services. Source transfer is explicit, over management SSH.
After provisioning/model download, the guest nftables policy drops new external
traffic and permits only loopback and inbound SSH with established SSH replies.
The model API listens only on guest loopback. No model endpoint is exposed to
macOS. `verify.sh` checks the guest boundary before each launch.

The actor is a dedicated `researcher` user without sudo, invoked through a
restricted systemd unit: read-only system/home protection, a private temporary
directory, no capabilities or privilege escalation, a 512 MiB actor memory
limit, one CPU quota, 64 tasks, a 64 MiB file-size limit and a 25-minute service
limit. Ollama is a separate unprivileged guest service with a 4 GiB memory limit.
Only the results directory is writable to the actor. The model has no shell,
filesystem or arbitrary process tool. The C++ subprocess path is operator
configuration, never a model-selected path.

VMs reduce exposure but are not an absolute security guarantee. No GPU is
passed through; inference is guest CPU inference and can be slower than native
Metal. Start with one guest; measure memory/latency before parallel workers.

### TLS-intercepting networks

Do not disable certificate verification. If the model registry uses a private
CA already trusted by your host, explicitly transfer **only that public CA**
into the guest. Append it to a copy of the normal system CA bundle at
`/etc/game-research/registry-ca.pem`; set `SSL_CERT_FILE` for the guest Ollama
service through a systemd drop-in, then restart it. Do not transfer host private
keys, trust stores containing credentials, or SSH agents. This deployment used
a verified macOS-trusted public proxy CA; it is not committed to this repository.

## Build and test without graphics

Development unit tests do not invoke a model:

```sh
cmake -S . -B build-headless -DGAMES_BUILD_UI=OFF -DCMAKE_BUILD_TYPE=Release
cmake --build build-headless --parallel 4
ctest --test-dir build-headless --output-on-failure
(cd agent && go test -race ./... && go vet ./...)
```

The normal root CMake build still builds both native apps, reusing one raylib
instance. The imported project's standalone build also remains supported.
See [protocol.md](protocol.md) for the game interface and reward definitions.

## Trajectories and reproducibility

Guest results live in `/var/lib/game-research/results`; the launcher exports the
completed episode to ignored `agent/results` on the host. Existing files are
never overwritten. JSONL records include the game revision, Ollama model digest,
model capabilities, game/level, structured-state track, action responses,
prompt/output counts, durations, rejected actions, end reason and final state.
They contain no hidden chain-of-thought. Model output is untrusted data.

Replay inside the guest with the same deployed revision:

```sh
python3 /opt/game-research/current/agent/scripts/replay.py \
  /var/lib/game-research/results/EPISODE.jsonl \
  --env /opt/game-research/build/game-env
```

Physics is deterministic for a fixed engine/build/action sequence; cross-platform
floating-point results may differ. Replay comparison has small float tolerance.
The current levels/terrain are fixed; there is no pretend random seed or
procedural variation. Held-out evaluation needs explicit level splits and future
versioned terrain variations.

## Research direction

The next stages are bounded parallel VM workers, an idiomatic Gymnasium adapter,
a baseline evaluation suite with locked level splits, teacher demonstrations,
then Python/PyTorch student training. The sequence is data -> teacher labels ->
student checkpoint -> held-out evaluation -> gated promotion. Repeated inference
does not update weights. A researcher agent must not edit rewards, the evaluator
or held-out tasks. Compare win/progress, invalid actions, tokens, latency, peak
memory and training compute at fixed budgets before claiming improvement.

References informing the design:

- [Gymnasium step/reset and termination semantics](https://gymnasium.farama.org/introduction/basic_usage/)
- [Ollama structured outputs](https://docs.ollama.com/capabilities/structured-outputs)
- [OpenAI VPT: demonstrations and subsequent learning](https://openai.com/index/vpt/)
- [DeepMind SIMA: visual gameplay agents](https://deepmind.google/discover/blog/sima-generalist-ai-agent-for-3d-virtual-environments/)
- [Lima security](https://lima-vm.io/docs/security/)
- [Firecracker Linux/KVM requirements](https://github.com/firecracker-microvm/firecracker/blob/main/docs/getting-started.md)

Context7 was consulted for Ollama API behavior; Exa was unavailable in the
connected tools during planning. These references inform the architecture;
this first milestone does not reproduce frontier-scale training results.
