from __future__ import annotations

import json
import zipfile
from hashlib import sha256
from pathlib import Path

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session as OrmSession, sessionmaker

from yourvpn_api.main import create_app
from yourvpn_core.config import AppSettings
from yourvpn_core.db import AccessGroup, AccessGroupRoute, Base, Device, InstallPackage, Job, User, UserAccessGroup
from yourvpn_core.db.session import create_session_factory
from yourvpn_core.domain.enums import InstallPackageStatus, JobStatus, Role, UserStatus
from yourvpn_core.modules.auth import PasswordService
from yourvpn_core.modules.installer_builder import DEVICE_INI_NAME, MANIFEST_NAME, RUNNER_NAME, WIREGUARD_MSI_NAME


SERVER_PUBLIC_KEY = "qenSvxW2fyx68E89mYqYlYa7C4cPm3+uoXKRFq6eZFc="


@pytest.fixture()
def session_factory(tmp_path: Path) -> sessionmaker[OrmSession]:
    engine = create_engine(f"sqlite:///{(tmp_path / 'm6.sqlite3').as_posix()}", future=True)
    Base.metadata.create_all(engine)
    return create_session_factory(engine)


def _write_msi(tmp_path: Path, content: bytes = b"wireguard-msi-fixture") -> tuple[Path, str]:
    path = tmp_path / "wireguard-amd64-1.1.msi"
    path.write_bytes(content)
    return path, sha256(content).hexdigest().upper()


def _settings(tmp_path: Path, msi_path: Path, msi_sha256: str) -> AppSettings:
    return AppSettings(
        environment="test",
        session_cookie_secure=False,
        artifacts_dir=tmp_path / "artifacts",
        build_tmp_dir=tmp_path / "build-tmp",
        installer_builder_mode="self_pack",
        wireguard_msi_path=str(msi_path),
        wireguard_msi_sha256=msi_sha256,
        wireguard_server_public_key=SERVER_PUBLIC_KEY,
        wireguard_endpoint="vpn.example.test:51820",
    )


def _create_user_with_route(session_factory: sessionmaker[OrmSession]) -> str:
    with session_factory() as db:
        user = User(
            email="m6-user@example.com",
            display_name="M6 User",
            role=Role.USER.value,
            status=UserStatus.ACTIVE.value,
            password_hash=PasswordService().hash_password("GoodPass123"),
            approved_device_limit=1,
        )
        db.add(user)
        db.flush()
        group = AccessGroup(name="engineering", enabled=True)
        db.add(group)
        db.flush()
        db.add(AccessGroupRoute(access_group_id=group.id, cidr="10.10.0.0/16", enabled=True))
        db.add(UserAccessGroup(user_id=user.id, access_group_id=group.id, granted_by_user_id=None))
        db.commit()
        return user.id


def _login(client: TestClient) -> str:
    response = client.post(
        "/api/auth/login",
        json={"email": "m6-user@example.com", "password": "GoodPass123"},
    )
    assert response.status_code == 200
    return response.json()["csrf_token"]


def test_self_pack_builder_generates_installer_package_without_storing_private_key(
    tmp_path: Path,
    session_factory: sessionmaker[OrmSession],
) -> None:
    msi_path, msi_sha256 = _write_msi(tmp_path)
    settings = _settings(tmp_path, msi_path, msi_sha256)
    client = TestClient(create_app(settings, session_factory=session_factory))
    _create_user_with_route(session_factory)
    csrf = _login(client)

    response = client.post(
        "/api/me/devices",
        headers={"x-csrf-token": csrf},
        json={"name": "Work Laptop"},
    )

    assert response.status_code == 200
    body = response.json()
    package = body["package"]
    assert package["status"] == InstallPackageStatus.READY_TO_DOWNLOAD.value
    assert package["file_name"].endswith(".exe")
    assert package["signed_status"] == "unsigned"
    assert package["config_format"] == "ini"

    with session_factory() as db:
        db_package = db.get(InstallPackage, package["id"])
        assert db_package is not None
        artifact = Path(db_package.artifact_path or "")
        assert artifact.exists()
        assert db_package.sha256 == sha256(artifact.read_bytes()).hexdigest()

        db_device = db.get(Device, body["device"]["id"])
        assert db_device is not None
        assert db_device.public_key is not None
        assert len(db_device.public_key) == 44

        build_job = db.scalar(select(Job).where(Job.job_type == "build_installer"))
        assert build_job is not None
        assert build_job.status == JobStatus.SUCCEEDED.value

    with zipfile.ZipFile(artifact) as package_zip:
        names = set(package_zip.namelist())
        assert MANIFEST_NAME in names
        assert WIREGUARD_MSI_NAME in names
        assert DEVICE_INI_NAME in names
        assert RUNNER_NAME in names
        manifest = json.loads(package_zip.read(MANIFEST_NAME).decode("utf-8"))
        device_ini = package_zip.read(DEVICE_INI_NAME).decode("utf-8")
        runner = package_zip.read(RUNNER_NAME).decode("utf-8")

    assert manifest["format"] == "wireportal-self-pack-v1"
    assert manifest["wireguard_installer_sha256"] == msi_sha256
    assert manifest["device"]["allowed_ips"] == ["10.10.0.0/16"]
    assert manifest["cleanup"]["build_temp_ini_deleted"] is True
    assert "PrivateKey =" in device_ini
    assert "AllowedIPs = 10.10.0.0/16" in device_ini
    assert db_device.public_key in manifest["device"]["public_key"]
    assert "PrivateKey =" not in json.dumps(manifest)
    assert "installtunnelservice" in runner
    assert not list((tmp_path / "build-tmp").glob("**/device.ini"))


def test_self_pack_builder_records_failed_job_on_msi_sha_mismatch(
    tmp_path: Path,
    session_factory: sessionmaker[OrmSession],
) -> None:
    msi_path, _msi_sha256 = _write_msi(tmp_path)
    settings = _settings(tmp_path, msi_path, "0" * 64)
    client = TestClient(create_app(settings, session_factory=session_factory))
    _create_user_with_route(session_factory)
    csrf = _login(client)

    response = client.post(
        "/api/me/devices",
        headers={"x-csrf-token": csrf},
        json={"name": "Mismatch Laptop"},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "installer_build_failed"

    with session_factory() as db:
        build_job = db.scalar(select(Job).where(Job.job_type == "build_installer"))
        assert build_job is not None
        assert build_job.status == JobStatus.FAILED.value
        assert "SHA256 mismatch" in (build_job.last_error or "")

        db_package = db.scalar(select(InstallPackage))
        assert db_package is not None
        assert db_package.status == InstallPackageStatus.FAILED.value
        assert db_package.artifact_path is None
