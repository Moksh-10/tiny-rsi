#!/bin/bash
set -euo pipefail
[[ $(id -u) = 0 ]]
[[ $(systemd-detect-virt --vm) != none ]]
[[ -z $(findmnt -rn -t virtiofs,9p,fuse.sshfs || true) ]]
[[ $(cat /etc/game-research/worker) = game-research-lima-v1 ]]
[[ $(cat /run/game-research/sealed) = sealed-v1 ]]
[[ $(stat -c %U /run/game-research/sealed) = root ]]
! id -nG researcher | tr ' ' '\n' | grep -E '^(sudo|wheel|docker|lima)$' >/dev/null
! sudo -u researcher sudo -n true 2>/dev/null
[[ ! -S /var/run/docker.sock ]]
[[ ! -d /Users ]]
nft list chain inet game_research output | grep 'policy drop' >/dev/null
nft list chain inet game_research input | grep 'policy drop' >/dev/null
# The actor cannot reach the host gateway, LAN or internet after sealing.
if sudo -u researcher curl --noproxy '*' -fsS --connect-timeout 2 --max-time 3 https://example.com >/dev/null 2>&1; then
  echo 'ERROR: guest egress remains open' >&2; exit 1
fi
curl --noproxy '*' -fsS http://127.0.0.1:11434/api/tags >/dev/null
printf 'VM boundary verified: no host shares; unprivileged actor; egress blocked; guest Ollama ready\n'
