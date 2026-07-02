from __future__ import annotations

import ipaddress
import shlex
from typing import Sequence


def build_apply_peer_command(
    *,
    interface: str,
    public_key: str,
    vpn_ip: str,
    allowed_ips: Sequence[str],
) -> list[str]:
    ipaddress.ip_address(vpn_ip)
    normalized_allowed = [str(ipaddress.ip_network(value, strict=False)) for value in allowed_ips]
    return [
        "wg",
        "set",
        interface,
        "peer",
        public_key,
        "allowed-ips",
        ",".join(normalized_allowed),
    ]


def build_remove_peer_command(*, interface: str, public_key: str) -> list[str]:
    return ["wg", "set", interface, "peer", public_key, "remove"]


def shell_join(command: Sequence[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)
