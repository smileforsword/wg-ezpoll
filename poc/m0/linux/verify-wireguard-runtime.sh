#!/usr/bin/env bash
set -euo pipefail

IFACE="${WG_POC_INTERFACE:-wg-m0-poc}"
TABLE="${NFT_TABLE:-yourvpn_m0}"
WG_PORT="${WG_POC_PORT:-51829}"
TMP_NFT="$(mktemp)"

cleanup() {
  rm -f "${TMP_NFT}"
  if ip link show "${IFACE}" >/dev/null 2>&1; then
    ip link delete dev "${IFACE}" >/dev/null 2>&1 || true
  fi
  if nft list table ip "${TABLE}" >/dev/null 2>&1; then
    nft delete table ip "${TABLE}" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root or with equivalent network capabilities." >&2
  exit 2
fi

if [[ "${TABLE}" == "yourvpn" && "${ALLOW_YOURVPN_TABLE_REPLACE:-}" != "1" ]]; then
  echo "Refusing to replace table 'yourvpn' without ALLOW_YOURVPN_TABLE_REPLACE=1." >&2
  exit 2
fi

command -v ip >/dev/null
command -v wg >/dev/null
command -v nft >/dev/null

if nft list table ip "${TABLE}" >/dev/null 2>&1; then
  nft delete table ip "${TABLE}"
fi

server_private="$(wg genkey)"
peer_private="$(wg genkey)"
peer_public="$(printf '%s' "${peer_private}" | wg pubkey)"

ip link add dev "${IFACE}" type wireguard
wg set "${IFACE}" private-key <(printf '%s' "${server_private}") listen-port "${WG_PORT}"
ip address add 10.77.0.1/20 dev "${IFACE}"
ip link set up dev "${IFACE}"

wg set "${IFACE}" peer "${peer_public}" allowed-ips 10.77.0.2/32
wg show "${IFACE}" dump
wg set "${IFACE}" peer "${peer_public}" remove
if wg show "${IFACE}" dump | grep -q "${peer_public}"; then
  echo "Peer removal failed." >&2
  exit 1
fi

cat >"${TMP_NFT}" <<EOF
table ip ${TABLE} {
  chain forward {
    type filter hook forward priority filter; policy accept;
    iifname "${IFACE}" ip saddr 10.77.0.2 ip daddr { 10.20.0.0/16, 10.30.0.0/16 } counter accept
    iifname "${IFACE}" ip saddr 10.77.0.2 counter drop
  }

  chain postrouting {
    type nat hook postrouting priority srcnat; policy accept;
    iifname "${IFACE}" oifname "eth0" masquerade
  }
}
EOF

nft -f "${TMP_NFT}"
nft list table ip "${TABLE}"

echo "M0 WireGuard/nftables runtime probe succeeded on interface ${IFACE}, table ${TABLE}."
