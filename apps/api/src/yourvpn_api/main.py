from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta
from ipaddress import ip_network

from fastapi import Cookie, Depends, FastAPI, Header, Request, Response, status
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session as OrmSession, sessionmaker

from yourvpn_core.config import AppSettings, load_settings
from yourvpn_core.db.models import (
    AccessGroup,
    AccessGroupRoute,
    Application,
    ApprovalRecord,
    AuditLog,
    Device,
    InstallPackage,
    Job,
    User,
    UserAccessGroup,
)
from yourvpn_core.db.session import create_db_engine, create_session_factory
from yourvpn_core.domain.enums import ApplicationStatus, DeviceStatus, InstallPackageStatus, JobStatus, Role
from yourvpn_core.health import build_health_status
from yourvpn_core.logging import configure_logging
from yourvpn_core.modules import (
    AuthenticatedSession,
    Actor,
    AuthModule,
    AuthorizationModule,
    CompleteSetupCommand,
    CreateDeviceCommand,
    ApplicationModule,
    ApproveApplicationCommand,
    DeviceModule,
    LoginCommand,
    RejectApplicationCommand,
    RequestContext,
    SetupModule,
    SetupPasswordCommand,
    SubmitApplicationCommand,
    UnixSocketWgAgentClient,
)
from yourvpn_core.modules.audit import AuditEvent, AuditModule
from yourvpn_core.modules.errors import (
    AuthenticationError,
    AuthorizationError,
    CsrfError,
    ConflictError,
    DownloadNotAvailableError,
    DomainError,
    InstallerBuildError,
    LoginRateLimitedError,
    NotFoundError,
    PasswordPolicyError,
    QuotaExceededError,
    SetupAlreadyCompletedError,
    ValidationError,
)


class ErrorResponse(BaseModel):
    code: str
    message: str
    details: dict[str, object] | None = None


class SetupStatusResponse(BaseModel):
    setup_completed: bool
    admin_exists: bool
    setup_available: bool


class SetupRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    display_name: str = Field(min_length=1, max_length=160)
    password: str

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
            raise ValueError("Invalid email")
        return normalized


class SetupResponse(BaseModel):
    setup_completed: bool
    user_id: str


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
            raise ValueError("Invalid email")
        return normalized


class LoginResponse(BaseModel):
    user_id: str
    csrf_token: str
    expires_at: str


class MeResponse(BaseModel):
    user_id: str
    email: str
    display_name: str
    role: str


class PasswordSetupRequest(BaseModel):
    token: str
    password: str


class PasswordSetupResponse(BaseModel):
    user_id: str
    status: str


class SubmitApplicationRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    display_name: str = Field(min_length=1, max_length=160)
    phone: str | None = Field(default=None, max_length=64)
    reason: str | None = Field(default=None, max_length=2000)
    requested_device_count: int = Field(ge=1, le=3)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
            raise ValueError("Invalid email")
        return normalized


class SubmitApplicationResponse(BaseModel):
    submitted: bool
    application_id: str


class AccessGroupResponse(BaseModel):
    id: str
    name: str
    description: str | None
    is_high_privilege: bool
    enabled: bool


class AccessGroupRouteResponse(BaseModel):
    id: str
    cidr: str
    description: str | None
    enabled: bool


class AccessGroupDetailResponse(AccessGroupResponse):
    routes: list[AccessGroupRouteResponse]


class CreateAccessGroupRouteRequest(BaseModel):
    cidr: str = Field(min_length=3, max_length=64)
    description: str | None = Field(default=None, max_length=500)
    enabled: bool = True


class CreateAccessGroupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    is_high_privilege: bool = False
    enabled: bool = True
    routes: list[CreateAccessGroupRouteRequest] = Field(default_factory=list)


class ApplicationSummaryResponse(BaseModel):
    id: str
    email: str
    display_name: str
    requested_device_count: int
    status: str
    created_at: str


class ApprovalRecordResponse(BaseModel):
    id: str
    action: str
    actor_user_id: str | None
    approved_device_limit: int | None
    reason: str | None
    created_user_id: str | None
    created_at: str


class ApplicationDetailResponse(BaseModel):
    id: str
    email: str
    display_name: str
    phone: str | None
    reason: str | None
    requested_device_count: int
    status: str
    submitted_ip: str | None
    submitted_user_agent: str | None
    created_at: str
    updated_at: str
    approval_records: list[ApprovalRecordResponse]


class ApproveApplicationRequest(BaseModel):
    approved_device_limit: int = Field(ge=1, le=10)
    access_group_ids: list[str] = Field(default_factory=list)
    expires_at: str | None = None
    reason: str | None = Field(default=None, max_length=2000)


class ApproveApplicationResponse(BaseModel):
    application_id: str
    user_id: str
    status: str
    setup_url: str
    notification_status: str


class RejectApplicationRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)


class RejectApplicationResponse(BaseModel):
    application_id: str
    status: str


class CreateDeviceRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)


class PackageResponse(BaseModel):
    id: str
    device_id: str
    status: str
    file_name: str | None
    sha256: str | None
    file_size: int | None
    signed_status: str
    config_format: str
    download_attempts: int
    max_download_attempts: int
    download_expires_at: str | None
    confirmed_at: str | None
    artifact_deleted_at: str | None
    can_download: bool


class DeviceResponse(BaseModel):
    id: str
    name: str
    status: str
    public_key: str | None
    vpn_ip: str
    latest_handshake_at: str | None
    latest_endpoint: str | None
    rx_bytes: int
    tx_bytes: int
    current_package: PackageResponse | None


class CreateDeviceResponse(BaseModel):
    device: DeviceResponse
    package: PackageResponse


class ConfirmDownloadResponse(BaseModel):
    package_id: str
    status: str
    artifact_deleted_at: str | None
    apply_peer_job_enqueued: bool


class ReportLostResponse(BaseModel):
    device_id: str
    lost_reported_at: str | None


class AdminDeviceResponse(BaseModel):
    id: str
    user_id: str
    user_email: str | None = None
    user_display_name: str | None = None
    name: str
    status: str
    public_key: str | None
    vpn_ip: str
    revoked_at: str | None
    current_package: PackageResponse | None


class AdminUserResponse(BaseModel):
    id: str
    email: str
    display_name: str
    phone: str | None
    role: str
    status: str
    approved_device_limit: int
    expires_at: str | None
    created_at: str
    device_count: int


class AuditLogResponse(BaseModel):
    id: str
    actor_user_id: str | None
    actor_type: str
    action: str
    target_type: str
    target_id: str | None
    before_json: dict[str, object] | None
    after_json: dict[str, object] | None
    ip_address: str | None
    user_agent: str | None
    created_at: str


def _request_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "0.0.0.0"


def _error_status(exc: DomainError) -> int:
    if isinstance(exc, (AuthenticationError, CsrfError)):
        return status.HTTP_401_UNAUTHORIZED
    if isinstance(exc, LoginRateLimitedError):
        return status.HTTP_429_TOO_MANY_REQUESTS
    if isinstance(exc, (AuthorizationError, SetupAlreadyCompletedError)):
        return status.HTTP_403_FORBIDDEN
    if isinstance(exc, NotFoundError):
        return status.HTTP_404_NOT_FOUND
    if isinstance(exc, (ConflictError, DownloadNotAvailableError, InstallerBuildError, QuotaExceededError)):
        return status.HTTP_409_CONFLICT
    if isinstance(exc, (PasswordPolicyError, ValidationError)):
        return status.HTTP_422_UNPROCESSABLE_ENTITY
    return status.HTTP_400_BAD_REQUEST


def _actor_from_session(authenticated: AuthenticatedSession) -> Actor:
    return Actor(
        user_id=authenticated.user.id,
        role=Role(authenticated.user.role),
        email=authenticated.user.email,
    )


def _parse_optional_datetime(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationError("expires_at must be an ISO datetime") from exc


def _application_summary(application: Application) -> ApplicationSummaryResponse:
    return ApplicationSummaryResponse(
        id=application.id,
        email=application.email,
        display_name=application.display_name,
        requested_device_count=application.requested_device_count,
        status=application.status,
        created_at=application.created_at.isoformat(),
    )


def _application_detail(
    application: Application,
    approval_records: list[ApprovalRecord],
) -> ApplicationDetailResponse:
    return ApplicationDetailResponse(
        id=application.id,
        email=application.email,
        display_name=application.display_name,
        phone=application.phone,
        reason=application.reason,
        requested_device_count=application.requested_device_count,
        status=application.status,
        submitted_ip=application.submitted_ip,
        submitted_user_agent=application.submitted_user_agent,
        created_at=application.created_at.isoformat(),
        updated_at=application.updated_at.isoformat(),
        approval_records=[
            ApprovalRecordResponse(
                id=record.id,
                action=record.action,
                actor_user_id=record.actor_user_id,
                approved_device_limit=record.approved_device_limit,
                reason=record.reason,
                created_user_id=record.created_user_id,
                created_at=record.created_at.isoformat(),
            )
            for record in approval_records
        ],
    )


def _access_group_response(group: AccessGroup, routes: list[AccessGroupRoute] | None = None):
    if routes is None:
        return AccessGroupResponse(
            id=group.id,
            name=group.name,
            description=group.description,
            is_high_privilege=group.is_high_privilege,
            enabled=group.enabled,
        )
    return AccessGroupDetailResponse(
        id=group.id,
        name=group.name,
        description=group.description,
        is_high_privilege=group.is_high_privilege,
        enabled=group.enabled,
        routes=[
            AccessGroupRouteResponse(
                id=route.id,
                cidr=route.cidr,
                description=route.description,
                enabled=route.enabled,
            )
            for route in routes
        ],
    )


def _package_can_download(package: InstallPackage) -> bool:
    return (
        package.status in {InstallPackageStatus.READY_TO_DOWNLOAD.value, InstallPackageStatus.DOWNLOADING.value}
        and package.confirmed_at is None
        and package.artifact_deleted_at is None
    )


def _package_response(package: InstallPackage) -> PackageResponse:
    return PackageResponse(
        id=package.id,
        device_id=package.device_id,
        status=package.status,
        file_name=package.file_name,
        sha256=package.sha256,
        file_size=package.file_size,
        signed_status=package.signed_status,
        config_format=package.config_format,
        download_attempts=package.download_attempts,
        max_download_attempts=package.max_download_attempts,
        download_expires_at=package.download_expires_at.isoformat() if package.download_expires_at else None,
        confirmed_at=package.confirmed_at.isoformat() if package.confirmed_at else None,
        artifact_deleted_at=package.artifact_deleted_at.isoformat() if package.artifact_deleted_at else None,
        can_download=_package_can_download(package),
    )


def _latest_package(db: OrmSession, device_id: str) -> InstallPackage | None:
    return db.scalars(
        select(InstallPackage)
        .where(InstallPackage.device_id == device_id)
        .order_by(InstallPackage.created_at.desc())
        .limit(1)
    ).first()


def _device_response(db: OrmSession, device: Device) -> DeviceResponse:
    package = _latest_package(db, device.id)
    return DeviceResponse(
        id=device.id,
        name=device.name,
        status=device.status,
        public_key=device.public_key,
        vpn_ip=device.vpn_ip,
        latest_handshake_at=device.latest_handshake_at.isoformat() if device.latest_handshake_at else None,
        latest_endpoint=device.latest_endpoint,
        rx_bytes=device.rx_bytes,
        tx_bytes=device.tx_bytes,
        current_package=_package_response(package) if package else None,
    )


def _admin_device_response(db: OrmSession, device: Device) -> AdminDeviceResponse:
    package = _latest_package(db, device.id)
    user = db.get(User, device.user_id)
    return AdminDeviceResponse(
        id=device.id,
        user_id=device.user_id,
        user_email=user.email if user else None,
        user_display_name=user.display_name if user else None,
        name=device.name,
        status=device.status,
        public_key=device.public_key,
        vpn_ip=device.vpn_ip,
        revoked_at=device.revoked_at.isoformat() if device.revoked_at else None,
        current_package=_package_response(package) if package else None,
    )


def _admin_user_response(db: OrmSession, user: User) -> AdminUserResponse:
    device_count = int(db.scalar(select(func.count(Device.id)).where(Device.user_id == user.id)) or 0)
    return AdminUserResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        phone=user.phone,
        role=user.role,
        status=user.status,
        approved_device_limit=user.approved_device_limit,
        expires_at=user.expires_at.isoformat() if user.expires_at else None,
        created_at=user.created_at.isoformat(),
        device_count=device_count,
    )


def _audit_log_response(row: AuditLog) -> AuditLogResponse:
    return AuditLogResponse(
        id=row.id,
        actor_user_id=row.actor_user_id,
        actor_type=row.actor_type,
        action=row.action,
        target_type=row.target_type,
        target_id=row.target_id,
        before_json=row.before_json,
        after_json=row.after_json,
        ip_address=row.ip_address,
        user_agent=row.user_agent,
        created_at=row.created_at.isoformat(),
    )


def _domain_error_response(exc: DomainError) -> JSONResponse:
    return JSONResponse(
        status_code=_error_status(exc),
        content=ErrorResponse(code=exc.code, message=str(exc)).model_dump(),
    )


def _set_session_cookie(
    response: Response,
    *,
    settings: AppSettings,
    session_token: str,
    max_age_seconds: int,
) -> None:
    response.set_cookie(
        settings.session_cookie_name,
        session_token,
        max_age=max_age_seconds,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="strict",
        path="/",
    )


def _clear_session_cookie(response: Response, *, settings: AppSettings) -> None:
    response.delete_cookie(settings.session_cookie_name, path="/")


def create_app(
    settings: AppSettings | None = None,
    *,
    session_factory: sessionmaker[OrmSession] | None = None,
) -> FastAPI:
    resolved_settings = settings or load_settings()
    configure_logging(resolved_settings, service="api")

    api = FastAPI(
        title="WirePortal API",
        version="0.1.0",
    )
    if session_factory is None:
        engine = create_db_engine(resolved_settings.database_url)
        session_factory = create_session_factory(engine)

    api.state.settings = resolved_settings
    api.state.session_factory = session_factory
    api.state.setup_module = SetupModule()
    api.state.auth_module = AuthModule()
    api.state.audit_module = AuditModule()
    api.state.authorization_module = AuthorizationModule()
    api.state.application_module = ApplicationModule(
        auth_module=api.state.auth_module,
        audit_module=api.state.audit_module,
        authorization_module=api.state.authorization_module,
    )
    api.state.device_module = DeviceModule(audit_module=api.state.audit_module)

    @api.exception_handler(DomainError)
    async def domain_error_handler(_request: Request, exc: DomainError):
        return _domain_error_response(exc)

    def get_db() -> Iterator[OrmSession]:
        db = api.state.session_factory()
        try:
            yield db
        finally:
            db.close()

    def get_settings() -> AppSettings:
        return api.state.settings

    def get_auth_module() -> AuthModule:
        return api.state.auth_module

    def get_setup_module() -> SetupModule:
        return api.state.setup_module

    def get_application_module() -> ApplicationModule:
        return api.state.application_module

    def get_device_module() -> DeviceModule:
        return api.state.device_module

    def get_current_session(
        db: OrmSession = Depends(get_db),
        auth: AuthModule = Depends(get_auth_module),
        session_token: str | None = Cookie(default=None, alias=resolved_settings.session_cookie_name),
    ) -> AuthenticatedSession:
        try:
            return auth.authenticate_session(db, session_token)
        except DomainError as exc:
            raise exc

    def require_csrf(
        authenticated: AuthenticatedSession = Depends(get_current_session),
        auth: AuthModule = Depends(get_auth_module),
        csrf_token: str | None = Header(default=None, alias=resolved_settings.csrf_header_name),
    ) -> AuthenticatedSession:
        try:
            auth.require_csrf(authenticated, csrf_token)
        except DomainError as exc:
            raise exc
        return authenticated

    def require_admin_actor(
        authenticated: AuthenticatedSession = Depends(get_current_session),
    ) -> Actor:
        actor = _actor_from_session(authenticated)
        api.state.authorization_module.require_role(actor, {Role.ADMIN, Role.APPROVER})
        return actor

    def require_admin_actor_with_csrf(
        authenticated: AuthenticatedSession = Depends(require_csrf),
    ) -> Actor:
        actor = _actor_from_session(authenticated)
        api.state.authorization_module.require_role(actor, {Role.ADMIN, Role.APPROVER})
        return actor

    @api.middleware("http")
    async def admin_ip_whitelist_middleware(request: Request, call_next):
        if request.url.path.startswith("/api/admin/"):
            allowed_cidrs = resolved_settings.admin_ip_whitelist_cidrs()
            try:
                api.state.authorization_module.require_admin_ip_allowed(
                    RequestContext(ip_address=_request_ip(request), user_agent=request.headers.get("user-agent")),
                    allowed_cidrs,
                )
            except AuthorizationError as exc:
                db = api.state.session_factory()
                try:
                    api.state.audit_module.record(
                        db,
                        AuditEvent(
                            actor_type="anonymous",
                            action="security.admin_ip_rejected",
                            target_type="api_path",
                            target_id=request.url.path,
                            after_json={"ip": _request_ip(request)},
                            ip_address=_request_ip(request),
                            user_agent=request.headers.get("user-agent"),
                        ),
                    )
                    db.commit()
                finally:
                    db.close()
                return _domain_error_response(exc)
        return await call_next(request)

    @api.get("/health", tags=["health"])
    def health():
        return build_health_status(
            service="api",
            settings=resolved_settings,
            details={
                "database_url_configured": bool(resolved_settings.database_url),
                "wg_agent_socket_path": resolved_settings.wg_agent_socket_path,
            },
        )

    @api.get("/api/health", tags=["health"])
    def api_health():
        return health()

    @api.get("/api/setup/status", response_model=SetupStatusResponse, tags=["setup"])
    def setup_status(
        db: OrmSession = Depends(get_db),
        setup_module: SetupModule = Depends(get_setup_module),
    ):
        status_result = setup_module.get_status(db)
        return SetupStatusResponse(
            setup_completed=status_result.setup_completed,
            admin_exists=status_result.admin_exists,
            setup_available=status_result.setup_available,
        )

    @api.post("/api/setup", response_model=SetupResponse, tags=["setup"])
    def complete_setup(
        payload: SetupRequest,
        request: Request,
        db: OrmSession = Depends(get_db),
        setup_module: SetupModule = Depends(get_setup_module),
    ):
        try:
            result = setup_module.complete_setup(
                db,
                CompleteSetupCommand(
                    email=str(payload.email),
                    display_name=payload.display_name,
                    password=payload.password,
                ),
                ip_address=_request_ip(request),
                user_agent=request.headers.get("user-agent"),
            )
            db.commit()
        except DomainError as exc:
            db.commit()
            return _domain_error_response(exc)

        return SetupResponse(setup_completed=result.setup_completed, user_id=result.user_id)

    @api.post("/api/auth/login", response_model=LoginResponse, tags=["auth"])
    def login(
        payload: LoginRequest,
        request: Request,
        response: Response,
        db: OrmSession = Depends(get_db),
        auth: AuthModule = Depends(get_auth_module),
        settings: AppSettings = Depends(get_settings),
    ):
        try:
            result = auth.login(
                db,
                LoginCommand(email=str(payload.email), password=payload.password),
                ip_address=_request_ip(request),
                user_agent=request.headers.get("user-agent"),
                session_ttl=timedelta(minutes=settings.session_ttl_minutes),
                rate_limit_attempts=settings.login_rate_limit_attempts,
                rate_limit_window=timedelta(minutes=settings.login_rate_limit_window_minutes),
            )
            db.commit()
        except DomainError as exc:
            db.commit()
            return _domain_error_response(exc)

        _set_session_cookie(
            response,
            settings=settings,
            session_token=result.session_token,
            max_age_seconds=settings.session_ttl_minutes * 60,
        )
        return LoginResponse(
            user_id=result.user_id,
            csrf_token=result.csrf_token,
            expires_at=result.expires_at.isoformat(),
        )

    @api.post("/api/auth/logout", tags=["auth"])
    def logout(
        response: Response,
        db: OrmSession = Depends(get_db),
        authenticated: AuthenticatedSession = Depends(require_csrf),
        auth: AuthModule = Depends(get_auth_module),
        settings: AppSettings = Depends(get_settings),
    ):
        auth.logout(db, authenticated.session.id)
        db.commit()
        _clear_session_cookie(response, settings=settings)
        return {"ok": True}

    @api.get("/api/me", response_model=MeResponse, tags=["auth"])
    def me(authenticated: AuthenticatedSession = Depends(get_current_session)):
        return MeResponse(
            user_id=authenticated.user.id,
            email=authenticated.user.email,
            display_name=authenticated.user.display_name,
            role=Role(authenticated.user.role).value,
        )

    @api.post("/api/auth/password/setup", response_model=PasswordSetupResponse, tags=["auth"])
    def setup_password(
        payload: PasswordSetupRequest,
        request: Request,
        db: OrmSession = Depends(get_db),
        auth: AuthModule = Depends(get_auth_module),
    ):
        try:
            user = auth.setup_password(
                db,
                SetupPasswordCommand(token=payload.token, password=payload.password),
                ip_address=_request_ip(request),
                user_agent=request.headers.get("user-agent"),
            )
            db.commit()
        except DomainError as exc:
            db.commit()
            return _domain_error_response(exc)
        return PasswordSetupResponse(user_id=user.id, status=user.status)

    @api.post("/api/auth/password/reset", response_model=PasswordSetupResponse, tags=["auth"])
    def reset_password(
        payload: PasswordSetupRequest,
        request: Request,
        db: OrmSession = Depends(get_db),
        auth: AuthModule = Depends(get_auth_module),
    ):
        try:
            user = auth.setup_password(
                db,
                SetupPasswordCommand(token=payload.token, password=payload.password),
                ip_address=_request_ip(request),
                user_agent=request.headers.get("user-agent"),
            )
            db.commit()
        except DomainError as exc:
            db.commit()
            return _domain_error_response(exc)
        return PasswordSetupResponse(user_id=user.id, status=user.status)

    @api.get("/api/me/devices", response_model=list[DeviceResponse], tags=["portal"])
    def list_my_devices(
        db: OrmSession = Depends(get_db),
        authenticated: AuthenticatedSession = Depends(get_current_session),
        device_module: DeviceModule = Depends(get_device_module),
    ):
        devices = device_module.list_user_devices(db, user_id=authenticated.user.id)
        return [_device_response(db, device) for device in devices]

    @api.post("/api/me/devices", response_model=CreateDeviceResponse, tags=["portal"])
    def create_my_device(
        payload: CreateDeviceRequest,
        request: Request,
        db: OrmSession = Depends(get_db),
        authenticated: AuthenticatedSession = Depends(require_csrf),
        device_module: DeviceModule = Depends(get_device_module),
        settings: AppSettings = Depends(get_settings),
    ):
        try:
            device, package = device_module.create_device(
                db,
                CreateDeviceCommand(name=payload.name),
                user=authenticated.user,
                settings=settings,
                ip_address=_request_ip(request),
                user_agent=request.headers.get("user-agent"),
            )
            db.commit()
        except DomainError as exc:
            db.commit()
            return _domain_error_response(exc)
        return CreateDeviceResponse(device=_device_response(db, device), package=_package_response(package))

    @api.get("/api/me/packages/{package_id}", response_model=PackageResponse, tags=["portal"])
    def get_my_package(
        package_id: str,
        db: OrmSession = Depends(get_db),
        authenticated: AuthenticatedSession = Depends(get_current_session),
        device_module: DeviceModule = Depends(get_device_module),
    ):
        package = device_module.get_user_package(db, package_id=package_id, user_id=authenticated.user.id)
        return _package_response(package)

    @api.get("/api/me/packages/{package_id}/download", tags=["portal"])
    def download_my_package(
        package_id: str,
        db: OrmSession = Depends(get_db),
        authenticated: AuthenticatedSession = Depends(get_current_session),
        device_module: DeviceModule = Depends(get_device_module),
    ):
        try:
            grant = device_module.record_download_attempt(
                db,
                package_id=package_id,
                user_id=authenticated.user.id,
            )
            db.commit()
        except DomainError as exc:
            db.commit()
            return _domain_error_response(exc)
        return FileResponse(
            grant.artifact_path,
            media_type="application/octet-stream",
            filename=grant.package.file_name or "wireportal-installer.exe",
        )

    @api.post(
        "/api/me/packages/{package_id}/confirm-download",
        response_model=ConfirmDownloadResponse,
        tags=["portal"],
    )
    def confirm_my_package_download(
        package_id: str,
        request: Request,
        db: OrmSession = Depends(get_db),
        authenticated: AuthenticatedSession = Depends(require_csrf),
        device_module: DeviceModule = Depends(get_device_module),
    ):
        try:
            package = device_module.confirm_download(
                db,
                package_id=package_id,
                user_id=authenticated.user.id,
                ip_address=_request_ip(request),
                user_agent=request.headers.get("user-agent"),
            )
            db.commit()
        except DomainError as exc:
            db.commit()
            return _domain_error_response(exc)
        return ConfirmDownloadResponse(
            package_id=package.id,
            status=package.status,
            artifact_deleted_at=package.artifact_deleted_at.isoformat() if package.artifact_deleted_at else None,
            apply_peer_job_enqueued=True,
        )

    @api.post("/api/me/devices/{device_id}/report-lost", response_model=ReportLostResponse, tags=["portal"])
    def report_my_device_lost(
        device_id: str,
        db: OrmSession = Depends(get_db),
        authenticated: AuthenticatedSession = Depends(require_csrf),
        device_module: DeviceModule = Depends(get_device_module),
    ):
        try:
            device = device_module.report_lost(db, device_id=device_id, user_id=authenticated.user.id)
            db.commit()
        except DomainError as exc:
            db.commit()
            return _domain_error_response(exc)
        return ReportLostResponse(
            device_id=device.id,
            lost_reported_at=device.lost_reported_at.isoformat() if device.lost_reported_at else None,
        )

    @api.post("/api/applications", response_model=SubmitApplicationResponse, tags=["applications"])
    def submit_application(
        payload: SubmitApplicationRequest,
        request: Request,
        db: OrmSession = Depends(get_db),
        application_module: ApplicationModule = Depends(get_application_module),
    ):
        try:
            application = application_module.submit(
                db,
                SubmitApplicationCommand(
                    email=payload.email,
                    display_name=payload.display_name,
                    phone=payload.phone,
                    reason=payload.reason,
                    requested_device_count=payload.requested_device_count,
                ),
                ip_address=_request_ip(request),
                user_agent=request.headers.get("user-agent"),
            )
            db.commit()
        except DomainError as exc:
            db.commit()
            return _domain_error_response(exc)
        return SubmitApplicationResponse(submitted=True, application_id=application.id)

    @api.get(
        "/api/admin/access-groups",
        response_model=list[AccessGroupResponse],
        tags=["admin"],
    )
    def list_access_groups(
        _actor: Actor = Depends(require_admin_actor),
        db: OrmSession = Depends(get_db),
    ):
        rows = db.scalars(select(AccessGroup).order_by(AccessGroup.name)).all()
        return [_access_group_response(row) for row in rows]

    @api.get(
        "/api/admin/access-groups/{group_id}",
        response_model=AccessGroupDetailResponse,
        tags=["admin"],
    )
    def get_access_group(
        group_id: str,
        _actor: Actor = Depends(require_admin_actor),
        db: OrmSession = Depends(get_db),
    ):
        group = db.get(AccessGroup, group_id)
        if group is None:
            raise NotFoundError("Access group not found")
        routes = db.scalars(
            select(AccessGroupRoute)
            .where(AccessGroupRoute.access_group_id == group.id)
            .order_by(AccessGroupRoute.cidr)
        ).all()
        return _access_group_response(group, list(routes))

    @api.post(
        "/api/admin/access-groups",
        response_model=AccessGroupDetailResponse,
        tags=["admin"],
    )
    def create_access_group(
        payload: CreateAccessGroupRequest,
        request: Request,
        actor: Actor = Depends(require_admin_actor_with_csrf),
        db: OrmSession = Depends(get_db),
    ):
        if actor.role != Role.ADMIN:
            raise AuthorizationError("Only admin can manage access groups")
        try:
            group = AccessGroup(
                name=payload.name.strip(),
                description=payload.description,
                is_high_privilege=payload.is_high_privilege,
                enabled=payload.enabled,
            )
            db.add(group)
            db.flush()
            routes: list[AccessGroupRoute] = []
            for route_payload in payload.routes:
                cidr = str(ip_network(route_payload.cidr, strict=False))
                route = AccessGroupRoute(
                    access_group_id=group.id,
                    cidr=cidr,
                    description=route_payload.description,
                    enabled=route_payload.enabled,
                )
                db.add(route)
                routes.append(route)
            api.state.audit_module.record(
                db,
                AuditEvent(
                    actor_user_id=actor.user_id,
                    actor_type="user",
                    action="access_group.created",
                    target_type="access_group",
                    target_id=group.id,
                    after_json={
                        "name": group.name,
                        "is_high_privilege": group.is_high_privilege,
                        "routes": [route.cidr for route in routes],
                    },
                    ip_address=_request_ip(request),
                    user_agent=request.headers.get("user-agent"),
                ),
            )
            db.commit()
        except ValueError as exc:
            db.rollback()
            raise ValidationError("Invalid access group route CIDR") from exc
        except DomainError as exc:
            db.commit()
            return _domain_error_response(exc)
        return _access_group_response(group, routes)

    @api.get("/api/admin/users", response_model=list[AdminUserResponse], tags=["admin"])
    def list_users(
        _actor: Actor = Depends(require_admin_actor),
        db: OrmSession = Depends(get_db),
    ):
        users = db.scalars(select(User).order_by(User.created_at.desc())).all()
        return [_admin_user_response(db, user) for user in users]

    @api.get("/api/admin/audit-logs", response_model=list[AuditLogResponse], tags=["admin"])
    def list_audit_logs(
        limit: int = 100,
        _actor: Actor = Depends(require_admin_actor),
        db: OrmSession = Depends(get_db),
    ):
        safe_limit = max(1, min(limit, 200))
        rows = db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(safe_limit)).all()
        return [_audit_log_response(row) for row in rows]

    @api.get(
        "/api/admin/applications",
        response_model=list[ApplicationSummaryResponse],
        tags=["admin"],
    )
    def list_applications(
        status_filter: str | None = None,
        _actor: Actor = Depends(require_admin_actor),
        db: OrmSession = Depends(get_db),
    ):
        statement = select(Application)
        if status_filter:
            try:
                ApplicationStatus(status_filter)
            except ValueError as exc:
                raise ValidationError("Invalid application status") from exc
            statement = statement.where(Application.status == status_filter)
        statement = statement.order_by(Application.created_at.desc())
        return [_application_summary(row) for row in db.scalars(statement).all()]

    @api.get(
        "/api/admin/applications/{application_id}",
        response_model=ApplicationDetailResponse,
        tags=["admin"],
    )
    def get_application_detail(
        application_id: str,
        _actor: Actor = Depends(require_admin_actor),
        db: OrmSession = Depends(get_db),
    ):
        application = db.get(Application, application_id)
        if application is None:
            raise NotFoundError("Application not found")
        approval_records = db.scalars(
            select(ApprovalRecord)
            .where(ApprovalRecord.application_id == application_id)
            .order_by(ApprovalRecord.created_at)
        ).all()
        return _application_detail(application, list(approval_records))

    @api.post(
        "/api/admin/applications/{application_id}/approve",
        response_model=ApproveApplicationResponse,
        tags=["admin"],
    )
    def approve_application(
        application_id: str,
        payload: ApproveApplicationRequest,
        request: Request,
        db: OrmSession = Depends(get_db),
        actor: Actor = Depends(require_admin_actor_with_csrf),
        application_module: ApplicationModule = Depends(get_application_module),
        settings: AppSettings = Depends(get_settings),
    ):
        try:
            result = application_module.approve(
                db,
                application_id,
                ApproveApplicationCommand(
                    approved_device_limit=payload.approved_device_limit,
                    access_group_ids=payload.access_group_ids,
                    expires_at=_parse_optional_datetime(payload.expires_at),
                    reason=payload.reason,
                ),
                actor=actor,
                settings=settings,
                ip_address=_request_ip(request),
                user_agent=request.headers.get("user-agent"),
            )
            db.commit()
        except DomainError as exc:
            db.commit()
            return _domain_error_response(exc)
        return ApproveApplicationResponse(
            application_id=result.application.id,
            user_id=result.user.id,
            status=result.application.status,
            setup_url=result.setup_url,
            notification_status=result.notification_status,
        )

    @api.post(
        "/api/admin/applications/{application_id}/reject",
        response_model=RejectApplicationResponse,
        tags=["admin"],
    )
    def reject_application(
        application_id: str,
        payload: RejectApplicationRequest,
        request: Request,
        db: OrmSession = Depends(get_db),
        actor: Actor = Depends(require_admin_actor_with_csrf),
        application_module: ApplicationModule = Depends(get_application_module),
    ):
        try:
            application = application_module.reject(
                db,
                application_id,
                RejectApplicationCommand(reason=payload.reason),
                actor=actor,
                ip_address=_request_ip(request),
                user_agent=request.headers.get("user-agent"),
            )
            db.commit()
        except DomainError as exc:
            db.commit()
            return _domain_error_response(exc)
        return RejectApplicationResponse(application_id=application.id, status=application.status)

    @api.get("/api/admin/runtime/health", tags=["admin"])
    def runtime_health(
        db: OrmSession = Depends(get_db),
        settings: AppSettings = Depends(get_settings),
        _actor: Actor = Depends(require_admin_actor),
    ):
        pending_jobs = int(
            db.scalar(select(func.count(Job.id)).where(Job.status == JobStatus.PENDING.value)) or 0
        )
        active_devices = int(
            db.scalar(select(func.count(Device.id)).where(Device.status == DeviceStatus.ACTIVE.value)) or 0
        )
        target_devices = int(
            db.scalar(
                select(func.count(Device.id)).where(
                    Device.status.in_(
                        [
                            DeviceStatus.DOWNLOAD_CONFIRMED.value,
                            DeviceStatus.ACTIVE.value,
                        ]
                    )
                )
            )
            or 0
        )
        try:
            wg_agent = UnixSocketWgAgentClient(settings.wg_agent_socket_path).health()
        except Exception as exc:
            wg_agent = {"status": "unavailable", "error": str(exc)}
        return {
            "status": "ok" if wg_agent.get("status") == "ok" else "degraded",
            "database": {"status": "ok"},
            "jobs": {"pending": pending_jobs},
            "runtime": {
                "active_devices": active_devices,
                "target_devices": target_devices,
                "wg_interface": settings.wg_interface,
                "nft_table_name": settings.nft_table_name,
            },
            "wg_agent": wg_agent,
        }

    @api.get("/api/admin/devices", response_model=list[AdminDeviceResponse], tags=["admin"])
    def list_admin_devices(
        _actor: Actor = Depends(require_admin_actor),
        db: OrmSession = Depends(get_db),
    ):
        devices = db.scalars(select(Device).order_by(Device.created_at.desc())).all()
        return [_admin_device_response(db, device) for device in devices]

    @api.post("/api/admin/devices/{device_id}/reset", response_model=CreateDeviceResponse, tags=["admin"])
    def reset_admin_device(
        device_id: str,
        db: OrmSession = Depends(get_db),
        actor: Actor = Depends(require_admin_actor_with_csrf),
        device_module: DeviceModule = Depends(get_device_module),
        settings: AppSettings = Depends(get_settings),
    ):
        try:
            device, package = device_module.reset_device(
                db,
                device_id=device_id,
                actor=actor,
                settings=settings,
            )
            db.commit()
        except DomainError as exc:
            db.commit()
            return _domain_error_response(exc)
        return CreateDeviceResponse(device=_device_response(db, device), package=_package_response(package))

    @api.post("/api/admin/devices/{device_id}/revoke", response_model=AdminDeviceResponse, tags=["admin"])
    def revoke_admin_device(
        device_id: str,
        db: OrmSession = Depends(get_db),
        actor: Actor = Depends(require_admin_actor_with_csrf),
        device_module: DeviceModule = Depends(get_device_module),
    ):
        try:
            device = device_module.revoke_device(db, device_id=device_id, actor=actor)
            db.commit()
        except DomainError as exc:
            db.commit()
            return _domain_error_response(exc)
        return _admin_device_response(db, device)

    return api


app = create_app()
