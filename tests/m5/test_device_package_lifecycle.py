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
    Base,
    Device,
    DeviceAccessGroup,
    InstallPackage,
    Job,
    User,
    UserAccessGroup,
)
from yourvpn_core.db.session import create_session_factory
from yourvpn_core.domain.enums import DeviceStatus, InstallPackageStatus, JobStatus, Role, UserStatus
from yourvpn_core.modules.auth import PasswordService


@pytest.fixture()
def session_factory(tmp_path: Path) -> Iterator[sessionmaker[OrmSession]]:
    engine = create_engine(f"sqlite:///{(tmp_path / 'm5.sqlite3').as_posix()}", future=True)
    Base.metadata.create_all(engine)
    yield create_session_factory(engine)
    Base.metadata.drop_all(engine)


@pytest.fixture()
def app_settings(tmp_path: Path) -> AppSettings:
    return AppSettings(
        environment="test",
        session_cookie_secure=False,
        artifacts_dir=tmp_path / "artifacts",
        install_package_max_download_attempts=2,
        install_package_download_window_minutes=120,
    )


@pytest.fixture()
def client(session_factory: sessionmaker[OrmSession], app_settings: AppSettings) -> TestClient:
    return TestClient(create_app(app_settings, session_factory=session_factory))


def create_user(
    session_factory: sessionmaker[OrmSession],
    *,
    email: str,
    role: Role = Role.USER,
    approved_device_limit: int = 1,
    password: str = "GoodPass123",
) -> str:
    with session_factory() as db:
        user = User(
            email=email,
            display_name=email.split("@")[0],
            role=role.value,
            status=UserStatus.ACTIVE.value,
            password_hash=PasswordService().hash_password(password),
            approved_device_limit=approved_device_limit,
        )
        db.add(user)
        db.commit()
        return user.id


def seed_access_group(session_factory: sessionmaker[OrmSession], user_id: str) -> str:
    with session_factory() as db:
        group = AccessGroup(name="engineering", enabled=True)
        db.add(group)
        db.flush()
        db.add(UserAccessGroup(user_id=user_id, access_group_id=group.id, granted_by_user_id=None))
        db.commit()
        return group.id


def login(client: TestClient, *, email: str, password: str = "GoodPass123") -> str:
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return response.json()["csrf_token"]


def create_device(client: TestClient, csrf: str, name: str = "Laptop") -> dict:
    response = client.post(
        "/api/me/devices",
        headers={"x-csrf-token": csrf},
        json={"name": name},
    )
    assert response.status_code == 200
    return response.json()


def test_user_device_package_download_confirm_lifecycle(
    client: TestClient,
    session_factory: sessionmaker[OrmSession],
) -> None:
    user_id = create_user(session_factory, email="user@example.com", approved_device_limit=1)
    group_id = seed_access_group(session_factory, user_id)
    csrf = login(client, email="user@example.com")

    created = create_device(client, csrf)
    device = created["device"]
    package = created["package"]
    assert device["status"] == DeviceStatus.READY_TO_DOWNLOAD.value
    assert package["status"] == InstallPackageStatus.READY_TO_DOWNLOAD.value
    assert package["can_download"] is True
    package_id = package["id"]

    list_response = client.get("/api/me/devices")
    assert list_response.status_code == 200
    assert list_response.json()[0]["id"] == device["id"]

    package_response = client.get(f"/api/me/packages/{package_id}")
    assert package_response.status_code == 200
    assert package_response.json()["sha256"]

    with session_factory() as db:
        db_package = db.get(InstallPackage, package_id)
        assert db_package is not None
        artifact_path = Path(db_package.artifact_path or "")
        assert artifact_path.exists()

        inherited = db.scalar(
            select(DeviceAccessGroup).where(
                DeviceAccessGroup.device_id == device["id"],
                DeviceAccessGroup.access_group_id == group_id,
            )
        )
        assert inherited is not None

        build_job = db.scalar(select(Job).where(Job.job_type == "build_installer_fake"))
        assert build_job is not None
        assert build_job.status == JobStatus.SUCCEEDED.value

    download_response = client.get(f"/api/me/packages/{package_id}/download")
    assert download_response.status_code == 200
    assert b"WirePortal fake installer" in download_response.content

    confirm_response = client.post(
        f"/api/me/packages/{package_id}/confirm-download",
        headers={"x-csrf-token": csrf},
    )
    assert confirm_response.status_code == 200
    assert confirm_response.json()["apply_peer_job_enqueued"] is True
    assert confirm_response.json()["status"] == InstallPackageStatus.ARTIFACT_DELETED.value

    with session_factory() as db:
        db_package = db.get(InstallPackage, package_id)
        assert db_package is not None
        assert db_package.confirmed_at is not None
        assert db_package.artifact_deleted_at is not None
        assert not artifact_path.exists()

        db_device = db.get(Device, device["id"])
        assert db_device is not None
        assert db_device.status == DeviceStatus.DOWNLOAD_CONFIRMED.value

        apply_job = db.scalar(select(Job).where(Job.job_type == "apply_peer"))
        assert apply_job is not None
        assert apply_job.status == JobStatus.PENDING.value

    second_download = client.get(f"/api/me/packages/{package_id}/download")
    assert second_download.status_code == 409
    assert second_download.json()["code"] == "download_not_available"


def test_device_quota_is_enforced(client: TestClient, session_factory: sessionmaker[OrmSession]) -> None:
    create_user(session_factory, email="quota@example.com", approved_device_limit=1)
    csrf = login(client, email="quota@example.com")
    create_device(client, csrf, name="first")

    response = client.post(
        "/api/me/devices",
        headers={"x-csrf-token": csrf},
        json={"name": "second"},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "quota_exceeded"


def test_download_attempt_limit_is_enforced(
    session_factory: sessionmaker[OrmSession],
    tmp_path: Path,
) -> None:
    settings = AppSettings(
        environment="test",
        session_cookie_secure=False,
        artifacts_dir=tmp_path / "artifacts",
        install_package_max_download_attempts=1,
    )
    client = TestClient(create_app(settings, session_factory=session_factory))
    create_user(session_factory, email="limit@example.com", approved_device_limit=1)
    csrf = login(client, email="limit@example.com")
    created = create_device(client, csrf)
    package_id = created["package"]["id"]

    first = client.get(f"/api/me/packages/{package_id}/download")
    assert first.status_code == 200

    second = client.get(f"/api/me/packages/{package_id}/download")
    assert second.status_code == 409
    assert second.json()["code"] == "download_not_available"


def test_package_is_visible_only_to_owner(
    client: TestClient,
    session_factory: sessionmaker[OrmSession],
) -> None:
    create_user(session_factory, email="owner@example.com", approved_device_limit=1)
    create_user(session_factory, email="other@example.com", approved_device_limit=1)
    owner_csrf = login(client, email="owner@example.com")
    created = create_device(client, owner_csrf)
    package_id = created["package"]["id"]

    login(client, email="other@example.com")
    response = client.get(f"/api/me/packages/{package_id}")

    assert response.status_code == 404


def test_admin_reset_and_revoke_device(
    client: TestClient,
    session_factory: sessionmaker[OrmSession],
) -> None:
    create_user(session_factory, email="admin@example.com", role=Role.ADMIN, approved_device_limit=0)
    create_user(session_factory, email="device-user@example.com", approved_device_limit=1)
    user_csrf = login(client, email="device-user@example.com")
    created = create_device(client, user_csrf)
    device_id = created["device"]["id"]
    first_package_id = created["package"]["id"]

    admin_csrf = login(client, email="admin@example.com")
    reset = client.post(
        f"/api/admin/devices/{device_id}/reset",
        headers={"x-csrf-token": admin_csrf},
    )
    assert reset.status_code == 200
    assert reset.json()["package"]["id"] != first_package_id
    assert reset.json()["device"]["status"] == DeviceStatus.READY_TO_DOWNLOAD.value

    revoke = client.post(
        f"/api/admin/devices/{device_id}/revoke",
        headers={"x-csrf-token": admin_csrf},
    )
    assert revoke.status_code == 200
    assert revoke.json()["status"] == DeviceStatus.REVOKED.value

    with session_factory() as db:
        remove_job = db.scalar(select(Job).where(Job.job_type == "remove_peer"))
        assert remove_job is not None
        assert remove_job.status == JobStatus.PENDING.value
