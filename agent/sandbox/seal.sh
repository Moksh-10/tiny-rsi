#!/bin/bash
# Guest root only. Atomic nft transaction; management SSH remains reachable.
set -euo pipefail
if nft list table inet game_research >/dev/null 2>&1; then
  nft delete table inet game_research
fi
nft -f - <<'RULES'
table inet game_research {
 chain input {
  type filter hook input priority 0; policy drop;
  iifname "lo" accept
  ct state established,related accept
  tcp dport 22 accept
 }
 chain output {
  type filter hook output priority 0; policy drop;
  oifname "lo" accept
  tcp sport 22 ct state established accept
 }
 chain forward { type filter hook forward priority 0; policy drop; }
}
RULES
install -d -m 0755 /run/game-research
printf 'sealed-v1\n' > /run/game-research/sealed
chmod 0444 /run/game-research/sealed
