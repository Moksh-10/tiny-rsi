#!/bin/bash
# Trusted provisioning/training control plane. Model output never selects these commands.
set -euo pipefail
ROOT=${GAME_LAB_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}
if [[ ${GAME_LAB_SNAPSHOT:-0} != 1 ]]; then
  SCRIPT=$(cat "$0")
  exec env GAME_LAB_ROOT="$ROOT" GAME_LAB_SNAPSHOT=1 /bin/bash -c "$SCRIPT" -- "$@"
fi
export LIMA_HOME="$ROOT/.workers/lima"
VM=game-worker
case ${1:-help} in
 setup)
  FREE_KIB=$(df -Pk "$ROOT" | awk 'NR==2 {print $4}')
  [[ $FREE_KIB -ge 20971520 ]] || { echo 'Need 20 GiB free before training provisioning' >&2; exit 1; }
  limactl copy "$ROOT/config/training.json" "$VM:/tmp/tiny-rsi-training.json"
  limactl shell "$VM" sudo bash -s <<'GUEST'
set -euo pipefail
if systemctl is-active --quiet game-rollout.service || systemctl list-units --state=running --no-legend 'game-lab-*' 'game-training-*' | grep . >/dev/null; then
 echo 'An agent/training job is active; maintenance refused' >&2;exit 1
fi
rm -f /run/game-research/sealed
if nft list table inet game_research >/dev/null 2>&1; then nft delete table inet game_research; fi
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get -o DPkg::Lock::Timeout=180 install -y python3-venv git cmake build-essential
install -d -m 0755 /opt/game-research/training /var/lib/game-research/models
install -m 0444 /tmp/tiny-rsi-training.json /opt/game-research/training/config.json
rm /tmp/tiny-rsi-training.json
if test -f /etc/game-research/registry-ca.pem; then
 export SSL_CERT_FILE=/etc/game-research/registry-ca.pem
 export REQUESTS_CA_BUNDLE=$SSL_CERT_FILE
 export PIP_CERT=$SSL_CERT_FILE
fi
export PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1 HF_HUB_DISABLE_TELEMETRY=1
python3 -m venv /opt/game-research/training/venv
PY=/opt/game-research/training/venv/bin/python
printf 'torch==2.11.0+cpu\n' > /opt/game-research/training/cpu-constraints.txt
$PY -m pip install --dry-run --report /opt/game-research/training/torch-plan.json --index-url https://download.pytorch.org/whl/cpu 'torch==2.11.0+cpu'
$PY - <<'PYCPU'
import json
plan=json.load(open('/opt/game-research/training/torch-plan.json'))
for item in plan['install']:
 name=item['metadata']['name'].lower()
 if any(bad in name for bad in ('nvidia','cuda','triton')):raise SystemExit('Unexpected GPU dependency: '+name)
PYCPU
$PY -m pip install --index-url https://download.pytorch.org/whl/cpu 'torch==2.11.0+cpu'
$PY -m pip install --dry-run --report /opt/game-research/training/hf-plan.json -c /opt/game-research/training/cpu-constraints.txt 'transformers==5.24.0' 'peft==0.22.0' 'accelerate==1.16.0' 'safetensors==0.8.0'
$PY - <<'PYCPU'
import json
plan=json.load(open('/opt/game-research/training/hf-plan.json'))
for item in plan['install']:
 name=item['metadata']['name'].lower()
 if any(bad in name for bad in ('nvidia','cuda','triton')):raise SystemExit('Unexpected GPU dependency: '+name)
PYCPU
$PY -m pip install -c /opt/game-research/training/cpu-constraints.txt 'transformers==5.24.0' 'peft==0.22.0' 'accelerate==1.16.0' 'safetensors==0.8.0'
$PY -m pip freeze > /opt/game-research/training/requirements-resolved.txt
$PY - <<'PYSMOKE'
import torch,transformers,peft,accelerate,safetensors,json
assert torch.version.cuda is None, 'CPU-only PyTorch is required'
print(json.dumps({m.__name__:m.__version__ for m in (torch,transformers,peft,accelerate,safetensors)}))
PYSMOKE
$PY - <<'PYMODEL'
import hashlib,json,pathlib
from huggingface_hub import snapshot_download
config=json.load(open('/opt/game-research/training/config.json'))
base=config['base'];path='/var/lib/game-research/models/qwen2.5-0.5b-hf'
snapshot_download(base['repository'],revision=base['revision'],local_dir=path,
 allow_patterns=['*.json','*.safetensors','*.txt','*.model','*.tiktoken','LICENSE','README.md'])
weights=pathlib.Path(path)/'model.safetensors';h=hashlib.sha256()
with weights.open('rb') as source:
 for block in iter(lambda:source.read(1024*1024),b''):h.update(block)
if h.hexdigest()!=base['weights_sha256']:raise SystemExit('Pinned model weights digest mismatch')
(pathlib.Path(path)/'tiny-rsi-provenance.json').write_text(json.dumps(base,sort_keys=True))
print('Pinned 0.5B source model verified:',h.hexdigest())
PYMODEL
TOOLS=/opt/game-research/training/llama.cpp
COMMIT=$($PY -c "import json;print(json.load(open('/opt/game-research/training/config.json'))['converter_commit'])")
if ! test -d "$TOOLS/.git"; then git init "$TOOLS";git -C "$TOOLS" remote add origin https://github.com/ggml-org/llama.cpp.git;fi
git -C "$TOOLS" fetch --depth 1 origin "$COMMIT"
git -C "$TOOLS" checkout --detach "$COMMIT"
cmake -S "$TOOLS" -B "$TOOLS/build" -DCMAKE_BUILD_TYPE=Release -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF -DLLAMA_CURL=OFF -DGGML_OPENMP=OFF -DGGML_NATIVE=OFF
cmake --build "$TOOLS/build" --target llama-quantize --parallel 2
$PY -m pip install --no-deps "$TOOLS/gguf-py"
$PY "$TOOLS/convert_hf_to_gguf.py" --help >/dev/null
chmod -R go-w /opt/game-research/training /var/lib/game-research/models
printf 'Training toolchain provisioned; reseal before any agent or training run.\n'
GUEST
  ;;
 *) echo 'Usage: training.sh setup' ;;
esac
