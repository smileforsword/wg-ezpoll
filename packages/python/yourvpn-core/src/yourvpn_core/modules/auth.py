from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import secrets
from typing import Literal

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session as OrmSession

from yourvpn_core.db.models import (
    AuditLog,
    LoginAttempt,
    PasswordToken,
    Session as UserSession,
    User,
)
from yourvpn_core.domain.enums import UserStatus
from yourvpn_core.modules.audit import AuditEvent, AuditModule
from yourvpn_core.modules.errors import (
    AuthenticationError,
    CsrfError,
    LoginRateLimitedError,
    PasswordPolicyError,
)


@dataclass(frozen=True)
class LoginCommand:
    email: str
    password: str


@dataclass(frozen=True)
class LoginResult:
    user_id: str
    session_id: str
    session_token: str
    csrf_token: str
    expires_at: datetime


@dataclass(frozen=True)
class SetupPasswordCommand:
    token: str
    password: str


@dataclass(frozen=True)
class AuthenticatedSession:
    user: User
    session: UserSession


class PasswordService:
    def __init__(self) -> None:
        self._hasher = PasswordHasher(type=Type.ID)

    def validate_password_policy(self, password: str) -> None:
        if len(password) < 8:
            raise PasswordPolicyError("Password must be at least 8 characters")
        if not any(character.isalpha() for character in password):
            raise PasswordPolicyError("Password must contain a letter")
        if not any(character.isdigit() for character in password):
            raise PasswordPolicyError("Password must contain a number")

    def hash_password(self, password: str) -> str:
        self.validate_password_policy(password)
        return self._hasher.hash(password)

    def verify_password(self, password_hash: str | None, password: str) -> bool:
        if not password_hash:
            return False
        try:
            return self._hasher.verify(password_hash, password)
        except (InvalidHashError, VerificationError, VerifyMismatchError):
            return False


def generate_secret_token() -> str:
    return secrets.token_urlsafe(32)


def hash_secret(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


class AuthModule:
    def __init__(
        self,
        *,
        password_service: PasswordService | None = None,
        audit_module: AuditModule | None = None,
    ) -> None:
        self.password_service = password_service or PasswordService()
        self.audit_module = audit_module or AuditModule()

    def login(
        self,
        db: OrmSession,
        command: LoginCommand,
        *,
        ip_address: str,
        user_agent: str | None,
        session_ttl: timedelta,
        rate_limit_attempts: int,
        rate_limit_window: timedelta,
        now: datetime | None = None,
    ) -> LoginResult:
        current_time = now or datetime.now(UTC)
        email = command.email.strip().lower()

        if self._is_rate_limited(
            db,
            email=email,
            ip_address=ip_address,
            now=current_time,
            window=rate_limit_window,
            max_attempts=rate_limit_attempts,
        ):
            self._record_login_attempt(
                db,
                email=email,
                ip_address=ip_address,
                success=False,
                failure_reason="rate_limited",
                actor_type="anonymous",
            )
            raise LoginRateLimitedError("Too many failed login attempts")

        user = db.scalar(select(User).where(func.lower(User.email) == email))
        if user is None or user.status != UserStatus.ACTIVE.value:
            self._record_login_attempt(
                db,
                email=email,
                ip_address=ip_address,
                success=False,
                failure_reason="invalid_credentials_or_status",
                actor_type="anonymous",
            )
            raise AuthenticationError("Invalid email or password")

        if not self.password_service.verify_password(user.password_hash, command.password):
            self._record_login_attempt(
                db,
                email=email,
                ip_address=ip_address,
                success=False,
                failure_reason="invalid_credentials",
                actor_type="user",
                actor_user_id=user.id,
            )
            raise AuthenticationError("Invalid email or password")

        session_token = generate_secret_token()
        csrf_token = generate_secret_token()
        session = UserSession(
            user_id=user.id,
            session_token_hash=hash_secret(session_token),
            csrf_token_hash=hash_secret(csrf_token),
            ip_address=ip_address,
            user_agent=user_agent,
            expires_at=current_time + session_ttl,
        )
        db.add(session)
        self._record_login_attempt(
            db,
            email=email,
            ip_address=ip_address,
            success=True,
            failure_reason=None,
            actor_type="user",
            actor_user_id=user.id,
        )
        db.flush()
        return LoginResult(
            user_id=user.id,
            session_id=session.id,
            session_token=session_token,
            csrf_token=csrf_token,
            expires_at=session.expires_at,
        )

    def logout(self, db: OrmSession, session_id: str, *, now: datetime | None = None) -> None:
        session = db.get(UserSession, session_id)
        if session is None:
            return
        session.revoked_at = now or datetime.now(UTC)
        db.flush()

    def create_password_setup_token(
        self,
        db: OrmSession,
        *,
        user_id: str,
        expires_at: datetime,
        purpose: Literal["setup", "reset"] = "setup",
    ) -> tuple[PasswordToken, str]:
        token = generate_secret_token()
        row = PasswordToken(
            user_id=user_id,
            token_hash=hash_secret(token),
            purpose=purpose,
            expires_at=expires_at,
        )
        db.add(row)
        db.flush()
        return row, token

    def setup_password(
        self,
        db: OrmSession,
        command: SetupPasswordCommand,
        *,
        ip_address: str,
        user_agent: str | None,
        now: datetime | None = None,
    ) -> User:
        current_time = now or datetime.now(UTC)
        token_hash = hash_secret(command.token)
        token = db.scalar(
            select(PasswordToken).where(
                PasswordToken.token_hash == token_hash,
                PasswordToken.used_at.is_(None),
                PasswordToken.expires_at > current_time,
            )
        )
        if token is None:
            self.audit_module.record(
                db,
                AuditEvent(
                    actor_type="anonymous",
                    action="auth.password_setup_rejected",
                    target_type="password_token",
                    target_id=None,
                    after_json={"reason": "invalid_or_expired_token"},
                    ip_address=ip_address,
                    user_agent=user_agent,
                ),
            )
            raise AuthenticationError("Password setup token is invalid or expired")

        user = db.get(User, token.user_id)
        if user is None or user.status not in {UserStatus.PENDING_PASSWORD.value, UserStatus.ACTIVE.value}:
            raise AuthenticationError("Password setup token is invalid or expired")

        user.password_hash = self.password_service.hash_password(command.password)
        user.status = UserStatus.ACTIVE.value
        token.used_at = current_time
        self.audit_module.record(
            db,
            AuditEvent(
                actor_user_id=user.id,
                actor_type="user",
                action="auth.password_setup",
                target_type="user",
                target_id=user.id,
                after_json={"status": user.status, "purpose": token.purpose},
                ip_address=ip_address,
                user_agent=user_agent,
            ),
        )
        db.flush()
        return user

    def authenticate_session(
        self,
        db: OrmSession,
        session_token: str | None,
        *,
        now: datetime | None = None,
    ) -> AuthenticatedSession:
        if not session_token:
            raise AuthenticationError("Missing session")
        current_time = now or datetime.now(UTC)
        row = db.scalar(
            select(UserSession).where(
                UserSession.session_token_hash == hash_secret(session_token),
                UserSession.revoked_at.is_(None),
                UserSession.expires_at > current_time,
            )
        )
        if row is None:
            raise AuthenticationError("Invalid session")
        user = db.get(User, row.user_id)
        if user is None or user.status != UserStatus.ACTIVE.value:
            raise AuthenticationError("Invalid session")
        return AuthenticatedSession(user=user, session=row)

    def require_csrf(self, authenticated: AuthenticatedSession, submitted_token: str | None) -> None:
        if not submitted_token:
            raise CsrfError("Missing CSRF token")
        if not secrets.compare_digest(authenticated.session.csrf_token_hash, hash_secret(submitted_token)):
            raise CsrfError("Invalid CSRF token")

    def _is_rate_limited(
        self,
        db: OrmSession,
        *,
        email: str,
        ip_address: str,
        now: datetime,
        window: timedelta,
        max_attempts: int,
    ) -> bool:
        since = now - window
        failed_count = db.scalar(
            select(func.count(LoginAttempt.id)).where(
                LoginAttempt.success.is_(False),
                LoginAttempt.created_at >= since,
                or_(func.lower(LoginAttempt.email) == email, LoginAttempt.ip_address == ip_address),
            )
        )
        return int(failed_count or 0) >= max_attempts

    def _record_login_attempt(
        self,
        db: OrmSession,
        *,
        email: str,
        ip_address: str,
        success: bool,
        failure_reason: str | None,
        actor_type: str,
        actor_user_id: str | None = None,
    ) -> None:
        db.add(
            LoginAttempt(
                email=email,
                ip_address=ip_address,
                success=success,
                failure_reason=failure_reason,
            )
        )
        if not success:
            db.add(
                AuditLog(
                    actor_user_id=actor_user_id,
                    actor_type=actor_type,
                    action="auth.login_rejected",
                    target_type="user",
                    target_id=actor_user_id,
                    after_json={"email": email, "reason": failure_reason},
                    ip_address=ip_address,
                )
            )
