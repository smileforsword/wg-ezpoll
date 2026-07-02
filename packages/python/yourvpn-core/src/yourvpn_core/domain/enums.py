from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    USER = "user"
    APPROVER = "approver"
    ADMIN = "admin"


class ApplicationStatus(StrEnum):
    SUBMITTED = "submitted"
    APPROVED = "approved"
    ACCOUNT_SETUP_PENDING = "account_setup_pending"
    ACTIVE = "active"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    DISABLED = "disabled"
    EXPIRED = "expired"


class UserStatus(StrEnum):
    PENDING_PASSWORD = "pending_password"
    ACTIVE = "active"
    DISABLED = "disabled"
    EXPIRED = "expired"


class DeviceStatus(StrEnum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    PENDING_BUILD = "pending_build"
    BUILT = "built"
    READY_TO_DOWNLOAD = "ready_to_download"
    DOWNLOADING = "downloading"
    DOWNLOAD_CONFIRMED = "download_confirmed"
    ACTIVE = "active"
    DISABLED = "disabled"
    REVOKED = "revoked"
    EXPIRED = "expired"
    RESET_PENDING = "reset_pending"


class InstallPackageStatus(StrEnum):
    PENDING_BUILD = "pending_build"
    BUILDING = "building"
    READY_TO_DOWNLOAD = "ready_to_download"
    DOWNLOADING = "downloading"
    DOWNLOAD_CONFIRMED = "download_confirmed"
    ARTIFACT_DELETED = "artifact_deleted"
    EXPIRED = "expired"
    REVOKED = "revoked"
    FAILED = "failed"


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
