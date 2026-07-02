from __future__ import annotations


class DomainError(Exception):
    code = "domain_error"


class InvalidStateTransitionError(DomainError):
    code = "invalid_state_transition"


class AuthorizationError(DomainError):
    code = "authorization_denied"


class IpPoolExhaustedError(DomainError):
    code = "ip_pool_exhausted"


class SetupAlreadyCompletedError(DomainError):
    code = "setup_already_completed"


class PasswordPolicyError(DomainError):
    code = "password_policy_failed"


class AuthenticationError(DomainError):
    code = "authentication_failed"


class LoginRateLimitedError(DomainError):
    code = "login_rate_limited"


class CsrfError(DomainError):
    code = "csrf_failed"


class ValidationError(DomainError):
    code = "validation_failed"


class NotFoundError(DomainError):
    code = "not_found"


class ConflictError(DomainError):
    code = "conflict"


class QuotaExceededError(DomainError):
    code = "quota_exceeded"


class DownloadNotAvailableError(DomainError):
    code = "download_not_available"


class InstallerBuildError(DomainError):
    code = "installer_build_failed"
