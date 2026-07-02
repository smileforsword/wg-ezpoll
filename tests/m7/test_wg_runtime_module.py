from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session as OrmSession, sessionmaker

from yourvpn_core.config import AppSettings
from yourvpn_core.db import (
    AccessGroup,
    AccessGroupRoute,
    Base,
    Device,
    DeviceAccessGroup,
    Job,
    TrafficSnapshot,
    User,
)
from yourvpn_core.db.session import create_session_factory
from yourvpn_core.domain.enums import DeviceStatus, JobStatus, Role, UserStatus
from yourvpn_core.modules.wg_runtime import RuntimeFirewall, RuntimeTargetState, WgPeerStatus, WgRuntimeModule
from yourvpn_worker.main import run_pending_job_once


@pytest.fixture()
def session_factory(tmp_path: Path) -> sessionmaker[OrmSession]:
    engine = create_engine(f"sqlite:///{(tmp_path / 'm7.sqlite3').as_posix()}", future=True)
    Base.metadata.create_all(engine)
    return create_session_factory(engine)


@dataclass
class FakeWgAgentClient:
    applied_peers: list[dict[str, Any]] = field(default_factory=list)
    removed_peers: list[dict[str, Any]] = field(default_factory=list)
    firewall_payloads: list[RuntimeFirewall] = field(default_factory=list)
    reconcile_payloads: list[RuntimeTargetState] = field(default_factory=list)
    statuses: list[WgPeerStatus] = field(default_factory=list)

    def health(self) -> dict[str, Any]:
        return {"ok": True}

    def status(self) -> list[WgPeerStatus]:
        return self.statuses

    def apply_peer(self, *, interface: str, public_key: str, vpn_ip: str, allowed_ips: list[str]) -> dict[str, Any]:
        payload = {
            "interface": interface,
            "public_key": public_key,
            "vpn_ip": vpn_ip,
            "allowed_ips": allowed_ips,
        }
        self.applied_peers.append(payload)
        return {"ok": True, "operation": "apply_peer"}

    def remove_peer(self, *, interface: str, public_key: str) -> dict[str, Any]:
        payload = {"interface": interface, "public_key": public_key}
        self.removed_peers.append(payload)
        return {"ok": True, "operation": "remove_peer"}

    def apply_firewall(self, firewall: RuntimeFirewall) -> dict[str, Any]:
        self.firewall_payloads.append(firewall)
        return {"ok": True, "operation": "apply_firewall"}

    def reconcile(self, target: RuntimeTargetState) -> dict[str, Any]:
        self.reconcile_payloads.append(target)
        return {"ok": True, "operation": "reconcile"}


def seed_runtime_devices(session_factory: sessionmaker[OrmSession]) -> tuple[str, str]:
    with session_factory() as db:
        user = User(
            email="m7@example.com",
            display_name="M7 User",
            role=Role.USER.value,
            status=UserStatus.ACTIVE.value,
            approved_device_limit=2,
        )
        db.add(user)
        db.flush()
        group = AccessGroup(name="engineering", enabled=True)
        db.add(group)
        db.flush()
        db.add(AccessGroupRoute(access_group_id=group.id, cidr="10.10.0.0/16", enabled=True))
        ready = Device(
            user_id=user.id,
            name="Ready",
            status=DeviceStatus.DOWNLOAD_CONFIRMED.value,
            public_key="ready-public-key",
            vpn_ip="10.77.0.2",
        )
        pending = Device(
            user_id=user.id,
            name="Pending",
            status=DeviceStatus.READY_TO_DOWNLOAD.value,
            public_key="pending-public-key",
            vpn_ip="10.77.0.3",
        )
        db.add_all([ready, pending])
        db.flush()
        db.add(DeviceAccessGroup(device_id=ready.id, access_group_id=group.id, granted_by_user_id=None))
        db.commit()
        return ready.id, pending.id


def test_runtime_target_state_includes_only_confirmed_or_active_devices(
    session_factory: sessionmaker[OrmSession],
) -> None:
    ready_id, _pending_id = seed_runtime_devices(session_factory)
    settings = AppSettings(environment="test", nft_table_name="yourvpn", outbound_interface="eth0")
    runtime = WgRuntimeModule()

    with session_factory() as db:
        target = runtime.build_target_state(db, settings=settings)

    assert [peer.device_id for peer in target.peers] == [ready_id]
    assert target.peers[0].allowed_ips == ["10.77.0.2/32"]
    assert 'table ip yourvpn {' in target.firewall.ruleset
    assert 'ip saddr 10.77.0.2 ip daddr { 10.10.0.0/16 } counter accept' in target.firewall.ruleset
    assert 'oifname "eth0" masquerade' in target.firewall.ruleset
    assert "10.77.0.3" not in target.firewall.ruleset


def test_worker_apply_peer_job_marks_device_active(
    session_factory: sessionmaker[OrmSession],
) -> None:
    ready_id, _pending_id = seed_runtime_devices(session_factory)
    settings = AppSettings(environment="test")
    client = FakeWgAgentClient()
    with session_factory() as db:
        db.add(Job(job_type="apply_peer", status=JobStatus.PENDING.value, payload_json={"device_id": ready_id}))
        db.commit()

    job = run_pending_job_once(
        settings,
        session_factory=session_factory,
        wg_agent_client=client,
        worker_id="test-worker",
    )

    assert job is not None
    assert job.status == JobStatus.SUCCEEDED.value
    assert client.applied_peers == [
        {
            "interface": "wg0",
            "public_key": "ready-public-key",
            "vpn_ip": "10.77.0.2",
            "allowed_ips": ["10.77.0.2/32"],
        }
    ]
    with session_factory() as db:
        device = db.get(Device, ready_id)
        assert device is not None
        assert device.status == DeviceStatus.ACTIVE.value


def test_runtime_sample_status_updates_device_and_writes_snapshot(
    session_factory: sessionmaker[OrmSession],
) -> None:
    ready_id, _pending_id = seed_runtime_devices(session_factory)
    client = FakeWgAgentClient(
        statuses=[
            WgPeerStatus(
                interface="wg0",
                public_key="ready-public-key",
                endpoint="198.51.100.2:53000",
                allowed_ips=["10.77.0.2/32"],
                latest_handshake_epoch=1780000000,
                transfer_rx_bytes=1024,
                transfer_tx_bytes=2048,
            )
        ]
    )
    runtime = WgRuntimeModule(client=client)
    settings = AppSettings(environment="test")
    sampled_at = datetime(2026, 6, 28, tzinfo=UTC)

    with session_factory() as db:
        snapshots = runtime.sample_status(db, settings=settings, now=sampled_at)
        db.commit()

    assert len(snapshots) == 1
    with session_factory() as db:
        device = db.get(Device, ready_id)
        assert device is not None
        assert device.latest_endpoint == "198.51.100.2:53000"
        assert device.rx_bytes == 1024
        assert device.tx_bytes == 2048
        snapshot = db.scalar(select(TrafficSnapshot).where(TrafficSnapshot.device_id == ready_id))
        assert snapshot is not None
        assert snapshot.rx_bytes == 1024
        assert snapshot.tx_bytes == 2048
