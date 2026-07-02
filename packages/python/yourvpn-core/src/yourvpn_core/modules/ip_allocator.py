from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Iterable

from yourvpn_core.modules.errors import IpPoolExhaustedError


@dataclass(frozen=True)
class RevokedIp:
    ip: str
    cooldown_until: datetime


class IpAllocatorModule:
    def allocate_for_device(
        self,
        *,
        vpn_cidr: str = "10.77.0.0/20",
        server_ip: str = "10.77.0.1",
        allocated_ips: Iterable[str] = (),
        revoked_ips: Iterable[RevokedIp] = (),
        now: datetime | None = None,
    ) -> str:
        network = ipaddress.ip_network(vpn_cidr, strict=False)
        server_address = ipaddress.ip_address(server_ip)
        used = {ipaddress.ip_address(value) for value in allocated_ips}
        current_time = now or datetime.now(UTC)
        cooling = {
            ipaddress.ip_address(item.ip)
            for item in revoked_ips
            if item.cooldown_until > current_time
        }

        for candidate in network.hosts():
            if candidate == server_address:
                continue
            if candidate in used or candidate in cooling:
                continue
            return str(candidate)

        raise IpPoolExhaustedError(f"No available IP in {vpn_cidr}")

    def reserve_existing_for_reset(self, existing_vpn_ip: str) -> str:
        return str(ipaddress.ip_address(existing_vpn_ip))
