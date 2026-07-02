from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from yourvpn_core.db.base import Base, IdMixin, TimestampMixin, utcnow
from yourvpn_core.domain.enums import (
    ApplicationStatus,
    DeviceStatus,
    InstallPackageStatus,
    JobStatus,
    Role,
    UserStatus,
)


class User(IdMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(32), nullable=False, default=Role.USER.value)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=UserStatus.PENDING_PASSWORD.value,
        index=True,
    )
    password_hash: Mapped[str | None] = mapped_column(String(255))
    approved_device_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    identities: Mapped[list[UserIdentity]] = relationship(back_populates="user", cascade="all, delete-orphan")
    devices: Mapped[list[Device]] = relationship(back_populates="user", cascade="all, delete-orphan")


class UserIdentity(IdMixin, Base):
    __tablename__ = "user_identities"
    __table_args__ = (UniqueConstraint("provider", "provider_subject", name="uq_user_identity_provider_subject"),)

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    user: Mapped[User] = relationship(back_populates="identities")


class Session(IdMixin, TimestampMixin, Base):
    __tablename__ = "sessions"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    session_token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    csrf_token_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(512))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PasswordToken(IdMixin, Base):
    __tablename__ = "password_tokens"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False, default="setup")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class LoginAttempt(IdMixin, Base):
    __tablename__ = "login_attempts"
    __table_args__ = (
        Index("ix_login_attempts_email_created_at", "email", "created_at"),
        Index("ix_login_attempts_ip_created_at", "ip_address", "created_at"),
    )

    email: Mapped[str | None] = mapped_column(String(320))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    failure_reason: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class AccessGroup(IdMixin, TimestampMixin, Base):
    __tablename__ = "access_groups"

    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    is_high_privilege: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    routes: Mapped[list[AccessGroupRoute]] = relationship(back_populates="access_group", cascade="all, delete-orphan")


class AccessGroupRoute(IdMixin, TimestampMixin, Base):
    __tablename__ = "access_group_routes"
    __table_args__ = (UniqueConstraint("access_group_id", "cidr", name="uq_access_group_route_group_cidr"),)

    access_group_id: Mapped[str] = mapped_column(
        ForeignKey("access_groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    cidr: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    access_group: Mapped[AccessGroup] = relationship(back_populates="routes")


class Application(IdMixin, TimestampMixin, Base):
    __tablename__ = "applications"

    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(64))
    reason: Mapped[str | None] = mapped_column(Text)
    requested_device_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=ApplicationStatus.SUBMITTED.value,
        index=True,
    )
    submitted_ip: Mapped[str | None] = mapped_column(String(64))
    submitted_user_agent: Mapped[str | None] = mapped_column(String(512))


class ApprovalRecord(IdMixin, Base):
    __tablename__ = "approval_records"
    __table_args__ = (Index("ix_approval_records_application_created_at", "application_id", "created_at"),)

    application_id: Mapped[str] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    actor_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    approved_device_limit: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(Text)
    created_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class UserAccessGroup(Base):
    __tablename__ = "user_access_groups"
    __table_args__ = (UniqueConstraint("user_id", "access_group_id", name="uq_user_access_groups_user_group"),)

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    access_group_id: Mapped[str] = mapped_column(ForeignKey("access_groups.id", ondelete="CASCADE"), primary_key=True)
    granted_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Device(IdMixin, TimestampMixin, Base):
    __tablename__ = "devices"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=DeviceStatus.PENDING_BUILD.value,
        index=True,
    )
    public_key: Mapped[str | None] = mapped_column(String(88), unique=True)
    vpn_ip: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    lost_reported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    latest_handshake_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    latest_endpoint: Mapped[str | None] = mapped_column(String(255))
    rx_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tx_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    user: Mapped[User] = relationship(back_populates="devices")


class DeviceAccessGroup(Base):
    __tablename__ = "device_access_groups"
    __table_args__ = (UniqueConstraint("device_id", "access_group_id", name="uq_device_access_groups_device_group"),)

    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), primary_key=True)
    access_group_id: Mapped[str] = mapped_column(ForeignKey("access_groups.id", ondelete="CASCADE"), primary_key=True)
    granted_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class InstallPackage(IdMixin, TimestampMixin, Base):
    __tablename__ = "install_packages"
    __table_args__ = (
        Index("ix_install_packages_device_status", "device_id", "status"),
        Index("ix_install_packages_download_expires_at", "download_expires_at"),
    )

    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=InstallPackageStatus.PENDING_BUILD.value,
        index=True,
    )
    file_name: Mapped[str | None] = mapped_column(String(255))
    artifact_path: Mapped[str | None] = mapped_column(String(1024))
    sha256: Mapped[str | None] = mapped_column(String(64))
    file_size: Mapped[int | None] = mapped_column(Integer)
    signed_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unsigned")
    config_format: Mapped[str] = mapped_column(String(32), nullable=False, default="ini")
    wireguard_installer_version: Mapped[str | None] = mapped_column(String(64))
    download_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_download_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    download_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    artifact_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


class Job(IdMixin, TimestampMixin, Base):
    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_status_run_after", "status", "run_after"),
        Index("ix_jobs_locked_at", "locked_at"),
    )

    job_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=JobStatus.PENDING.value, index=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    run_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(String(120))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    last_error: Mapped[str | None] = mapped_column(Text)


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"

    worker_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    hostname: Mapped[str | None] = mapped_column(String(255))
    process_id: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    version: Mapped[str | None] = mapped_column(String(64))


class AuditLog(IdMixin, Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_created_at", "created_at"),
        Index("ix_audit_logs_actor_action", "actor_user_id", "action"),
        Index("ix_audit_logs_target", "target_type", "target_id"),
    )

    actor_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False, default="system")
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    target_type: Mapped[str] = mapped_column(String(80), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(80))
    before_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    after_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class TrafficSnapshot(IdMixin, Base):
    __tablename__ = "traffic_snapshots"
    __table_args__ = (Index("ix_traffic_snapshots_device_sampled_at", "device_id", "sampled_at"),)

    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), nullable=False)
    sampled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    rx_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tx_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latest_handshake_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    endpoint: Mapped[str | None] = mapped_column(String(255))


class ServerSecret(IdMixin, Base):
    __tablename__ = "server_secrets"

    key: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    secret_type: Mapped[str] = mapped_column(String(64), nullable=False)
    ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    nonce: Mapped[str] = mapped_column(String(255), nullable=False)
    algorithm: Mapped[str] = mapped_column(String(64), nullable=False)
    key_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    is_secret: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )
