from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
import smtplib

from sqlalchemy import func, select
from sqlalchemy.orm import Session as OrmSession

from yourvpn_core.config import AppSettings
from yourvpn_core.db.models import (
    AccessGroup,
    Application,
    ApprovalRecord,
    PasswordToken,
    User,
    UserAccessGroup,
)
from yourvpn_core.domain.enums import ApplicationStatus, Role, UserStatus
from yourvpn_core.modules.audit import AuditEvent, AuditModule
from yourvpn_core.modules.auth import AuthModule
from yourvpn_core.modules.authorization import Actor, AuthorizationModule, GrantableAccessGroup
from yourvpn_core.modules.errors import AuthorizationError, ConflictError, NotFoundError, ValidationError
from yourvpn_core.modules.state_machine import StateMachineModule


@dataclass(frozen=True)
class SubmitApplicationCommand:
    email: str
    display_name: str
    phone: str | None
    reason: str | None
    requested_device_count: int


@dataclass(frozen=True)
class ApproveApplicationCommand:
    approved_device_limit: int
    access_group_ids: list[str]
    expires_at: datetime | None = None
    reason: str | None = None


@dataclass(frozen=True)
class RejectApplicationCommand:
    reason: str | None = None


@dataclass(frozen=True)
class ApprovalResult:
    application: Application
    user: User
    password_token: PasswordToken
    setup_url: str
    notification_status: str


class ApplicationModule:
    def __init__(
        self,
        *,
        auth_module: AuthModule | None = None,
        audit_module: AuditModule | None = None,
        authorization_module: AuthorizationModule | None = None,
        state_machine: StateMachineModule | None = None,
    ) -> None:
        self.auth_module = auth_module or AuthModule()
        self.audit_module = audit_module or AuditModule()
        self.authorization_module = authorization_module or AuthorizationModule()
        self.state_machine = state_machine or StateMachineModule()

    def submit(
        self,
        db: OrmSession,
        command: SubmitApplicationCommand,
        *,
        ip_address: str,
        user_agent: str | None,
    ) -> Application:
        email = command.email.strip().lower()
        display_name = command.display_name.strip()
        if "@" not in email or email.startswith("@") or email.endswith("@"):
            raise ValidationError("Invalid email")
        if not display_name:
            raise ValidationError("Display name is required")
        if command.requested_device_count < 1 or command.requested_device_count > 3:
            raise ValidationError("Requested device count must be between 1 and 3")

        application = Application(
            email=email,
            display_name=display_name,
            phone=(command.phone or "").strip() or None,
            reason=(command.reason or "").strip() or None,
            requested_device_count=command.requested_device_count,
            status=ApplicationStatus.SUBMITTED.value,
            submitted_ip=ip_address,
            submitted_user_agent=user_agent,
        )
        db.add(application)
        db.flush()
        self.audit_module.record(
            db,
            AuditEvent(
                actor_type="anonymous",
                action="application.submitted",
                target_type="application",
                target_id=application.id,
                after_json={
                    "email": application.email,
                    "requested_device_count": application.requested_device_count,
                    "status": application.status,
                },
                ip_address=ip_address,
                user_agent=user_agent,
            ),
        )
        db.flush()
        return application

    def approve(
        self,
        db: OrmSession,
        application_id: str,
        command: ApproveApplicationCommand,
        *,
        actor: Actor,
        settings: AppSettings,
        ip_address: str,
        user_agent: str | None,
        now: datetime | None = None,
    ) -> ApprovalResult:
        self.authorization_module.require_role(actor, {Role.ADMIN, Role.APPROVER})
        if command.approved_device_limit < 1:
            raise ValidationError("Approved device limit must be at least 1")
        if command.approved_device_limit > 10:
            raise AuthorizationError("Approved device limit above 10 requires later admin adjustment")
        application = self._get_submitted_application(db, application_id)
        access_groups = self._load_access_groups(db, command.access_group_ids)
        self.authorization_module.can_grant_access_groups(
            actor,
            [
                GrantableAccessGroup(
                    access_group_id=access_group.id,
                    is_high_privilege=access_group.is_high_privilege,
                )
                for access_group in access_groups
            ],
        )

        existing_user = db.scalar(select(User).where(func.lower(User.email) == application.email.lower()))
        if existing_user is not None:
            raise ConflictError("A user already exists for this application email")

        self.state_machine.require_transition(
            ApplicationStatus(application.status),
            ApplicationStatus.ACCOUNT_SETUP_PENDING,
        )
        previous_status = application.status
        application.status = ApplicationStatus.ACCOUNT_SETUP_PENDING.value

        user = User(
            email=application.email,
            display_name=application.display_name,
            phone=application.phone,
            role=Role.USER.value,
            status=UserStatus.PENDING_PASSWORD.value,
            approved_device_limit=command.approved_device_limit,
            expires_at=command.expires_at,
        )
        db.add(user)
        db.flush()

        for access_group in access_groups:
            db.add(
                UserAccessGroup(
                    user_id=user.id,
                    access_group_id=access_group.id,
                    granted_by_user_id=actor.user_id,
                )
            )

        approval_record = ApprovalRecord(
            application_id=application.id,
            actor_user_id=actor.user_id,
            action="approve",
            approved_device_limit=command.approved_device_limit,
            reason=(command.reason or "").strip() or None,
            created_user_id=user.id,
        )
        db.add(approval_record)

        password_token, plaintext_token = self.auth_module.create_password_setup_token(
            db,
            user_id=user.id,
            expires_at=(now or datetime.now(UTC)) + timedelta(hours=settings.password_setup_token_ttl_hours),
            purpose="setup",
        )
        setup_url = f"{str(settings.public_base_url).rstrip('/')}/password/setup?token={plaintext_token}"
        notification_status = self._send_password_setup_email(
            settings=settings,
            application=application,
            user=user,
            setup_url=setup_url,
        )
        self.audit_module.record(
            db,
            AuditEvent(
                actor_user_id=actor.user_id,
                actor_type="user",
                action="application.approved",
                target_type="application",
                target_id=application.id,
                before_json={"status": previous_status},
                after_json={
                    "status": application.status,
                    "user_id": user.id,
                    "approved_device_limit": command.approved_device_limit,
                    "access_group_ids": [access_group.id for access_group in access_groups],
                    "notification_status": notification_status,
                },
                ip_address=ip_address,
                user_agent=user_agent,
            ),
        )
        db.flush()
        return ApprovalResult(
            application=application,
            user=user,
            password_token=password_token,
            setup_url=setup_url,
            notification_status=notification_status,
        )

    def reject(
        self,
        db: OrmSession,
        application_id: str,
        command: RejectApplicationCommand,
        *,
        actor: Actor,
        ip_address: str,
        user_agent: str | None,
    ) -> Application:
        self.authorization_module.require_role(actor, {Role.ADMIN, Role.APPROVER})
        application = self._get_submitted_application(db, application_id)
        self.state_machine.require_transition(
            ApplicationStatus(application.status),
            ApplicationStatus.REJECTED,
        )
        previous_status = application.status
        application.status = ApplicationStatus.REJECTED.value
        db.add(
            ApprovalRecord(
                application_id=application.id,
                actor_user_id=actor.user_id,
                action="reject",
                reason=(command.reason or "").strip() or None,
            )
        )
        self.audit_module.record(
            db,
            AuditEvent(
                actor_user_id=actor.user_id,
                actor_type="user",
                action="application.rejected",
                target_type="application",
                target_id=application.id,
                before_json={"status": previous_status},
                after_json={"status": application.status, "reason": command.reason},
                ip_address=ip_address,
                user_agent=user_agent,
            ),
        )
        db.flush()
        return application

    def _get_submitted_application(self, db: OrmSession, application_id: str) -> Application:
        application = db.get(Application, application_id)
        if application is None:
            raise NotFoundError("Application not found")
        if application.status != ApplicationStatus.SUBMITTED.value:
            raise ConflictError("Application is not pending approval")
        return application

    def _load_access_groups(self, db: OrmSession, access_group_ids: list[str]) -> list[AccessGroup]:
        unique_ids = list(dict.fromkeys(access_group_ids))
        rows = db.scalars(select(AccessGroup).where(AccessGroup.id.in_(unique_ids))).all()
        if len(rows) != len(unique_ids):
            raise NotFoundError("One or more access groups were not found")
        disabled = [row.id for row in rows if not row.enabled]
        if disabled:
            raise ValidationError("Disabled access groups cannot be granted")
        return rows

    def _send_password_setup_email(
        self,
        *,
        settings: AppSettings,
        application: Application,
        user: User,
        setup_url: str,
    ) -> str:
        if not settings.smtp_configured:
            return "not_configured"

        message = EmailMessage()
        message["From"] = settings.smtp_from
        message["To"] = user.email
        message["Subject"] = "WirePortal password setup"
        message.set_content(
            "\n".join(
                [
                    f"Hello {user.display_name},",
                    "",
                    "Your VPN access request has been approved.",
                    f"Application: {application.id}",
                    f"Password setup: {setup_url}",
                    "",
                    "This link is time limited.",
                ]
            )
        )

        try:
            with smtplib.SMTP(
                settings.smtp_host,
                settings.smtp_port,
                timeout=settings.smtp_timeout_seconds,
            ) as smtp:
                if settings.smtp_use_tls:
                    smtp.starttls()
                if settings.smtp_username:
                    smtp.login(settings.smtp_username, settings.smtp_password)
                smtp.send_message(message)
        except (OSError, smtplib.SMTPException):
            return "failed"

        return "sent"
