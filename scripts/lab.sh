#!/bin/bash
# Trusted host launcher. Every research command executes inside a sealed Linux VM.
set -euo pipefail
ROOT=${GAME_LAB_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}
# Read the whole trusted launcher before running: edits cannot corrupt active jobs.
if [[ ${GAME_LAB_SNAPSHOT:-0} != 1 ]]; then
  SCRIPT=$(cat "$0")
  exec env GAME_LAB_ROOT="$ROOT" GAME_LAB_SNAPSHOT=1 /bin/bash -c "$SCRIPT" -- "$@"
fi
export LIMA_HOME="$ROOT/.workers/lima"
ROLE=${2:-inference}
case "$ROLE" in
 inference) VM=game-worker ;;
 execution) VM=game-execution ;;
 *) echo 'role must be inference or execution' >&2; exit 2 ;;
esac
case ${1:-help} in
 start)
  # Two guests reserve 8 GiB total. Keep at least 12 GiB free disk before a new guest.
  FREE_KIB=$(df -Pk "$ROOT" | awk 'NR==2 {print $4}')
  [[ $FREE_KIB -ge 12582912 ]] || { echo 'Less than 12 GiB free; refusing new worker' >&2; exit 1; }
  if limactl list --format '{{.Name}}' | grep -x "$VM" >/dev/null; then limactl start --tty=false "$VM";
  elif [[ $ROLE = execution ]]; then limactl start --name="$VM" --tty=false "$ROOT/sandbox/lima/execution.yaml";
  else "$ROOT/scripts/worker.sh" start; fi
  ;;
 stage)
  # Explicit source transfer for development. Archives contain only research modules and boundary scripts.
  BUNDLE=$(mktemp /tmp/game-lab.XXXXXX)
  trap 'rm -f "$BUNDLE"' EXIT
  python3 - "$ROOT" "$BUNDLE" <<'PY'
import hashlib,json,pathlib,sys,tarfile,io
root=pathlib.Path(sys.argv[1])
snapshot={str(pathlib.Path('tiny_rsi')/p.name):p.read_bytes() for p in sorted((root/'research/src/tiny_rsi').glob('*.py'))}
for name in ('seal.sh','verify.sh'):
 snapshot[str(pathlib.Path('sandbox')/name)]=(root/'sandbox/scripts'/name).read_bytes()
snapshot['config/models.json']=(root/'config/models.json').read_bytes()
manifest={name:hashlib.sha256(raw).hexdigest() for name,raw in snapshot.items()}
with tarfile.open(sys.argv[2],'w') as archive:
 for name,raw in snapshot.items():
  item=tarfile.TarInfo(name);item.size=len(raw);item.mode=0o644;archive.addfile(item,io.BytesIO(raw))
 raw=json.dumps(manifest,sort_keys=True).encode();item=tarfile.TarInfo('source-manifest.json');item.size=len(raw);item.mode=0o444
 archive.addfile(item,io.BytesIO(raw))
PY
  limactl copy "$BUNDLE" "$VM:/tmp/game-lab.tar"
  limactl shell "$VM" sudo bash -s <<'GUEST'
set -euo pipefail
if systemctl list-units --state=running --no-legend 'game-lab-*' | grep . >/dev/null; then echo 'Research job active; cannot change its source' >&2; exit 1; fi
mkdir -p /opt/game-research/lab
tar -xf /tmp/game-lab.tar -C /opt/game-research/lab
rm /tmp/game-lab.tar
chown -R root:root /opt/game-research/lab
chmod -R go-w /opt/game-research/lab
bash /opt/game-research/lab/sandbox/seal.sh
GUEST
  ;;
 run)
  MODULE=${3:?module required}; shift 3
  case "$MODULE" in planner|evaluation|policy|policy_experiments|researcher|actor) ;; *) echo 'unsupported research entry point' >&2; exit 2;; esac
  limactl shell "$VM" sudo bash /opt/game-research/lab/sandbox/verify.sh "$ROLE"
  UNIT="game-lab-${MODULE}-$(date +%s)-$$"
  limactl shell "$VM" sudo systemd-run --unit="$UNIT" --wait --pipe --collect \
    -p User=researcher -p Group=researcher -p WorkingDirectory=/opt/game-research/lab \
    --setenv=TINY_RSI_MODEL_CONFIG=/opt/game-research/lab/config/models.json \
    -p NoNewPrivileges=yes -p ProtectSystem=strict -p ProtectHome=yes -p PrivateTmp=yes \
    -p ReadWritePaths=/var/lib/game-research/results -p MemoryMax=768M -p TasksMax=64 \
    -p CPUQuota=200% -p RuntimeMaxSec=3600 -p LimitFSIZE=67108864 \
    -p RestrictSUIDSGID=yes -p CapabilityBoundingSet= \
    /usr/bin/python3 -B -m "tiny_rsi.$MODULE" "$@"
  ;;
 export)
  NAME=${3:?result filename required}
  [[ $NAME =~ ^[a-zA-Z0-9._-]+$ ]] || exit 2
  mkdir -p "$ROOT/experiments/results"
  limactl shell "$VM" sudo cat "/var/lib/game-research/results/$NAME" > "$ROOT/experiments/results/$NAME"
  ;;
 stop) limactl stop "$VM" ;;
 *) echo 'Usage: lab.sh start|stage|run|export|stop inference|execution [module|filename] [args...]' ;;
esac
