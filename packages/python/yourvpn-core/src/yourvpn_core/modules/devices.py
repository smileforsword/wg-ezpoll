from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from secrets import token_urlsafe

from sqlalchemy import func, select
from sqlalchemy.orm import Session as OrmSession

from yourvpn_core.config import AppSettings
from yourvpn_core.db.models import (
    AccessGroupRoute as DbAccessGroupRoute,
    Device,
    DeviceAccessGroup,
    InstallPackage,
    Job,
    User,
    UserAccessGroup,
)
from yourvpn_core.domain.enums import DeviceStatus, InstallPackageStatus, JobStatus, Role
from yourvpn_core.modules.audit import AuditEvent, AuditModule
from yourvpn_core.modules.authorization import Actor
from yourvpn_core.modules.errors import (
    AuthorizationError,
    ConflictError,
    DownloadNotAvailableError,
    InstallerBuildError,
    NotFoundError,
    QuotaExceededError,
    ValidationError,
)
from yourvpn_core.modules.access_groups import AccessGroupModule, AccessGroupRoute
from yourvpn_core.modules.installer_builder import (
    BuildInstallerRequest,
    ConfigZipInstallerBuilder,
    FakeInstallerBuilder,
    InstallerBuilder,
    SelfPackInstallerBuilder,
)
from yourvpn_core.modules.ip_allocator import IpAllocatorModule
from yourvpn_core.modules.state_machine import StateMachineModule


TERMINAL_DEVICE_STATUSES = {
    DeviceStatus.REVOKED.value,
    DeviceStatus.EXPIRED.value,
}

ACTIVE_PACKAGE_STATUSES = {
    InstallPackageStatus.PENDING_BUILD.value,
    InstallPackageStatus.BUILDING.value,
    InstallPackageStatus.READY_TO_DOWNLOAD.value,
    InstallPackageStatus.DOWNLOADING.value,
}


def _as_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


@dataclass(frozen=True)
class CreateDeviceCommand:
    name: str


@dataclass(frozen=True)
class DownloadGrant:
    package: InstallPackage
    artifact_path: Path


class DeviceModule:
    def __init__(
        self,
        *,
        ip_allocator: IpAllocatorModule | None = None,
        access_group_module: AccessGroupModule | None = None,
        state_machine: StateMachineModule | None = None,
        audit_module: AuditModule | None = None,
        installer_builder: InstallerBuilder | None = None,
        fake_builder: FakeInstallerBuilder | None = None,
    ) -> None:
        self.ip_allocator = ip_allocator or IpAllocatorModule()
        self.access_group_module = access_group_module or AccessGroupModule()
        self.state_machine = state_machine or StateMachineModule()
        self.audit_module = audit_module or AuditModule()
        self.installer_builder = installer_builder
        self.fake_builder = fake_builder or FakeInstallerBuilder()
        self.self_pack_builder = SelfPackInstallerBuilder()
        self.config_zip_builder = ConfigZipInstallerBuilder()

    def list_user_devices(self, db: OrmSession, *, user_id: str) -> list[Device]:
        return db.scalars(select(Device).where(Device.user_id == user_id).order_by(Device.created_at.desc())).all()

    def create_device(
        self,
        db: OrmSession,
        command: CreateDeviceCommand,
        *,
        user: User,
        settings: AppSettings,
        ip_address: str,
        user_agent: str | None,
        now: datetime | None = None,
    ) -> tuple[Device, InstallPackage]:
        current_time = now or datetime.now(UTC)
        name = command.name.strip()
        if not name:
            raise ValidationError("Device name is required")

        active_count = db.scalar(
            select(func.count(Device.id)).where(
                Device.user_id == user.id,
                Device.status.notin_(TERMINAL_DEVICE_STATUSES),
            )
        )
        if int(active_count or 0) >= user.approved_device_limit:
            raise QuotaExceededError("Device quota exceeded")

        allocated_ips = db.scalars(select(Device.vpn_ip).where(Device.vpn_ip.is_not(None))).all()
        vpn_ip = self.ip_allocator.allocate_for_device(
            vpn_cidr=settings.vpn_cidr,
            server_ip=settings.vpn_server_ip,
            allocated_ips=allocated_ips,
            revoked_ips=[],
            now=current_time,
        )

        device = Device(
            user_id=user.id,
            name=name,
            status=DeviceStatus.PENDING_BUILD.value,
            vpn_ip=vpn_ip,
            rx_bytes=0,
            tx_bytes=0,
            expires_at=user.expires_at,
        )
        db.add(device)
        db.flush()

        user_grants = db.scalars(
            select(UserAccessGroup).where(UserAccessGroup.user_id == user.id)
        ).all()
        for grant in user_grants:
            db.add(
                DeviceAccessGroup(
                    device_id=device.id,
                    access_group_id=grant.access_group_id,
                    granted_by_user_id=grant.granted_by_user_id,
                )
            )

        package = InstallPackage(
            device_id=device.id,
            status=InstallPackageStatus.PENDING_BUILD.value,
            max_download_attempts=settings.install_package_max_download_attempts,
            download_attempts=0,
            signed_status="unsigned",
            config_format="ini",
        )
        db.add(package)
        db.flush()

        self.state_machine.require_transition(
            InstallPackageStatus(package.status),
            InstallPackageStatus.BUILDING,
        )
        self._build_package(
            db,
            settings=settings,
            device=device,
            package=package,
            allowed_group_ids=[grant.access_group_id for grant in user_grants],
            current_time=current_time,
            payload_extra={},
        )
        self.audit_module.record(
            db,
            AuditEvent(
                actor_user_id=user.id,
                actor_type="user",
                action="device.created",
                target_type="device",
                target_id=device.id,
                after_json={
                    "vpn_ip": device.vpn_ip,
                    "package_id": package.id,
                    "package_status": package.status,
                },
                ip_address=ip_address,
                user_agent=user_agent,
            ),
        )
        db.flush()
        return device, package

    def get_user_package(self, db: OrmSession, *, package_id: str, user_id: str) -> InstallPackage:
        package = db.get(InstallPackage, package_id)
        if package is None:
            raise NotFoundError("Install package not found")
        device = db.get(Device, package.device_id)
        if device is None or device.user_id != user_id:
            raise NotFoundError("Install package not found")
        return package

    def record_download_attempt(
        self,
        db: OrmSession,
        *,
        package_id: str,
        user_id: str,
        now: datetime | None = None,
    ) -> DownloadGrant:
        current_time = now or datetime.now(UTC)
        package = self.get_user_package(db, package_id=package_id, user_id=user_id)
        if package.confirmed_at is not None or package.artifact_deleted_at is not None:
            raise DownloadNotAvailableError("Install package has already been confirmed")
        if package.status not in {
            InstallPackageStatus.READY_TO_DOWNLOAD.value,
            InstallPackageStatus.DOWNLOADING.value,
        }:
            raise DownloadNotAvailableError("Install package is not ready")
        if package.download_expires_at is None or _as_aware_utc(package.download_expires_at) <= current_time:
            self._delete_artifact(package)
            package.status = InstallPackageStatus.EXPIRED.value
            package.artifact_deleted_at = current_time
            raise DownloadNotAvailableError("Install package download window expired")
        if package.download_attempts >= package.max_download_attempts:
            raise DownloadNotAvailableError("Install package download attempts exceeded")
        if not package.artifact_path:
            raise DownloadNotAvailableError("Install package artifact is missing")
        artifact_path = Path(package.artifact_path)
        if not artifact_path.exists():
            raise DownloadNotAvailableError("Install package artifact is missing")

        package.download_attempts += 1
        if package.status == InstallPackageStatus.READY_TO_DOWNLOAD.value:
            package.status = InstallPackageStatus.DOWNLOADING.value
            device = db.get(Device, package.device_id)
            if device and device.status == DeviceStatus.READY_TO_DOWNLOAD.value:
                device.status = DeviceStatus.DOWNLOADING.value
        db.flush()
        return DownloadGrant(package=package, artifact_path=artifact_path)

    def confirm_download(
        self,
        db: OrmSession,
        *,
        package_id: str,
        user_id: str,
        ip_address: str,
        user_agent: str | None,
        now: datetime | None = None,
    ) -> InstallPackage:
        current_time = now or datetime.now(UTC)
        package = self.get_user_package(db, package_id=package_id, user_id=user_id)
        if package.confirmed_at is not None:
            raise ConflictError("Install package download is already confirmed")
        if package.status not in {
            InstallPackageStatus.DOWNLOADING.value,
            InstallPackageStatus.READY_TO_DOWNLOAD.value,
        }:
            raise DownloadNotAvailableError("Install package cannot be confirmed")

        device = db.get(Device, package.device_id)
        if device is None:
            raise NotFoundError("Device not found")

        package.confirmed_at = current_time
        package.status = InstallPackageStatus.DOWNLOAD_CONFIRMED.value
        device.status = DeviceStatus.DOWNLOAD_CONFIRMED.value
        self._delete_artifact(package)
        package.artifact_deleted_at = current_time
        package.status = InstallPackageStatus.ARTIFACT_DELETED.value

        db.add(
            Job(
                job_type="apply_peer",
                status=JobStatus.PENDING.value,
                payload_json={
                    "device_id": device.id,
                    "public_key": device.public_key,
                    "vpn_ip": device.vpn_ip,
                    "allowed_ips": [f"{device.vpn_ip}/32"],
                },
            )
        )
        self.audit_module.record(
            db,
            AuditEvent(
                actor_user_id=user_id,
                actor_type="user",
                action="install_package.confirmed",
                target_type="install_package",
                target_id=package.id,
                after_json={"device_id": device.id, "apply_peer_job": True},
                ip_address=ip_address,
                user_agent=user_agent,
            ),
        )
        db.flush()
        return package

    def report_lost(
        self,
        db: OrmSession,
        *,
        device_id: str,
        user_id: str,
        now: datetime | None = None,
    ) -> Device:
        device = self._get_user_device(db, device_id=device_id, user_id=user_id)
        device.lost_reported_at = now or datetime.now(UTC)
        db.flush()
        return device

    def reset_device(
        self,
        db: OrmSession,
        *,
        device_id: str,
        actor: Actor,
        settings: AppSettings,
        now: datetime | None = None,
    ) -> tuple[Device, InstallPackage]:
        if actor.role != Role.ADMIN:
            raise AuthorizationError("Only admin can reset devices")
        current_time = now or datetime.now(UTC)
        device = db.get(Device, device_id)
        if device is None:
            raise NotFoundError("Device not found")
        if device.status == DeviceStatus.REVOKED.value:
            raise ConflictError("Revoked devices cannot be reset")

        for package in db.scalars(select(InstallPackage).where(InstallPackage.device_id == device.id)).all():
            if package.status in ACTIVE_PACKAGE_STATUSES:
                self._delete_artifact(package)
                package.status = InstallPackageStatus.REVOKED.value
                package.artifact_deleted_at = current_time

        device.status = DeviceStatus.RESET_PENDING.value
        device.public_key = f"reset-pending-{token_urlsafe(8)}"[:88]
        package = InstallPackage(
            device_id=device.id,
            status=InstallPackageStatus.PENDING_BUILD.value,
            max_download_attempts=settings.install_package_max_download_attempts,
            download_attempts=0,
            signed_status="unsigned",
            config_format="ini",
        )
        db.add(package)
        db.flush()
        group_ids = db.scalars(
            select(DeviceAccessGroup.access_group_id).where(DeviceAccessGroup.device_id == device.id)
        ).all()
        self.state_machine.require_transition(
            InstallPackageStatus(package.status),
            InstallPackageStatus.BUILDING,
        )
        self._build_package(
            db,
            settings=settings,
            device=device,
            package=package,
            allowed_group_ids=list(group_ids),
            current_time=current_time,
            payload_extra={"reason": "reset"},
        )
        db.flush()
        return device, package

    def revoke_device(
        self,
        db: OrmSession,
        *,
        device_id: str,
        actor: Actor,
        now: datetime | None = None,
    ) -> Device:
        if actor.role != Role.ADMIN:
            raise AuthorizationError("Only admin can revoke devices")
        current_time = now or datetime.now(UTC)
        device = db.get(Device, device_id)
        if device is None:
            raise NotFoundError("Device not found")
        device.status = DeviceStatus.REVOKED.value
        device.revoked_at = current_time
        for package in db.scalars(select(InstallPackage).where(InstallPackage.device_id == device.id)).all():
            if package.artifact_deleted_at is None:
                self._delete_artifact(package)
                package.artifact_deleted_at = current_time
            if package.status not in {
                InstallPackageStatus.ARTIFACT_DELETED.value,
                InstallPackageStatus.DOWNLOAD_CONFIRMED.value,
            }:
                package.status = InstallPackageStatus.REVOKED.value
        db.add(
            Job(
                job_type="remove_peer",
                status=JobStatus.PENDING.value,
                payload_json={"device_id": device.id, "public_key": device.public_key},
            )
        )
        db.flush()
        return device

    def _build_package(
        self,
        db: OrmSession,
        *,
        settings: AppSettings,
        device: Device,
        package: InstallPackage,
        allowed_group_ids: list[str],
        current_time: datetime,
        payload_extra: dict[str, object],
    ) -> None:
        builder = self._select_builder(settings)
        job_payload = {"device_id": device.id, "package_id": package.id, **payload_extra}
        job = Job(
            job_type=builder.job_type,
            status=JobStatus.RUNNING.value,
            payload_json=job_payload,
        )
        db.add(job)
        package.status = InstallPackageStatus.BUILDING.value

        try:
            result = builder.build(
                BuildInstallerRequest(
                    settings=settings,
                    device_id=device.id,
                    device_name=device.name,
                    vpn_ip=device.vpn_ip,
                    package_id=package.id,
                    allowed_group_ids=allowed_group_ids,
                    allowed_ips=self._compile_allowed_ips(db, settings=settings, allowed_group_ids=allowed_group_ids),
                    now=current_time,
                )
            )
        except Exception as exc:
            package.status = InstallPackageStatus.FAILED.value
            package.last_error = str(exc)
            device.status = DeviceStatus.PENDING_BUILD.value
            job.status = JobStatus.FAILED.value
            job.last_error = str(exc)
            if isinstance(exc, InstallerBuildError):
                raise
            raise InstallerBuildError(str(exc)) from exc

        device.public_key = result.public_key
        package.file_name = result.file_name
        package.artifact_path = str(result.artifact_path)
        package.sha256 = result.sha256
        package.file_size = result.file_size
        package.signed_status = result.signed_status
        package.config_format = result.config_format
        package.wireguard_installer_version = result.wireguard_installer_version
        package.download_expires_at = current_time + timedelta(
            minutes=settings.install_package_download_window_minutes
        )
        package.status = InstallPackageStatus.READY_TO_DOWNLOAD.value
        package.last_error = None
        device.status = DeviceStatus.READY_TO_DOWNLOAD.value
        job.status = JobStatus.SUCCEEDED.value

    def _select_builder(self, settings: AppSettings) -> InstallerBuilder:
        if self.installer_builder is not None:
            return self.installer_builder
        mode = settings.installer_builder_mode.strip().lower().replace("-", "_")
        if mode == "fake":
            if not settings.fake_builder_enabled:
                raise ConflictError("Fake builder is disabled")
            return self.fake_builder
        if mode == "self_pack":
            return self.self_pack_builder
        if mode == "config_zip":
            return self.config_zip_builder
        if mode == "auto":
            if settings.wireguard_msi_path:
                return self.self_pack_builder
            if settings.fake_builder_enabled:
                return self.fake_builder
            raise ConflictError("No installer builder is configured")
        raise ValidationError("installer_builder_mode must be auto, fake, self_pack, or config_zip")

    def _compile_allowed_ips(
        self,
        db: OrmSession,
        *,
        settings: AppSettings,
        allowed_group_ids: list[str],
    ) -> list[str]:
        if not allowed_group_ids:
            return [f"{settings.vpn_server_ip}/32"]
        routes = db.scalars(
            select(DbAccessGroupRoute).where(DbAccessGroupRoute.access_group_id.in_(allowed_group_ids))
        ).all()
        allowed_ips = self.access_group_module.compile_allowed_ips(
            AccessGroupRoute(
                access_group_id=route.access_group_id,
                cidr=route.cidr,
                enabled=route.enabled,
            )
            for route in routes
        )
        return allowed_ips or [f"{settings.vpn_server_ip}/32"]

    def _get_user_device(self, db: OrmSession, *, device_id: str, user_id: str) -> Device:
        device = db.get(Device, device_id)
        if device is None or device.user_id != user_id:
            raise NotFoundError("Device not found")
        return device

    def _delete_artifact(self, package: InstallPackage) -> None:
        if not package.artifact_path:
            return
        artifact_path = Path(package.artifact_path)
        if artifact_path.exists():
            artifact_path.unlink()
