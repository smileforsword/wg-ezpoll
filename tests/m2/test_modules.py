from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from yourvpn_core.db import AuditLog, Base
from yourvpn_core.domain.enums import (
    ApplicationStatus,
    DeviceStatus,
    InstallPackageStatus,
    Role,
)
from yourvpn_core.modules import (
    AccessGroupModule,
    AccessGroupRoute,
    Actor,
    AuditEvent,
    AuditModule,
    AuthorizationModule,
    GrantableAccessGroup,
    IpAllocatorModule,
    RequestContext,
    RevokedIp,
    StateMachineModule,
)
from yourvpn_core.modules.errors import AuthorizationError, InvalidStateTransitionError


def test_state_machine_allows_expected_transitions() -> None:
    module = StateMachineModule()

    module.require_transition(ApplicationStatus.SUBMITTED, ApplicationStatus.APPROVED)
    module.require_transition(DeviceStatus.DOWNLOAD_CONFIRMED, DeviceStatus.ACTIVE)
    module.require_transition(InstallPackageStatus.DOWNLOAD_CONFIRMED, InstallPackageStatus.ARTIFACT_DELETED)

    with pytest.raises(InvalidStateTransitionError):
        module.require_transition(DeviceStatus.READY_TO_DOWNLOAD, DeviceStatus.ACTIVE)


def test_authorization_roles_ip_and_high_privilege_groups() -> None:
    module = AuthorizationModule()
    admin = Actor(user_id="admin-id", role=Role.ADMIN)
    approver = Actor(user_id="approver-id", role=Role.APPROVER)
    user = Actor(user_id="user-id", role=Role.USER)

    module.require_role(admin, {Role.ADMIN})
    module.require_admin_ip_allowed(RequestContext(ip_address="10.1.2.3"), ["10.1.0.0/16"])
    module.can_grant_access_groups(
        admin,
        [GrantableAccessGroup(access_group_id="root", is_high_privilege=True)],
    )

    with pytest.raises(AuthorizationError):
        module.require_role(user, {Role.ADMIN, Role.APPROVER})

    with pytest.raises(AuthorizationError):
        module.require_admin_ip_allowed(RequestContext(ip_address="192.0.2.9"), ["10.1.0.0/16"])

    with pytest.raises(AuthorizationError):
        module.can_grant_access_groups(
            approver,
            [GrantableAccessGroup(access_group_id="root", is_high_privilege=True)],
        )


def test_access_group_compilation_deduplicates_routes() -> None:
    module = AccessGroupModule()
    routes = [
        AccessGroupRoute(access_group_id="a", cidr="10.20.0.0/16"),
        AccessGroupRoute(access_group_id="a", cidr="10.20.10.0/24"),
        AccessGroupRoute(access_group_id="b", cidr="10.20.0.0/16"),
        AccessGroupRoute(access_group_id="b", cidr="172.16.30.0/24", enabled=False),
    ]

    assert module.compile_allowed_ips(routes) == ["10.20.0.0/16", "10.20.10.0/24"]
    assert module.compile_firewall_targets(device_vpn_ip="10.77.0.2", routes=routes)[0].source_vpn_ip == "10.77.0.2"


def test_ip_allocator_skips_server_used_and_cooling_ips() -> None:
    module = IpAllocatorModule()
    now = datetime(2026, 6, 26, tzinfo=UTC)

    ip = module.allocate_for_device(
        vpn_cidr="10.77.0.0/29",
        server_ip="10.77.0.1",
        allocated_ips=["10.77.0.2"],
        revoked_ips=[RevokedIp(ip="10.77.0.3", cooldown_until=now + timedelta(days=1))],
        now=now,
    )

    assert ip == "10.77.0.4"
    assert module.reserve_existing_for_reset("10.77.0.9") == "10.77.0.9"


def test_audit_module_records_event() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)

    with Session() as db:
        row = AuditModule().record(
            db,
            AuditEvent(
                action="application.approve",
                target_type="application",
                target_id="app-id",
                actor_type="user",
                before_json={"status": "submitted"},
                after_json={"status": "approved"},
                ip_address="198.51.100.10",
            ),
        )
        db.commit()

        saved = db.scalars(select(AuditLog).where(AuditLog.id == row.id)).one()
        assert saved.action == "application.approve"
        assert saved.before_json == {"status": "submitted"}
        assert saved.after_json == {"status": "approved"}
