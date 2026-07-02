from __future__ import annotations

from enum import StrEnum

from yourvpn_core.domain.enums import (
    ApplicationStatus,
    DeviceStatus,
    InstallPackageStatus,
    JobStatus,
    UserStatus,
)
from yourvpn_core.modules.errors import InvalidStateTransitionError


State = ApplicationStatus | UserStatus | DeviceStatus | InstallPackageStatus | JobStatus


class StateMachineModule:
    _allowed: dict[type[StrEnum], dict[StrEnum, set[StrEnum]]] = {
        ApplicationStatus: {
            ApplicationStatus.SUBMITTED: {
                ApplicationStatus.APPROVED,
                ApplicationStatus.ACCOUNT_SETUP_PENDING,
                ApplicationStatus.REJECTED,
                ApplicationStatus.CANCELLED,
            },
            ApplicationStatus.APPROVED: {ApplicationStatus.ACCOUNT_SETUP_PENDING},
            ApplicationStatus.ACCOUNT_SETUP_PENDING: {
                ApplicationStatus.ACTIVE,
                ApplicationStatus.DISABLED,
                ApplicationStatus.EXPIRED,
            },
            ApplicationStatus.ACTIVE: {ApplicationStatus.DISABLED, ApplicationStatus.EXPIRED},
            ApplicationStatus.REJECTED: set(),
            ApplicationStatus.CANCELLED: set(),
            ApplicationStatus.DISABLED: set(),
            ApplicationStatus.EXPIRED: set(),
        },
        UserStatus: {
            UserStatus.PENDING_PASSWORD: {UserStatus.ACTIVE, UserStatus.DISABLED, UserStatus.EXPIRED},
            UserStatus.ACTIVE: {UserStatus.DISABLED, UserStatus.EXPIRED},
            UserStatus.DISABLED: set(),
            UserStatus.EXPIRED: set(),
        },
        DeviceStatus: {
            DeviceStatus.DRAFT: {DeviceStatus.PENDING_APPROVAL, DeviceStatus.PENDING_BUILD},
            DeviceStatus.PENDING_APPROVAL: {DeviceStatus.PENDING_BUILD, DeviceStatus.REVOKED},
            DeviceStatus.PENDING_BUILD: {DeviceStatus.BUILT, DeviceStatus.REVOKED},
            DeviceStatus.BUILT: {DeviceStatus.READY_TO_DOWNLOAD, DeviceStatus.REVOKED},
            DeviceStatus.READY_TO_DOWNLOAD: {DeviceStatus.DOWNLOADING, DeviceStatus.EXPIRED, DeviceStatus.REVOKED},
            DeviceStatus.DOWNLOADING: {
                DeviceStatus.DOWNLOAD_CONFIRMED,
                DeviceStatus.READY_TO_DOWNLOAD,
                DeviceStatus.EXPIRED,
                DeviceStatus.REVOKED,
            },
            DeviceStatus.DOWNLOAD_CONFIRMED: {DeviceStatus.ACTIVE},
            DeviceStatus.ACTIVE: {
                DeviceStatus.DISABLED,
                DeviceStatus.REVOKED,
                DeviceStatus.EXPIRED,
                DeviceStatus.RESET_PENDING,
            },
            DeviceStatus.RESET_PENDING: {DeviceStatus.PENDING_BUILD, DeviceStatus.REVOKED},
            DeviceStatus.DISABLED: set(),
            DeviceStatus.REVOKED: set(),
            DeviceStatus.EXPIRED: set(),
        },
        InstallPackageStatus: {
            InstallPackageStatus.PENDING_BUILD: {InstallPackageStatus.BUILDING, InstallPackageStatus.FAILED},
            InstallPackageStatus.BUILDING: {
                InstallPackageStatus.READY_TO_DOWNLOAD,
                InstallPackageStatus.FAILED,
            },
            InstallPackageStatus.READY_TO_DOWNLOAD: {
                InstallPackageStatus.DOWNLOADING,
                InstallPackageStatus.EXPIRED,
                InstallPackageStatus.REVOKED,
            },
            InstallPackageStatus.DOWNLOADING: {
                InstallPackageStatus.DOWNLOAD_CONFIRMED,
                InstallPackageStatus.READY_TO_DOWNLOAD,
                InstallPackageStatus.EXPIRED,
                InstallPackageStatus.REVOKED,
            },
            InstallPackageStatus.DOWNLOAD_CONFIRMED: {InstallPackageStatus.ARTIFACT_DELETED},
            InstallPackageStatus.ARTIFACT_DELETED: set(),
            InstallPackageStatus.EXPIRED: {InstallPackageStatus.ARTIFACT_DELETED},
            InstallPackageStatus.REVOKED: {InstallPackageStatus.ARTIFACT_DELETED},
            InstallPackageStatus.FAILED: {InstallPackageStatus.PENDING_BUILD, InstallPackageStatus.BUILDING},
        },
        JobStatus: {
            JobStatus.PENDING: {JobStatus.RUNNING, JobStatus.CANCELLED},
            JobStatus.RUNNING: {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.PENDING},
            JobStatus.SUCCEEDED: set(),
            JobStatus.FAILED: {JobStatus.PENDING, JobStatus.CANCELLED},
            JobStatus.CANCELLED: set(),
        },
    }

    def can_transition(self, current: State, target: State) -> bool:
        if type(current) is not type(target):
            return False
        return target == current or target in self._allowed[type(current)].get(current, set())

    def require_transition(self, current: State, target: State) -> None:
        if not self.can_transition(current, target):
            raise InvalidStateTransitionError(f"Cannot transition {current} -> {target}")
