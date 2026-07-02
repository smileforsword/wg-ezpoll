from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session as OrmSession

from yourvpn_core.db.models import SystemSetting, User
from yourvpn_core.domain.enums import Role, UserStatus
from yourvpn_core.modules.audit import AuditEvent, AuditModule
from yourvpn_core.modules.auth import PasswordService
from yourvpn_core.modules.errors import SetupAlreadyCompletedError


SETUP_COMPLETED_KEY = "setup_completed"


@dataclass(frozen=True)
class SetupStatus:
    setup_completed: bool
    admin_exists: bool

    @property
    def setup_available(self) -> bool:
        return not self.setup_completed and not self.admin_exists


@dataclass(frozen=True)
class CompleteSetupCommand:
    email: str
    display_name: str
    password: str


@dataclass(frozen=True)
class SetupResult:
    user_id: str
    setup_completed: bool


class SetupModule:
    def __init__(
        self,
        *,
        password_service: PasswordService | None = None,
        audit_module: AuditModule | None = None,
    ) -> None:
        self.password_service = password_service or PasswordService()
        self.audit_module = audit_module or AuditModule()

    def get_status(self, db: OrmSession) -> SetupStatus:
        admin_count = db.scalar(select(func.count(User.id)).where(User.role == Role.ADMIN.value))
        setting = db.get(SystemSetting, SETUP_COMPLETED_KEY)
        setup_completed = bool(setting and setting.value_json.get("value") is True)
        return SetupStatus(
            setup_completed=setup_completed,
            admin_exists=bool(admin_count),
        )

    def complete_setup(
        self,
        db: OrmSession,
        command: CompleteSetupCommand,
        *,
        ip_address: str,
        user_agent: str | None,
        now: datetime | None = None,
    ) -> SetupResult:
        status = self.get_status(db)
        if not status.setup_available:
            self.audit_module.record(
                db,
                AuditEvent(
                    actor_type="anonymous",
                    action="setup.rejected",
                    target_type="setup",
                    after_json={
                        "setup_completed": status.setup_completed,
                        "admin_exists": status.admin_exists,
                    },
                    ip_address=ip_address,
                    user_agent=user_agent,
                ),
            )
            raise SetupAlreadyCompletedError("Setup has already been completed")

        email = command.email.strip().lower()
        user = User(
            email=email,
            display_name=command.display_name.strip() or email,
            role=Role.ADMIN.value,
            status=UserStatus.ACTIVE.value,
            password_hash=self.password_service.hash_password(command.password),
            approved_device_limit=0,
        )
        db.add(user)
        db.flush()

        setting = SystemSetting(
            key=SETUP_COMPLETED_KEY,
            value_json={"value": True, "completed_at": (now or datetime.now(UTC)).isoformat()},
            is_secret=False,
        )
        db.merge(setting)
        self.audit_module.record(
            db,
            AuditEvent(
                actor_user_id=user.id,
                actor_type="user",
                action="setup.completed",
                target_type="user",
                target_id=user.id,
                after_json={"role": user.role, "email": user.email},
                ip_address=ip_address,
                user_agent=user_agent,
            ),
        )
        db.flush()
        return SetupResult(user_id=user.id, setup_completed=True)
