#!/bin/bash
# Trusted host control plane; the actor and inference never run on macOS.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
export LIMA_HOME="$ROOT/.workers/lima"
VM=game-worker
MODEL=${MODEL:-qwen2.5:3b}
case ${1:-help} in
 start)
  mkdir -p "$LIMA_HOME"
  if limactl list --format '{{.Name}}' | grep -qx "$VM"; then
    limactl start --tty=false "$VM"
  else
    limactl start --name="$VM" --tty=false "$ROOT/agent/sandbox/lima.yaml"
  fi
  ;;
 deploy)
  # Commit first: transfer a credential-free, immutable source snapshot, not the working directory.
  if [[ -n $(git -C "$ROOT" status --porcelain) ]]; then echo 'Commit changes before deploy' >&2; exit 1; fi
  REV=$(git -C "$ROOT" rev-parse HEAD)
  BUNDLE=$(mktemp /tmp/game-research.XXXXXX)
  trap 'rm -f "$BUNDLE"' EXIT
  git -C "$ROOT" archive HEAD > "$BUNDLE"
  limactl copy "$BUNDLE" "$VM:/tmp/game-research.tar"
  limactl shell "$VM" sudo bash -s -- "$REV" <<'GUEST'
set -euo pipefail
REV=$1
if systemctl is-active --quiet game-rollout.service; then echo "Rollout active" >&2; exit 1; fi
rm -f /run/game-research/sealed
if nft list table inet game_research >/dev/null 2>&1; then nft delete table inet game_research; fi
mkdir -p /opt/game-research/releases
mkdir -p "/opt/game-research/releases/$REV"
tar -xf /tmp/game-research.tar -C "/opt/game-research/releases/$REV"
rm /tmp/game-research.tar
ln -sfn "/opt/game-research/releases/$REV" /opt/game-research/current
cd /opt/game-research/current
cmake -S . -B build -DGAMES_BUILD_UI=OFF -DCMAKE_BUILD_TYPE=Release
cmake --build build --parallel 4
ctest --test-dir build --output-on-failure
cd agent
go test ./...
go build -trimpath -ldflags "-X main.revision=$REV" -o /opt/game-research/game-agent ./cmd/game-agent
ln -sfn "/opt/game-research/current/build" /opt/game-research/build
GUEST
  ;;
 pull)
  # Maintenance mode only, never concurrent with a running rollout.
  limactl shell "$VM" sudo bash -s -- "$MODEL" <<'GUEST'
set -euo pipefail
if systemctl is-active --quiet game-rollout.service; then echo 'Rollout active' >&2; exit 1; fi
rm -f /run/game-research/sealed
if nft list table inet game_research >/dev/null 2>&1; then nft delete table inet game_research; fi
/usr/bin/ollama pull "$1"
GUEST
  ;;
 seal)
  limactl shell "$VM" sudo bash /opt/game-research/current/agent/sandbox/seal.sh
  limactl shell "$VM" sudo bash /opt/game-research/current/agent/sandbox/verify.sh
  ;;
 run)
  GAME=${2:-angry-birds}
  [[ $GAME = angry-birds || $GAME = getting-over-it ]] || exit 2
  STEPS=${3:-32}
  [[ $STEPS =~ ^[0-9]+$ && $STEPS -ge 1 && $STEPS -le 10000 ]] || exit 2
  limactl shell "$VM" sudo bash /opt/game-research/current/agent/sandbox/verify.sh
  RUN="${GAME}-$(date -u +%Y%m%dT%H%M%SZ)"
  limactl shell "$VM" sudo systemd-run --unit=game-rollout --wait --pipe --collect \
    -p User=researcher -p Group=researcher -p NoNewPrivileges=yes \
    -p ProtectSystem=strict -p ProtectHome=yes -p PrivateTmp=yes \
    -p ReadWritePaths=/var/lib/game-research/results -p MemoryMax=512M \
    -p TasksMax=64 -p CPUQuota=100% -p RuntimeMaxSec=1500 \
    -p LimitFSIZE=67108864 -p RestrictSUIDSGID=yes -p CapabilityBoundingSet= \
    -p RestrictAddressFamilies='AF_UNIX AF_INET AF_INET6' \
    /opt/game-research/game-agent --model "$MODEL" --game "$GAME" --steps "$STEPS" \
    --output "/var/lib/game-research/results/$RUN.jsonl"
  mkdir -p "$ROOT/agent/results"
  limactl shell "$VM" sudo cat "/var/lib/game-research/results/$RUN.jsonl" > "$ROOT/agent/results/$RUN.jsonl"
  echo "Saved $ROOT/agent/results/$RUN.jsonl"
  ;;
 stop) limactl stop "$VM" ;;
 *) echo 'Usage: worker.sh start|deploy|pull|seal|run [angry-birds|getting-over-it] [steps]|stop' ;;
esac
