from __future__ import annotations

import ipaddress
from pathlib import Path

from poc.m0.access_rules import (
    AccessGroup,
    PeerRule,
    compile_allowed_ips,
    format_allowed_ips,
    load_access_groups,
    render_nftables_table,
)


def test_access_group_routes_are_deduplicated_without_merging() -> None:
    groups = (
        AccessGroup(
            name="engineering",
            routes=(
                ipaddress.ip_network("10.20.0.0/16"),
                ipaddress.ip_network("10.20.10.0/24"),
            ),
        ),
        AccessGroup(
            name="office",
            routes=(
                ipaddress.ip_network("10.20.0.0/16"),
                ipaddress.ip_network("172.16.30.0/24"),
            ),
        ),
    )

    allowed_ips = compile_allowed_ips(groups)

    assert format_allowed_ips(allowed_ips) == "10.20.0.0/16, 10.20.10.0/24, 172.16.30.0/24"


def test_sample_access_groups_render_yourvpn_table_only() -> None:
    groups = load_access_groups(Path("poc/m0/samples/access-groups.json"))
    allowed_ips = compile_allowed_ips(groups)
    table = render_nftables_table(
        [
            PeerRule(
                public_key="sample",
                vpn_ip=ipaddress.ip_address("10.77.0.2"),
                allowed_ips=allowed_ips,
            )
        ]
    )

    assert table.startswith("table ip yourvpn {")
    assert 'iifname "wg0" ip saddr 10.77.0.2 ip daddr { 10.20.0.0/16, 10.20.10.0/24, 10.30.0.0/16, 172.16.30.0/24 } counter accept' in table
    assert 'iifname "wg0" oifname "eth0" masquerade' in table
    assert "table ip filter" not in table
