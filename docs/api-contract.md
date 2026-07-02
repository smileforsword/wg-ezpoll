# API Contract

状态：M8 已补齐 V1 浏览器控制台所需 API。wg-agent Unix socket 契约详见 `docs/wg-agent-contract.md`。

## Contract Rules

- Public HTTP API prefix: `/api`.
- Admin HTTP API prefix: `/api/admin`.
- JSON request and response bodies use `snake_case`.
- Error responses use a stable `code`, human-readable `message`, and optional `details`.
- Authenticated browser flows use HTTP-only cookie session plus CSRF token.

## M0 Notes

- No production public API is implemented in M0.
- API/Worker to wg-agent communication is local-only over Unix socket and is documented separately.

## M1 Health Endpoints

### `GET /health`

API service liveness endpoint.

Response:

```json
{
  "service": "api",
  "status": "ok",
  "version": "0.1.0",
  "environment": "development",
  "checked_at": "2026-06-26T00:00:00Z",
  "details": {
    "database_url_configured": true,
    "wg_agent_socket_path": "/run/yourvpn/wg-agent.sock"
  }
}
```

### `GET /api/health`

Alias for `GET /health`, provided so reverse proxy routing can verify the `/api` prefix.

## M2 Shared Domain Values

M2 does not add new HTTP endpoints. From M3 onward, business API responses must use the enum values documented in `docs/database-schema.md` for:

- `role`
- `application_status`
- `user_status`
- `device_status`
- `install_package_status`
- `job_status`

## Error Response

业务错误统一返回：

```json
{
  "code": "authentication_failed",
  "message": "Invalid email or password",
  "details": null
}
```

常见 M3 错误码：

- `setup_already_completed`
- `password_policy_failed`
- `authentication_failed`
- `login_rate_limited`
- `csrf_failed`
- `authorization_denied`

## M3 Setup API

### `GET /api/setup/status`

Response:

```json
{
  "setup_completed": false,
  "admin_exists": false,
  "setup_available": true
}
```

### `POST /api/setup`

仅当 `setup_available=true` 时允许调用。成功后创建第一个 `admin` 用户，并写入 `system_settings.setup_completed`。

Request:

```json
{
  "email": "admin@example.com",
  "display_name": "Admin",
  "password": "GoodPass123"
}
```

Response:

```json
{
  "setup_completed": true,
  "user_id": "uuid"
}
```

## M3 Auth API

### `POST /api/auth/login`

Request:

```json
{
  "email": "admin@example.com",
  "password": "GoodPass123"
}
```

Response:

```json
{
  "user_id": "uuid",
  "csrf_token": "token",
  "expires_at": "2026-06-26T17:00:00+00:00"
}
```

Cookie:

- Name: configured by `YOURVPN_SESSION_COOKIE_NAME`, default `wireportal_session`.
- Attributes: `HttpOnly`, `SameSite=Strict`, `Path=/`.
- `Secure` is controlled by `YOURVPN_SESSION_COOKIE_SECURE`; production must set it to `true`.

### `POST /api/auth/logout`

Requires a valid session cookie and CSRF header. Header name defaults to `x-csrf-token`.

Response:

```json
{
  "ok": true
}
```

### `GET /api/me`

Requires a valid session cookie.

Response:

```json
{
  "user_id": "uuid",
  "email": "admin@example.com",
  "display_name": "Admin",
  "role": "admin"
}
```

### `POST /api/auth/password/setup`

Consumes a one-time password setup token.

Request:

```json
{
  "token": "token",
  "password": "NewPass123"
}
```

Response:

```json
{
  "user_id": "uuid",
  "status": "active"
}
```

### `POST /api/auth/password/reset`

Consumes a one-time password reset token. Request and response match `/api/auth/password/setup`.

## M3 Admin IP Whitelist

All `/api/admin/*` requests pass through API-layer IP whitelist middleware before route handling.

- Empty whitelist means no IP restriction.
- Non-empty whitelist is a comma-separated CIDR list from `YOURVPN_ADMIN_IP_WHITELIST`.
- Rejected requests return `authorization_denied` and write `security.admin_ip_rejected` to `audit_logs`.

## M4 Public Application API

### `POST /api/applications`

公开申请无需登录。普通申请最多请求 3 台设备。

Request:

```json
{
  "email": "applicant@example.com",
  "display_name": "Applicant",
  "phone": "10086",
  "reason": "Need VPN access",
  "requested_device_count": 2
}
```

Response:

```json
{
  "submitted": true,
  "application_id": "uuid"
}
```

## M4 Admin Approval API

All endpoints below require a valid session cookie. Mutating endpoints also require the CSRF header.

### `GET /api/admin/access-groups`

M4 helper endpoint for approval UI. M8 admin console also uses it as the access-group list.

Response:

```json
[
  {
    "id": "uuid",
    "name": "engineering",
    "description": "Engineering routes",
    "is_high_privilege": false,
    "enabled": true
  }
]
```

### `GET /api/admin/access-groups/{id}`

Returns one access group plus routes. Requires `admin` or `approver`.

Response:

```json
{
  "id": "uuid",
  "name": "engineering",
  "description": "Engineering routes",
  "is_high_privilege": false,
  "enabled": true,
  "routes": [
    {
      "id": "uuid",
      "cidr": "10.20.0.0/16",
      "description": "office lan",
      "enabled": true
    }
  ]
}
```

### `POST /api/admin/access-groups`

Admin only. Requires CSRF. Creates an access group and optional routes.

Route CIDRs are parsed with non-strict CIDR handling and persisted in canonical network form. For example, `10.20.0.1/16` becomes `10.20.0.0/16`.

Request:

```json
{
  "name": "ops",
  "description": "Operations routes",
  "is_high_privilege": true,
  "enabled": true,
  "routes": [
    {
      "cidr": "10.20.0.1/16",
      "description": "ops lan",
      "enabled": true
    }
  ]
}
```

Response matches `GET /api/admin/access-groups/{id}`.

### `GET /api/admin/applications`

Optional query:

- `status_filter=submitted`

Response:

```json
[
  {
    "id": "uuid",
    "email": "applicant@example.com",
    "display_name": "Applicant",
    "requested_device_count": 2,
    "status": "submitted",
    "created_at": "2026-06-28T00:00:00+00:00"
  }
]
```

### `GET /api/admin/applications/{id}`

Returns application detail plus approval records.

### `POST /api/admin/applications/{id}/approve`

Rules:

- `approver` and `admin` may approve ordinary access groups.
- Only `admin` may approve access groups where `is_high_privilege=true`.
- `approved_device_limit` is capped at 10 in M4.

Request:

```json
{
  "approved_device_limit": 2,
  "access_group_ids": ["uuid-a", "uuid-b"],
  "expires_at": null,
  "reason": "Approved"
}
```

Response:

```json
{
  "application_id": "uuid",
  "user_id": "uuid",
  "status": "account_setup_pending",
  "setup_url": "https://portal.example/password/setup?token=...",
  "notification_status": "not_configured"
}
```

`setup_url` is returned so an admin can copy it when SMTP is unavailable. `notification_status` is one of:

- `not_configured`
- `sent`
- `failed`

### `POST /api/admin/applications/{id}/reject`

Request:

```json
{
  "reason": "Missing justification"
}
```

Response:

```json
{
  "application_id": "uuid",
  "status": "rejected"
}
```

## M5/M6 User Device And Package API

All endpoints in this section require a valid user session. Mutating endpoints require CSRF.

### `GET /api/me/devices`

Response:

```json
[
  {
    "id": "uuid",
    "name": "Laptop",
    "status": "ready_to_download",
    "public_key": "base64-wireguard-public-key",
    "vpn_ip": "10.77.0.2",
    "latest_handshake_at": null,
    "latest_endpoint": null,
    "rx_bytes": 0,
    "tx_bytes": 0,
    "current_package": {
      "id": "uuid",
      "device_id": "uuid",
      "status": "ready_to_download",
      "file_name": "wireportal-uuid.exe",
      "sha256": "...",
      "file_size": 3300000,
      "signed_status": "unsigned",
      "config_format": "ini",
      "download_attempts": 0,
      "max_download_attempts": 5,
      "download_expires_at": "2026-06-28T10:00:00+00:00",
      "confirmed_at": null,
      "artifact_deleted_at": null,
      "can_download": true
    }
  }
]
```

### `POST /api/me/devices`

Creates a device, inherits user access groups, allocates a VPN IP, runs the configured installer builder, and creates a ready installer artifact.

Builder selection:

- `YOURVPN_INSTALLER_BUILDER_MODE=self_pack`: force `SelfPackInstallerBuilder`.
- `YOURVPN_INSTALLER_BUILDER_MODE=fake`: force the M5 fake builder.
- `YOURVPN_INSTALLER_BUILDER_MODE=auto`: use self-pack when `YOURVPN_WIREGUARD_MSI_PATH` is configured, otherwise fall back to fake when `YOURVPN_FAKE_BUILDER_ENABLED=true`.

Request:

```json
{
  "name": "Laptop"
}
```

Response:

```json
{
  "device": {
    "id": "uuid",
    "name": "Laptop",
    "status": "ready_to_download",
    "public_key": "base64-wireguard-public-key",
    "vpn_ip": "10.77.0.2",
    "latest_handshake_at": null,
    "latest_endpoint": null,
    "rx_bytes": 0,
    "tx_bytes": 0,
    "current_package": {}
  },
  "package": {}
}
```

### `GET /api/me/packages/{id}`

Returns package metadata for the owner only.

### `GET /api/me/packages/{id}/download`

Returns the installer artifact as `application/octet-stream`, increments `download_attempts`, and moves the package to `downloading` if it was `ready_to_download`.

Failure cases:

- `download_not_available` when confirmed, expired, deleted, not ready, missing, or attempts exceeded.
- `installer_build_failed` when the configured installer builder cannot produce an artifact, for example missing MSI, SHA256 mismatch, or missing WireGuard endpoint/server public key.

### `POST /api/me/packages/{id}/confirm-download`

Deletes the artifact, marks the package as `artifact_deleted`, moves the device to `download_confirmed`, and enqueues an `apply_peer` job.

Response:

```json
{
  "package_id": "uuid",
  "status": "artifact_deleted",
  "artifact_deleted_at": "2026-06-28T10:00:00+00:00",
  "apply_peer_job_enqueued": true
}
```

### `POST /api/me/devices/{id}/report-lost`

Records `lost_reported_at` for the owner.

## M5-M8 Admin Device, Console And Runtime API

### `GET /api/admin/devices`

Returns all devices with owner identity and current package summary. Requires `admin` or `approver`.

Response item:

```json
{
  "id": "uuid",
  "user_id": "uuid",
  "user_email": "user@example.com",
  "user_display_name": "User",
  "name": "Laptop",
  "status": "active",
  "public_key": "base64-wireguard-public-key",
  "vpn_ip": "10.77.0.2",
  "revoked_at": null,
  "current_package": {}
}
```

### `POST /api/admin/devices/{id}/reset`

Admin only. Deletes active package artifacts for the device and creates a fresh installer package through the configured builder.

### `POST /api/admin/devices/{id}/revoke`

Admin only. Marks the device as `revoked`, deletes remaining package artifacts, and enqueues a `remove_peer` job.

### `GET /api/admin/users`

Returns users for the M8 admin console. Requires `admin` or `approver`.

Response item:

```json
{
  "id": "uuid",
  "email": "user@example.com",
  "display_name": "User",
  "phone": null,
  "role": "user",
  "status": "active",
  "approved_device_limit": 2,
  "expires_at": null,
  "created_at": "2026-06-28T00:00:00+00:00",
  "device_count": 1
}
```

### `GET /api/admin/audit-logs`

Returns newest audit logs for the M8 admin console. Requires `admin` or `approver`.

Optional query:

- `limit`: default `100`, clamped to `1..200`.

Response item:

```json
{
  "id": "uuid",
  "actor_user_id": "uuid",
  "actor_type": "user",
  "action": "application.approved",
  "target_type": "application",
  "target_id": "uuid",
  "before_json": null,
  "after_json": {
    "status": "account_setup_pending"
  },
  "ip_address": "127.0.0.1",
  "user_agent": "browser",
  "created_at": "2026-06-28T00:00:00+00:00"
}
```

### `GET /api/admin/runtime/health`

Admin or approver only. Returns database/runtime counters and attempts a local wg-agent health probe over the configured Unix socket.

Response:

```json
{
  "status": "degraded",
  "database": {
    "status": "ok"
  },
  "jobs": {
    "pending": 1
  },
  "runtime": {
    "active_devices": 0,
    "target_devices": 1,
    "wg_interface": "wg0",
    "nft_table_name": "yourvpn"
  },
  "wg_agent": {
    "status": "unavailable",
    "error": "..."
  }
}
```
