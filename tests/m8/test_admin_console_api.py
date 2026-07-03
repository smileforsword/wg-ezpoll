from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session as OrmSession, sessionmaker

from yourvpn_api.main import create_app
from yourvpn_core.config import AppSettings
from yourvpn_core.db import AccessGroup, AuditLog, Base, User
from yourvpn_core.db.session import create_session_factory
from yourvpn_core.domain.enums import Role, UserStatus
from yourvpn_core.modules.auth import PasswordService


@pytest.fixture()
def session_factory(tmp_path: Path) -> Iterator[sessionmaker[OrmSession]]:
    engine = create_engine(f"sqlite:///{(tmp_path / 'm8.sqlite3').as_posix()}", future=True)
    Base.metadata.create_all(engine)
    yield create_session_factory(engine)
    Base.metadata.drop_all(engine)


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
            approved_device_limit=1,
        )
        db.add(user)
        db.commit()
        return user.id


def login(client: TestClient, *, email: str) -> str:
    response = client.post("/api/auth/login", json={"email": email, "password": "GoodPass123"})
    assert response.status_code == 200
    return response.json()["csrf_token"]


def test_admin_console_lists_users_and_audit_logs(session_factory: sessionmaker[OrmSession]) -> None:
    app = create_app(AppSettings(environment="test", session_cookie_secure=False), session_factory=session_factory)
    client = TestClient(app)
    admin_id = create_user(session_factory, email="admin@example.com", role=Role.ADMIN)
    create_user(session_factory, email="user@example.com", role=Role.USER)
    with session_factory() as db:
        db.add(
            AuditLog(
                actor_user_id=admin_id,
                actor_type="user",
                action="console.test",
                target_type="test",
                target_id="m8",
            )
        )
        db.commit()
    login(client, email="admin@example.com")

    users = client.get("/api/admin/users")
    audit_logs = client.get("/api/admin/audit-logs")

    assert users.status_code == 200
    assert [row["email"] for row in users.json()] == ["user@example.com", "admin@example.com"]
    assert users.json()[1]["id"] == admin_id
    assert audit_logs.status_code == 200
    assert any(row["action"] == "console.test" for row in audit_logs.json())


def test_admin_can_update_user_device_limit(session_factory: sessionmaker[OrmSession]) -> None:
    app = create_app(AppSettings(environment="test", session_cookie_secure=False), session_factory=session_factory)
    client = TestClient(app)
    create_user(session_factory, email="admin@example.com", role=Role.ADMIN)
    user_id = create_user(session_factory, email="user@example.com", role=Role.USER)
    csrf = login(client, email="admin@example.com")

    response = client.patch(
        f"/api/admin/users/{user_id}",
        headers={"x-csrf-token": csrf},
        json={"approved_device_limit": 3},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == user_id
    assert body["approved_device_limit"] == 3

    with session_factory() as db:
        user = db.get(User, user_id)
        assert user is not None
        assert user.approved_device_limit == 3
        audit = db.scalar(select(AuditLog).where(AuditLog.action == "user.updated"))
        assert audit is not None


def test_approver_cannot_update_user_device_limit(session_factory: sessionmaker[OrmSession]) -> None:
    app = create_app(AppSettings(environment="test", session_cookie_secure=False), session_factory=session_factory)
    client = TestClient(app)
    create_user(session_factory, email="approver@example.com", role=Role.APPROVER)
    user_id = create_user(session_factory, email="user@example.com", role=Role.USER)
    csrf = login(client, email="approver@example.com")

    response = client.patch(
        f"/api/admin/users/{user_id}",
        headers={"x-csrf-token": csrf},
        json={"approved_device_limit": 3},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "authorization_denied"


def test_admin_can_create_access_group_with_routes(session_factory: sessionmaker[OrmSession]) -> None:
    app = create_app(AppSettings(environment="test", session_cookie_secure=False), session_factory=session_factory)
    client = TestClient(app)
    create_user(session_factory, email="admin@example.com", role=Role.ADMIN)
    csrf = login(client, email="admin@example.com")

    response = client.post(
        "/api/admin/access-groups",
        headers={"x-csrf-token": csrf},
        json={
            "name": "ops",
            "description": "Operations",
            "is_high_privilege": True,
            "routes": [{"cidr": "10.20.0.1/16", "description": "ops lan"}],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "ops"
    assert body["routes"][0]["cidr"] == "10.20.0.0/16"

    with session_factory() as db:
        group = db.scalar(select(AccessGroup).where(AccessGroup.name == "ops"))
        assert group is not None
        audit = db.scalar(select(AuditLog).where(AuditLog.action == "access_group.created"))
        assert audit is not None


def test_approver_cannot_create_access_group(session_factory: sessionmaker[OrmSession]) -> None:
    app = create_app(AppSettings(environment="test", session_cookie_secure=False), session_factory=session_factory)
    client = TestClient(app)
    create_user(session_factory, email="approver@example.com", role=Role.APPROVER)
    csrf = login(client, email="approver@example.com")

    response = client.post(
        "/api/admin/access-groups",
        headers={"x-csrf-token": csrf},
        json={"name": "blocked"},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "authorization_denied"
