from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session as OrmSession, sessionmaker

from yourvpn_api.main import create_app
from yourvpn_core.config import AppSettings
from yourvpn_core.db import (
    AccessGroup,
    Application,
    ApprovalRecord,
    AuditLog,
    Base,
    PasswordToken,
    User,
    UserAccessGroup,
)
from yourvpn_core.db.session import create_session_factory
from yourvpn_core.domain.enums import ApplicationStatus, Role, UserStatus
from yourvpn_core.modules.auth import PasswordService


@pytest.fixture()
def session_factory(tmp_path: Path) -> Iterator[sessionmaker[OrmSession]]:
    engine = create_engine(f"sqlite:///{(tmp_path / 'm4.sqlite3').as_posix()}", future=True)
    Base.metadata.create_all(engine)
    yield create_session_factory(engine)
    Base.metadata.drop_all(engine)


@pytest.fixture()
def client(session_factory: sessionmaker[OrmSession]) -> TestClient:
    app = create_app(
        AppSettings(
            environment="test",
            session_cookie_secure=False,
            public_base_url="http://portal.test",
            admin_ip_whitelist="",
        ),
        session_factory=session_factory,
    )
    return TestClient(app)


def create_user(
    session_factory: sessionmaker[OrmSession],
    *,
    email: str,
    role: Role,
    password: str = "GoodPass123",
) -> str:
    with session_factory() as db:
        user = User(
            email=email,
            display_name=email.split("@")[0],
            role=role.value,
            status=UserStatus.ACTIVE.value,
            password_hash=PasswordService().hash_password(password),
            approved_device_limit=0,
        )
        db.add(user)
        db.commit()
        return user.id


def login(client: TestClient, *, email: str, password: str = "GoodPass123") -> str:
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return response.json()["csrf_token"]


def seed_access_group(
    session_factory: sessionmaker[OrmSession],
    *,
    name: str,
    high_privilege: bool = False,
) -> str:
    with session_factory() as db:
        group = AccessGroup(
            name=name,
            description=f"{name} routes",
            is_high_privilege=high_privilege,
            enabled=True,
        )
        db.add(group)
        db.commit()
        return group.id


def submit_application(client: TestClient, *, email: str = "applicant@example.com") -> str:
    response = client.post(
        "/api/applications",
        json={
            "email": email,
            "display_name": "Applicant",
            "phone": "10086",
            "reason": "Need access",
            "requested_device_count": 2,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["submitted"] is True
    return body["application_id"]


def test_application_approval_password_setup_and_login_flow(
    client: TestClient,
    session_factory: sessionmaker[OrmSession],
) -> None:
    create_user(session_factory, email="admin@example.com", role=Role.ADMIN)
    group_a = seed_access_group(session_factory, name="engineering")
    group_b = seed_access_group(session_factory, name="ops")
    application_id = submit_application(client)

    csrf = login(client, email="admin@example.com")

    list_response = client.get("/api/admin/applications")
    assert list_response.status_code == 200
    assert [row["id"] for row in list_response.json()] == [application_id]

    detail_response = client.get(f"/api/admin/applications/{application_id}")
    assert detail_response.status_code == 200
    assert detail_response.json()["status"] == ApplicationStatus.SUBMITTED.value

    approve_response = client.post(
        f"/api/admin/applications/{application_id}/approve",
        headers={"x-csrf-token": csrf},
        json={
            "approved_device_limit": 2,
            "access_group_ids": [group_a, group_b],
            "reason": "approved",
        },
    )
    assert approve_response.status_code == 200
    approve_body = approve_response.json()
    assert approve_body["status"] == ApplicationStatus.ACCOUNT_SETUP_PENDING.value
    assert approve_body["notification_status"] == "not_configured"
    assert approve_body["setup_url"].startswith("http://portal.test/password/setup?token=")

    setup_token = approve_body["setup_url"].split("token=", 1)[1]
    setup_response = client.post(
        "/api/auth/password/setup",
        json={"token": setup_token, "password": "Applicant123"},
    )
    assert setup_response.status_code == 200

    applicant_login = client.post(
        "/api/auth/login",
        json={"email": "applicant@example.com", "password": "Applicant123"},
    )
    assert applicant_login.status_code == 200

    with session_factory() as db:
        application = db.get(Application, application_id)
        assert application is not None
        assert application.status == ApplicationStatus.ACCOUNT_SETUP_PENDING.value

        user = db.scalar(select(User).where(User.email == "applicant@example.com"))
        assert user is not None
        assert user.status == UserStatus.ACTIVE.value
        assert user.approved_device_limit == 2

        grants = db.scalars(select(UserAccessGroup).where(UserAccessGroup.user_id == user.id)).all()
        assert {grant.access_group_id for grant in grants} == {group_a, group_b}

        password_tokens = db.scalars(select(PasswordToken).where(PasswordToken.user_id == user.id)).all()
        assert len(password_tokens) == 1
        assert password_tokens[0].used_at is not None

        approval = db.scalar(select(ApprovalRecord).where(ApprovalRecord.application_id == application_id))
        assert approval is not None
        assert approval.action == "approve"

        audit = db.scalar(select(AuditLog).where(AuditLog.action == "application.approved"))
        assert audit is not None


def test_approver_cannot_grant_high_privilege_group(
    client: TestClient,
    session_factory: sessionmaker[OrmSession],
) -> None:
    create_user(session_factory, email="approver@example.com", role=Role.APPROVER)
    high_group = seed_access_group(session_factory, name="root", high_privilege=True)
    application_id = submit_application(client, email="priv@example.com")

    csrf = login(client, email="approver@example.com")
    response = client.post(
        f"/api/admin/applications/{application_id}/approve",
        headers={"x-csrf-token": csrf},
        json={"approved_device_limit": 1, "access_group_ids": [high_group]},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "authorization_denied"


def test_admin_can_grant_high_privilege_group(
    client: TestClient,
    session_factory: sessionmaker[OrmSession],
) -> None:
    create_user(session_factory, email="admin@example.com", role=Role.ADMIN)
    high_group = seed_access_group(session_factory, name="root", high_privilege=True)
    application_id = submit_application(client, email="priv-admin@example.com")

    csrf = login(client, email="admin@example.com")
    response = client.post(
        f"/api/admin/applications/{application_id}/approve",
        headers={"x-csrf-token": csrf},
        json={"approved_device_limit": 1, "access_group_ids": [high_group]},
    )

    assert response.status_code == 200
    assert response.json()["setup_url"]


def test_reject_application_writes_approval_and_audit(
    client: TestClient,
    session_factory: sessionmaker[OrmSession],
) -> None:
    create_user(session_factory, email="approver@example.com", role=Role.APPROVER)
    application_id = submit_application(client, email="reject@example.com")
    csrf = login(client, email="approver@example.com")

    response = client.post(
        f"/api/admin/applications/{application_id}/reject",
        headers={"x-csrf-token": csrf},
        json={"reason": "missing justification"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == ApplicationStatus.REJECTED.value

    with session_factory() as db:
        record = db.scalar(select(ApprovalRecord).where(ApprovalRecord.application_id == application_id))
        assert record is not None
        assert record.action == "reject"

        audit = db.scalar(select(AuditLog).where(AuditLog.action == "application.rejected"))
        assert audit is not None


def test_public_application_validates_device_limit(client: TestClient) -> None:
    response = client.post(
        "/api/applications",
        json={
            "email": "too-many@example.com",
            "display_name": "Too Many",
            "requested_device_count": 4,
        },
    )

    assert response.status_code == 422


def test_smtp_configured_sends_password_setup_email(
    session_factory: sessionmaker[OrmSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent_messages = []

    class FakeSmtp:
        def __init__(self, host: str, port: int, timeout: int) -> None:
            assert host == "smtp.test"
            assert port == 2525
            assert timeout == 3

        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc, _traceback) -> None:
            return None

        def send_message(self, message) -> None:
            sent_messages.append(message)

    monkeypatch.setattr("yourvpn_core.modules.applications.smtplib.SMTP", FakeSmtp)

    app = create_app(
        AppSettings(
            environment="test",
            session_cookie_secure=False,
            public_base_url="http://portal.test",
            smtp_host="smtp.test",
            smtp_port=2525,
            smtp_from="noreply@example.com",
            smtp_timeout_seconds=3,
        ),
        session_factory=session_factory,
    )
    client = TestClient(app)
    create_user(session_factory, email="admin@example.com", role=Role.ADMIN)
    group_id = seed_access_group(session_factory, name="engineering")
    application_id = submit_application(client, email="smtp-applicant@example.com")
    csrf = login(client, email="admin@example.com")

    response = client.post(
        f"/api/admin/applications/{application_id}/approve",
        headers={"x-csrf-token": csrf},
        json={"approved_device_limit": 1, "access_group_ids": [group_id]},
    )

    assert response.status_code == 200
    assert response.json()["notification_status"] == "sent"
    assert len(sent_messages) == 1
    assert sent_messages[0]["To"] == "smtp-applicant@example.com"
