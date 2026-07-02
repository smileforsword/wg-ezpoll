from __future__ import annotations

from pathlib import Path

from poc.m0.wg_commands import build_apply_peer_command, build_remove_peer_command, shell_join
from poc.m0.wg_show_parser import parse_wg_show_dump


def test_parse_wg_show_all_dump_sample() -> None:
    peers = parse_wg_show_dump(Path("poc/m0/samples/wg-show-all.dump").read_text(encoding="utf-8"))

    assert len(peers) == 2
    assert peers[0].interface == "wg0"
    assert peers[0].endpoint == "198.51.100.20:53000"
    assert peers[0].allowed_ips == ("10.77.0.2/32",)
    assert peers[0].latest_handshake_epoch == 1780000000
    assert peers[0].transfer_rx_bytes == 1024
    assert peers[0].transfer_tx_bytes == 2048
    assert peers[1].endpoint is None
    assert peers[1].latest_handshake_epoch is None


def test_wg_command_shape_is_explicit() -> None:
    apply_command = build_apply_peer_command(
        interface="wg0",
        public_key="peer",
        vpn_ip="10.77.0.2",
        allowed_ips=["10.77.0.2/32"],
    )
    remove_command = build_remove_peer_command(interface="wg0", public_key="peer")

    assert apply_command == ["wg", "set", "wg0", "peer", "peer", "allowed-ips", "10.77.0.2/32"]
    assert shell_join(remove_command) == "wg set wg0 peer peer remove"
