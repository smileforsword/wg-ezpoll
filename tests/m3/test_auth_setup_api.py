from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session as OrmSession, sessionmaker

from yourvpn_api.main import create_app
from yourvpn_core.config import AppSettings
from yourvpn_core.db import AuditLog, Base, LoginAttempt, User
from yourvpn_core.db.session import create_session_factory
from yourvpn_core.domain.enums import Role, UserStatus
from yourvpn_core.modules.auth import AuthModule, PasswordService


@pytest.fixture()
def session_factory(tmp_path: Path) -> Iterator[sessionmaker[OrmSession]]:
    engine = create_engine(f"sqlite:///{(tmp_path / 'm3.sqlite3').as_posix()}", future=True)
    Base.metadata.create_all(engine)
    yield create_session_factory(engine)
    Base.metadata.drop_all(engine)


@pytest.fixture()
def client(session_factory: sessionmaker[OrmSession]) -> TestClient:
    app = create_app(
        AppSettings(
            environment="test",
            session_cookie_secure=False,
            login_rate_limit_attempts=3,
            login_rate_limit_window_minutes=15,
        ),
        session_factory=session_factory,
    )
    return TestClient(app)


def test_setup_status_setup_login_me_and_logout(client: TestClient) -> None:
    status_response = client.get("/api/setup/status")
    assert status_response.status_code == 200
    assert status_response.json() == {
        "setup_completed": False,
        "admin_exists": False,
        "setup_available": True,
    }

    setup_response = client.post(
        "/api/setup",
        json={
            "email": "Admin@Example.com",
            "display_name": "Admin",
            "password": "GoodPass123",
        },
    )
    assert setup_response.status_code == 200
    assert setup_response.json()["setup_completed"] is True

    repeat_response = client.post(
        "/api/setup",
        json={
            "email": "second@example.com",
            "display_name": "Second",
            "password": "GoodPass123",
        },
    )
    assert repeat_response.status_code == 403
    assert repeat_response.json()["code"] == "setup_already_completed"

    login_response = client.post(
        "/api/auth/login",
        json={"email": "admin@example.com", "password": "GoodPass123"},
    )
    assert login_response.status_code == 200
    csrf_token = login_response.json()["csrf_token"]
    assert csrf_token
    assert "wireportal_session" in login_response.cookies

    me_response = client.get("/api/me")
    assert me_response.status_code == 200
    assert me_response.json()["email"] == "admin@example.com"
    assert me_response.json()["role"] == Role.ADMIN.value

    rejected_logout = client.post("/api/auth/logout")
    assert rejected_logout.status_code == 401
    assert rejected_logout.json()["code"] == "csrf_failed"

    logout_response = client.post("/api/auth/logout", headers={"x-csrf-token": csrf_token})
    assert logout_response.status_code == 200
    assert logout_response.json() == {"ok": True}

    me_after_logout = client.get("/api/me")
    assert me_after_logout.status_code == 401


def test_setup_password_token_flow(session_factory: sessionmaker[OrmSession]) -> None:
    password_service = PasswordService()
    auth_module = AuthModule(password_service=password_service)

    with session_factory() as db:
        user = User(
            email="pending@example.com",
            display_name="Pending",
            role=Role.USER.value,
            status=UserStatus.PENDING_PASSWORD.value,
            approved_device_limit=1,
        )
        db.add(user)
        db.flush()
        _token_row, token = auth_module.create_password_setup_token(
            db,
            user_id=user.id,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        db.commit()

    app = create_app(AppSettings(environment="test", session_cookie_secure=False), session_factory=session_factory)
    client = TestClient(app)

    response = client.post(
        "/api/auth/password/setup",
        json={"token": token, "password": "NewPass123"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == UserStatus.ACTIVE.value

    reuse_response = client.post(
        "/api/auth/password/setup",
        json={"token": token, "password": "NewPass123"},
    )
    assert reuse_response.status_code == 401
    assert reuse_response.json()["code"] == "authentication_failed"

    login_response = client.post(
        "/api/auth/login",
        json={"email": "pending@example.com", "password": "NewPass123"},
    )
    assert login_response.status_code == 200


def test_reset_password_endpoint_accepts_reset_token(session_factory: sessionmaker[OrmSession]) -> None:
    auth_module = AuthModule()
    old_hash = PasswordService().hash_password("OldPass123")

    with session_factory() as db:
        user = User(
            email="active@example.com",
            display_name="Active",
            role=Role.USER.value,
            status=UserStatus.ACTIVE.value,
            password_hash=old_hash,
            approved_device_limit=1,
        )
        db.add(user)
        db.flush()
        _token_row, token = auth_module.create_password_setup_token(
            db,
            user_id=user.id,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            purpose="reset",
        )
        db.commit()

    app = create_app(AppSettings(environment="test", session_cookie_secure=False), session_factory=session_factory)
    client = TestClient(app)

    response = client.post(
        "/api/auth/password/reset",
        json={"token": token, "password": "NewPass123"},
    )
    assert response.status_code == 200

    login_response = client.post(
        "/api/auth/login",
        json={"email": "active@example.com", "password": "NewPass123"},
    )
    assert login_response.status_code == 200


def test_password_policy_rejects_weak_setup_password(client: TestClient) -> None:
    response = client.post(
        "/api/setup",
        json={
            "email": "admin@example.com",
            "display_name": "Admin",
            "password": "password",
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "password_policy_failed"


def test_login_rate_limit_records_attempts_and_audit(client: TestClient, session_factory: sessionmaker[OrmSession]) -> None:
    setup_response = client.post(
        "/api/setup",
        json={
            "email": "admin@example.com",
            "display_name": "Admin",
            "password": "GoodPass123",
        },
    )
    assert setup_response.status_code == 200

    for _ in range(3):
        response = client.post(
            "/api/auth/login",
            json={"email": "admin@example.com", "password": "WrongPass123"},
        )
        assert response.status_code == 401

    limited_response = client.post(
        "/api/auth/login",
        json={"email": "admin@example.com", "password": "WrongPass123"},
    )
    assert limited_response.status_code == 429
    assert limited_response.json()["code"] == "login_rate_limited"

    with session_factory() as db:
        attempts = db.scalars(select(LoginAttempt).where(LoginAttempt.email == "admin@example.com")).all()
        assert len(attempts) == 4
        audits = db.scalars(select(AuditLog).where(AuditLog.action == "auth.login_rejected")).all()
        assert len(audits) == 4


def test_admin_ip_whitelist_rejects_and_audits(session_factory: sessionmaker[OrmSession]) -> None:
    app = create_app(
        AppSettings(
            environment="test",
            admin_ip_whitelist="10.0.0.0/8",
            session_cookie_secure=False,
        ),
        session_factory=session_factory,
    )
    client = TestClient(app)

    denied = client.get("/api/admin/applications", headers={"x-forwarded-for": "192.0.2.10"})
    assert denied.status_code == 403
    assert denied.json()["code"] == "authorization_denied"

    allowed = client.get("/api/admin/applications", headers={"x-forwarded-for": "10.1.2.3"})
    assert allowed.status_code == 401

    with session_factory() as db:
        audit = db.scalar(select(AuditLog).where(AuditLog.action == "security.admin_ip_rejected"))
        assert audit is not None
        assert audit.ip_address == "192.0.2.10"
