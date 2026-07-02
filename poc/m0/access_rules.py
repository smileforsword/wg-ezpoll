from __future__ import annotations

import argparse
import ipaddress
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


@dataclass(frozen=True)
class AccessGroup:
    name: str
    routes: tuple[ipaddress.IPv4Network, ...]


@dataclass(frozen=True)
class PeerRule:
    public_key: str
    vpn_ip: ipaddress.IPv4Address
    allowed_ips: tuple[ipaddress.IPv4Network, ...]


def _network_sort_key(network: ipaddress.IPv4Network) -> tuple[int, int]:
    return int(network.network_address), network.prefixlen


def normalize_ipv4_networks(cidr_values: Iterable[str]) -> tuple[ipaddress.IPv4Network, ...]:
    """Deduplicate exact CIDRs while preserving a deterministic order.

    V1 deliberately avoids complex CIDR minimization during M0/M2. Overlapping
    networks are kept as-is so admin intent remains visible.
    """
    networks = {ipaddress.ip_network(value, strict=False) for value in cidr_values}
    ipv4_networks = [network for network in networks if isinstance(network, ipaddress.IPv4Network)]
    return tuple(sorted(ipv4_networks, key=_network_sort_key))


def load_access_groups(path: Path) -> tuple[AccessGroup, ...]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    groups = []
    for item in raw["access_groups"]:
        groups.append(
            AccessGroup(
                name=item["name"],
                routes=normalize_ipv4_networks(item["routes"]),
            )
        )
    return tuple(groups)


def compile_allowed_ips(groups: Sequence[AccessGroup]) -> tuple[ipaddress.IPv4Network, ...]:
    return normalize_ipv4_networks(str(route) for group in groups for route in group.routes)


def format_allowed_ips(networks: Sequence[ipaddress.IPv4Network]) -> str:
    return ", ".join(str(network) for network in networks)


def render_nftables_table(
    peers: Sequence[PeerRule],
    *,
    table_name: str = "yourvpn",
    wg_interface: str = "wg0",
    outbound_interface: str = "eth0",
    enable_masquerade: bool = True,
) -> str:
    """Render an IPv4 nftables table owned exclusively by WirePortal.

    The rendered content intentionally contains only one table. Replacement is
    handled by the caller so wg-agent can avoid touching unrelated host rules.
    """
    lines = [
        f"table ip {table_name} {{",
        "  chain forward {",
        "    type filter hook forward priority filter; policy accept;",
    ]

    for peer in peers:
        allowed = format_allowed_ips(peer.allowed_ips)
        if allowed:
            lines.append(
                f'    iifname "{wg_interface}" ip saddr {peer.vpn_ip} ip daddr {{ {allowed} }} counter accept'
            )
        lines.append(f'    iifname "{wg_interface}" ip saddr {peer.vpn_ip} counter drop')

    lines.extend(
        [
            "  }",
            "",
            "  chain postrouting {",
            "    type nat hook postrouting priority srcnat; policy accept;",
        ]
    )

    if enable_masquerade:
        lines.append(f'    iifname "{wg_interface}" oifname "{outbound_interface}" masquerade')

    lines.extend(["  }", "}"])
    return "\n".join(lines) + "\n"


def build_sample_peer(groups: Sequence[AccessGroup]) -> PeerRule:
    return PeerRule(
        public_key="m0samplepublickey000000000000000000000000000=",
        vpn_ip=ipaddress.ip_address("10.77.0.2"),
        allowed_ips=compile_allowed_ips(groups),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Render M0 access-group AllowedIPs and nftables samples.")
    parser.add_argument(
        "--input",
        type=Path,
        default=Path(__file__).with_name("samples") / "access-groups.json",
        help="Access-group sample JSON.",
    )
    parser.add_argument("--table-name", default="yourvpn", help="nftables table name.")
    parser.add_argument("--wg-interface", default="wg0", help="WireGuard interface name.")
    parser.add_argument("--outbound-interface", default="eth0", help="Outbound interface for masquerade.")
    args = parser.parse_args()

    groups = load_access_groups(args.input)
    peer = build_sample_peer(groups)

    print("# AllowedIPs")
    print(format_allowed_ips(peer.allowed_ips))
    print()
    print("# nftables")
    print(
        render_nftables_table(
            [peer],
            table_name=args.table_name,
            wg_interface=args.wg_interface,
            outbound_interface=args.outbound_interface,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
