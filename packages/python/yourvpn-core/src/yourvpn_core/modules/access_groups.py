from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class AccessGroupRoute:
    access_group_id: str
    cidr: str
    enabled: bool = True


@dataclass(frozen=True)
class FirewallTarget:
    source_vpn_ip: str
    destination_cidr: str


class AccessGroupModule:
    def compile_allowed_ips(self, routes: Iterable[AccessGroupRoute]) -> list[str]:
        networks = self._compile_networks(routes)
        return [str(network) for network in networks]

    def compile_firewall_targets(
        self,
        *,
        device_vpn_ip: str,
        routes: Iterable[AccessGroupRoute],
    ) -> list[FirewallTarget]:
        networks = self._compile_networks(routes)
        source = str(ipaddress.ip_address(device_vpn_ip))
        return [FirewallTarget(source_vpn_ip=source, destination_cidr=str(network)) for network in networks]

    def _compile_networks(self, routes: Iterable[AccessGroupRoute]) -> list[ipaddress.IPv4Network]:
        networks = {
            ipaddress.ip_network(route.cidr, strict=False)
            for route in routes
            if route.enabled
        }
        ipv4_networks = [network for network in networks if isinstance(network, ipaddress.IPv4Network)]
        return sorted(ipv4_networks, key=lambda network: (int(network.network_address), network.prefixlen))
