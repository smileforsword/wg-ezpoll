from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class WgPeerStatus:
    interface: str
    public_key: str
    endpoint: str | None
    allowed_ips: tuple[str, ...]
    latest_handshake_epoch: int | None
    transfer_rx_bytes: int
    transfer_tx_bytes: int
    persistent_keepalive_seconds: int | None


def _none_if_placeholder(value: str) -> str | None:
    return None if value in {"", "(none)", "off"} else value


def _int_or_none(value: str) -> int | None:
    if value in {"", "0", "off"}:
        return None
    return int(value)


def parse_wg_show_dump(dump_text: str) -> tuple[WgPeerStatus, ...]:
    """Parse `wg show all dump` output.

    The dump format is intentionally preferred over human-readable `wg show`
    because it is stable enough for automated sampling.
    """
    peers: list[WgPeerStatus] = []
    for raw_line in dump_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        parts = line.split("\t")
        if len(parts) == 5:
            # Interface line:
            # interface private-key public-key listen-port fwmark
            continue
        if len(parts) != 9:
            raise ValueError(f"Unsupported wg dump line with {len(parts)} fields: {raw_line!r}")

        (
            interface,
            public_key,
            _preshared_key,
            endpoint,
            allowed_ips,
            latest_handshake,
            transfer_rx,
            transfer_tx,
            persistent_keepalive,
        ) = parts

        peers.append(
            WgPeerStatus(
                interface=interface,
                public_key=public_key,
                endpoint=_none_if_placeholder(endpoint),
                allowed_ips=tuple() if allowed_ips == "(none)" else tuple(allowed_ips.split(",")),
                latest_handshake_epoch=_int_or_none(latest_handshake),
                transfer_rx_bytes=int(transfer_rx),
                transfer_tx_bytes=int(transfer_tx),
                persistent_keepalive_seconds=_int_or_none(persistent_keepalive),
            )
        )
    return tuple(peers)


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse wg show all dump output as JSON.")
    parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=Path(__file__).with_name("samples") / "wg-show-all.dump",
    )
    args = parser.parse_args()

    peers = parse_wg_show_dump(args.path.read_text(encoding="utf-8"))
    print(json.dumps([asdict(peer) for peer in peers], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
