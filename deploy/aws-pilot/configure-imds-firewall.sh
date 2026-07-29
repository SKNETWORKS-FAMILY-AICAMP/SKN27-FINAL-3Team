#!/usr/bin/env bash
set -euo pipefail

for _attempt in $(seq 1 30); do
  if iptables -n -L DOCKER-USER >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
iptables -n -L DOCKER-USER >/dev/null

metadata_cidr="169.254.169.254/32"
caddy_uid="10001"
iptables -C DOCKER-USER -d "$metadata_cidr" -j REJECT 2>/dev/null || \
  iptables -I DOCKER-USER 1 -d "$metadata_cidr" -j REJECT
for allowed_cidr in 172.31.0.5/32 172.31.0.6/32 172.31.0.7/32; do
  iptables -C DOCKER-USER -s "$allowed_cidr" -d "$metadata_cidr" -j ACCEPT 2>/dev/null || \
    iptables -I DOCKER-USER 1 -s "$allowed_cidr" -d "$metadata_cidr" -j ACCEPT
done
iptables -C OUTPUT -m owner --uid-owner "$caddy_uid" -d "$metadata_cidr" -j REJECT 2>/dev/null || \
  iptables -I OUTPUT 1 -m owner --uid-owner "$caddy_uid" -d "$metadata_cidr" -j REJECT
