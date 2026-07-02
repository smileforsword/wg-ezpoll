from __future__ import annotations

import http.client
import ipaddress
import json
import socket
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from yourvpn_core.config import AppSettings
from yourvpn_core.db.models import (
    AccessGroupRoute as DbAccessGroupRoute,
    Device,
    DeviceAccessGroup,
    Job,
    TrafficSnapshot,
)
from yourvpn_core.domain.enums import DeviceStatus, JobStatus
from yourvpn_core.modules.access_groups import AccessGroupModule, AccessGroupRoute
from yourvpn_core.modules.errors import ConflictError, NotFoundError, ValidationError


RUNTIME_TARGET_DEVICE_STATUSES = {
    DeviceStatus.DOWNLOAD_CONFIRMED.value,
    DeviceStatus.ACTIVE.value,
}


@dataclass(frozen=True)
class RuntimePeer:
    device_id: str
    public_key: str
    vpn_ip: str
    allowed_ips: list[str]


@dataclass(frozen=True)
class RuntimeFirewall:
    table_name: str
    family: str
    ruleset: str


@dataclass(frozen=True)
class RuntimeTargetState:
    interface: str
    peers: list[RuntimePeer]
    firewall: RuntimeFirewall


@dataclass(frozen=True)
class WgPeerStatus:
    interface: str
    public_key: str
    endpoint: str | None
    allowed_ips: list[str]
    latest_handshake_epoch: int | None
    transfer_rx_bytes: int
    transfer_tx_bytes: int


@dataclass(frozen=True)
class WgAgentCommandResult:
    argv: list[str]
    exit_code: int
    stdout: str
    stderr: str


class WgAgentClient(Protocol):
    def health(self) -> dict[str, Any]:
        ...

    def status(self) -> list[WgPeerStatus]:
        ...

    def apply_peer(self, *, interface: str, public_key: str, vpn_ip: str, allowed_ips: list[str]) -> dict[str, Any]:
        ...

    def remove_peer(self, *, interface: str, public_key: str) -> dict[str, Any]:
        ...

    def apply_firewall(self, firewall: RuntimeFirewall) -> dict[str, Any]:
        ...

    def reconcile(self, target: RuntimeTargetState) -> dict[str, Any]:
        ...


class UnixSocketHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path: str, timeout: int = 10) -> None:
        super().__init__("wg-agent.local", timeout=timeout)
        self.socket_path = socket_path

    def connect(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(self.socket_path)
        self.sock = sock


class UnixSocketWgAgentClient:
    def __init__(self, socket_path: str, *, timeout: int = 10) -> None:
        self.socket_path = socket_path
        self.timeout = timeout

    def health(self) -> dict[str, Any]:
        return self._request_json("GET", "/health")

    def status(self) -> list[WgPeerStatus]:
        body = self._request_json("GET", "/wg/status")
        return [
            WgPeerStatus(
                interface=item["interface"],
                public_key=item["public_key"],
                endpoint=item.get("endpoint"),
                allowed_ips=list(item.get("allowed_ips", [])),
                latest_handshake_epoch=item.get("latest_handshake_epoch"),
                transfer_rx_bytes=int(item.get("transfer_rx_bytes", 0)),
                transfer_tx_bytes=int(item.get("transfer_tx_bytes", 0)),
            )
            for item in body.get("peers", [])
        ]

    def apply_peer(self, *, interface: str, public_key: str, vpn_ip: str, allowed_ips: list[str]) -> dict[str, Any]:
        return self._request_json(
            "POST",
            "/peers/apply",
            {
                "interface": interface,
                "public_key": public_key,
                "vpn_ip": vpn_ip,
                "allowed_ips": allowed_ips,
            },
        )

    def remove_peer(self, *, interface: str, public_key: str) -> dict[str, Any]:
        return self._request_json(
            "POST",
            "/peers/remove",
            {
                "interface": interface,
                "public_key": public_key,
            },
        )

    def apply_firewall(self, firewall: RuntimeFirewall) -> dict[str, Any]:
        return self._request_json(
            "POST",
            "/firewall/apply",
            {
                "table_name": firewall.table_name,
                "family": firewall.family,
                "ruleset": firewall.ruleset,
            },
        )

    def reconcile(self, target: RuntimeTargetState) -> dict[str, Any]:
        return self._request_json(
            "POST",
            "/reconcile",
            {
                "interface": target.interface,
                "peers": [
                    {
                        "public_key": peer.public_key,
                        "vpn_ip": peer.vpn_ip,
                        "allowed_ips": peer.allowed_ips,
                    }
                    for peer in target.peers
                ],
                "firewall": {
                    "table_name": target.firewall.table_name,
                    "family": target.firewall.family,
                    "ruleset": target.firewall.ruleset,
                },
            },
        )

    def _request_json(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        connection = UnixSocketHTTPConnection(self.socket_path, timeout=self.timeout)
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"content-type": "application/json"} if payload is not None else {}
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        response_body = response.read().decode("utf-8")
        try:
            parsed = json.loads(response_body) if response_body else {}
        finally:
            connection.close()
        if response.status >= 400:
            raise ConflictError(parsed.get("detail") or parsed.get("message") or f"wg-agent HTTP {response.status}")
        return parsed


def render_nftables_table(
    peers: list[RuntimePeer],
    peer_destinations: dict[str, list[str]],
    *,
    table_name: str,
    wg_interface: str,
    outbound_interface: str,
    enable_masquerade: bool,
) -> str:
    _validate_identifier(table_name, "table_name")
    _validate_identifier(wg_interface, "wg_interface")
    _validate_identifier(outbound_interface, "outbound_interface")
    lines = [
        f"table ip {table_name} {{",
        "  chain forward {",
        "    type filter hook forward priority filter; policy accept;",
    ]

    for peer in sorted(peers, key=lambda item: item.vpn_ip):
        ipaddress.ip_address(peer.vpn_ip)
        destinations = _normalize_cidrs(peer_destinations.get(peer.device_id, []))
        if destinations:
            joined_destinations = ", ".join(destinations)
            lines.append(
                f'    iifname "{wg_interface}" ip saddr {peer.vpn_ip} '
                f"ip daddr {{ {joined_destinations} }} counter accept"
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


class WgRuntimeModule:
    def __init__(
        self,
        *,
        access_group_module: AccessGroupModule | None = None,
        client: WgAgentClient | None = None,
    ) -> None:
        self.access_group_module = access_group_module or AccessGroupModule()
        self.client = client

    def build_target_state(self, db: OrmSession, *, settings: AppSettings) -> RuntimeTargetState:
        devices = db.scalars(
            select(Device)
            .where(Device.status.in_(RUNTIME_TARGET_DEVICE_STATUSES))
            .where(Device.public_key.is_not(None))
            .order_by(Device.vpn_ip)
        ).all()
        peers = [
            RuntimePeer(
                device_id=device.id,
                public_key=device.public_key or "",
                vpn_ip=device.vpn_ip,
                allowed_ips=[f"{device.vpn_ip}/32"],
            )
            for device in devices
        ]
        peer_destinations = {
            device.id: self._compile_device_destinations(db, device_id=device.id)
            for device in devices
        }
        firewall = RuntimeFirewall(
            table_name=settings.nft_table_name,
            family="ip",
            ruleset=render_nftables_table(
                peers,
                peer_destinations,
                table_name=settings.nft_table_name,
                wg_interface=settings.wg_interface,
                outbound_interface=settings.outbound_interface,
                enable_masquerade=settings.enable_masquerade,
            ),
        )
        return RuntimeTargetState(interface=settings.wg_interface, peers=peers, firewall=firewall)

    def apply_peer_for_device(
        self,
        db: OrmSession,
        *,
        device_id: str,
        settings: AppSettings,
        client: WgAgentClient | None = None,
    ) -> dict[str, Any]:
        resolved_client = client or self._client(settings)
        device = self._get_runtime_device(db, device_id)
        if not device.public_key:
            raise ConflictError("Device has no public key")
        result = resolved_client.apply_peer(
            interface=settings.wg_interface,
            public_key=device.public_key,
            vpn_ip=device.vpn_ip,
            allowed_ips=[f"{device.vpn_ip}/32"],
        )
        device.status = DeviceStatus.ACTIVE.value
        db.flush()
        return result

    def remove_peer_for_device(
        self,
        db: OrmSession,
        *,
        device_id: str,
        settings: AppSettings,
        client: WgAgentClient | None = None,
    ) -> dict[str, Any]:
        resolved_client = client or self._client(settings)
        device = db.get(Device, device_id)
        if device is None:
            raise NotFoundError("Device not found")
        if not device.public_key:
            raise ConflictError("Device has no public key")
        return resolved_client.remove_peer(interface=settings.wg_interface, public_key=device.public_key)

    def apply_firewall(
        self,
        db: OrmSession,
        *,
        settings: AppSettings,
        client: WgAgentClient | None = None,
    ) -> dict[str, Any]:
        target = self.build_target_state(db, settings=settings)
        return (client or self._client(settings)).apply_firewall(target.firewall)

    def reconcile(
        self,
        db: OrmSession,
        *,
        settings: AppSettings,
        client: WgAgentClient | None = None,
    ) -> dict[str, Any]:
        target = self.build_target_state(db, settings=settings)
        return (client or self._client(settings)).reconcile(target)

    def sample_status(
        self,
        db: OrmSession,
        *,
        settings: AppSettings,
        client: WgAgentClient | None = None,
        now: datetime | None = None,
    ) -> list[TrafficSnapshot]:
        current_time = now or datetime.now(UTC)
        statuses = (client or self._client(settings)).status()
        snapshots: list[TrafficSnapshot] = []
        for status in statuses:
            device = db.scalar(select(Device).where(Device.public_key == status.public_key))
            if device is None:
                continue
            latest_handshake = (
                datetime.fromtimestamp(status.latest_handshake_epoch, tz=UTC)
                if status.latest_handshake_epoch
                else None
            )
            device.latest_endpoint = status.endpoint
            device.latest_handshake_at = latest_handshake
            device.rx_bytes = status.transfer_rx_bytes
            device.tx_bytes = status.transfer_tx_bytes
            snapshot = TrafficSnapshot(
                device_id=device.id,
                sampled_at=current_time,
                rx_bytes=status.transfer_rx_bytes,
                tx_bytes=status.transfer_tx_bytes,
                latest_handshake_at=latest_handshake,
                endpoint=status.endpoint,
            )
            db.add(snapshot)
            snapshots.append(snapshot)
        db.flush()
        return snapshots

    def mark_job_succeeded(self, job: Job) -> None:
        job.status = JobStatus.SUCCEEDED.value
        job.last_error = None

    def mark_job_failed(self, job: Job, error: Exception) -> None:
        job.status = JobStatus.FAILED.value
        job.last_error = str(error)

    def _client(self, settings: AppSettings) -> WgAgentClient:
        return self.client or UnixSocketWgAgentClient(settings.wg_agent_socket_path)

    def _get_runtime_device(self, db: OrmSession, device_id: str) -> Device:
        device = db.get(Device, device_id)
        if device is None:
            raise NotFoundError("Device not found")
        if device.status not in RUNTIME_TARGET_DEVICE_STATUSES:
            raise ConflictError("Device is not ready for runtime apply")
        return device

    def _compile_device_destinations(self, db: OrmSession, *, device_id: str) -> list[str]:
        group_ids = db.scalars(
            select(DeviceAccessGroup.access_group_id).where(DeviceAccessGroup.device_id == device_id)
        ).all()
        if not group_ids:
            return []
        routes = db.scalars(
            select(DbAccessGroupRoute).where(DbAccessGroupRoute.access_group_id.in_(list(group_ids)))
        ).all()
        return self.access_group_module.compile_allowed_ips(
            AccessGroupRoute(
                access_group_id=route.access_group_id,
                cidr=route.cidr,
                enabled=route.enabled,
            )
            for route in routes
        )


def _normalize_cidrs(values: list[str]) -> list[str]:
    networks = {
        ipaddress.ip_network(value, strict=False)
        for value in values
    }
    ipv4_networks = [network for network in networks if isinstance(network, ipaddress.IPv4Network)]
    return [str(network) for network in sorted(ipv4_networks, key=lambda network: (int(network.network_address), network.prefixlen))]


def _validate_identifier(value: str, field_name: str) -> None:
    if not value or not all(character.isalnum() or character in {"_", "-", "."} for character in value):
        raise ValidationError(f"Invalid {field_name}")
