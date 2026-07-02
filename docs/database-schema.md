# Database Schema

状态：M8 已实现。SQLAlchemy 模型位于 `packages/python/yourvpn-core/src/yourvpn_core/db/models.py`，初始 Alembic 版本为 `20260626_0001_initial_schema`。

## Database Targets

- 开发与自动化测试：SQLite。
- 生产目标：MySQL 兼容 DDL。
- 主键：业务表默认使用 36 字符 UUID 字符串。
- 时间字段：使用 UTC 时间，SQLAlchemy 类型为 `DateTime(timezone=True)`。
- JSON 字段：使用 SQLAlchemy `JSON`，目前用于任务 payload、审计 before/after、系统设置值。

## Enums

`role`:

- `user`
- `approver`
- `admin`

`application_status`:

- `submitted`
- `approved`
- `account_setup_pending`
- `active`
- `rejected`
- `cancelled`
- `disabled`
- `expired`

`user_status`:

- `pending_password`
- `active`
- `disabled`
- `expired`

`device_status`:

- `draft`
- `pending_approval`
- `pending_build`
- `built`
- `ready_to_download`
- `downloading`
- `download_confirmed`
- `active`
- `disabled`
- `revoked`
- `expired`
- `reset_pending`

`install_package_status`:

- `pending_build`
- `building`
- `ready_to_download`
- `downloading`
- `download_confirmed`
- `artifact_deleted`
- `expired`
- `revoked`
- `failed`

`job_status`:

- `pending`
- `running`
- `succeeded`
- `failed`
- `cancelled`

## Tables

### `users`

字段：

- `id`
- `created_at`
- `updated_at`
- `email`
- `display_name`
- `phone`
- `role`
- `status`
- `password_hash`
- `approved_device_limit`
- `expires_at`

索引/约束：

- Primary key: `id`
- Unique/index: `email`
- Index: `status`

### `user_identities`

字段：

- `id`
- `user_id`
- `provider`
- `provider_subject`
- `created_at`

索引/约束：

- Primary key: `id`
- Foreign key: `user_id -> users.id`
- Unique: `provider`, `provider_subject`
- Index: `user_id`

### `sessions`

字段：

- `id`
- `created_at`
- `updated_at`
- `user_id`
- `session_token_hash`
- `csrf_token_hash`
- `ip_address`
- `user_agent`
- `expires_at`
- `revoked_at`

索引/约束：

- Primary key: `id`
- Foreign key: `user_id -> users.id`
- Unique: `session_token_hash`
- Index: `user_id`
- Index: `expires_at`

### `password_tokens`

字段：

- `id`
- `user_id`
- `token_hash`
- `purpose`
- `expires_at`
- `used_at`
- `created_at`

索引/约束：

- Primary key: `id`
- Foreign key: `user_id -> users.id`
- Unique: `token_hash`
- Index: `user_id`
- Index: `expires_at`

### `login_attempts`

字段：

- `id`
- `email`
- `ip_address`
- `success`
- `failure_reason`
- `created_at`

索引/约束：

- Primary key: `id`
- Index: `ix_login_attempts_email_created_at` on `email`, `created_at`
- Index: `ix_login_attempts_ip_created_at` on `ip_address`, `created_at`

### `access_groups`

字段：

- `id`
- `created_at`
- `updated_at`
- `name`
- `description`
- `is_high_privilege`
- `enabled`

索引/约束：

- Primary key: `id`
- Unique: `name`

### `access_group_routes`

字段：

- `id`
- `created_at`
- `updated_at`
- `access_group_id`
- `cidr`
- `description`
- `enabled`

索引/约束：

- Primary key: `id`
- Foreign key: `access_group_id -> access_groups.id`
- Unique: `access_group_id`, `cidr`
- Index: `access_group_id`

### `applications`

字段：

- `id`
- `created_at`
- `updated_at`
- `email`
- `display_name`
- `phone`
- `reason`
- `requested_device_count`
- `status`
- `submitted_ip`
- `submitted_user_agent`

索引/约束：

- Primary key: `id`
- Index: `email`
- Index: `status`

### `approval_records`

字段：

- `id`
- `application_id`
- `actor_user_id`
- `action`
- `approved_device_limit`
- `reason`
- `created_user_id`
- `created_at`

索引/约束：

- Primary key: `id`
- Foreign key: `application_id -> applications.id`
- Foreign key: `actor_user_id -> users.id`
- Foreign key: `created_user_id -> users.id`
- Index: `application_id`
- Index: `ix_approval_records_application_created_at` on `application_id`, `created_at`

### `user_access_groups`

字段：

- `user_id`
- `access_group_id`
- `granted_by_user_id`
- `created_at`

索引/约束：

- Composite primary key: `user_id`, `access_group_id`
- Foreign key: `user_id -> users.id`
- Foreign key: `access_group_id -> access_groups.id`
- Foreign key: `granted_by_user_id -> users.id`
- Unique: `user_id`, `access_group_id`

### `devices`

字段：

- `id`
- `created_at`
- `updated_at`
- `user_id`
- `name`
- `status`
- `public_key`
- `vpn_ip`
- `lost_reported_at`
- `revoked_at`
- `expires_at`
- `latest_handshake_at`
- `latest_endpoint`
- `rx_bytes`
- `tx_bytes`

索引/约束：

- Primary key: `id`
- Foreign key: `user_id -> users.id`
- Unique: `public_key`
- Unique: `vpn_ip`
- Index: `user_id`
- Index: `status`
- Index: `expires_at`

### `device_access_groups`

字段：

- `device_id`
- `access_group_id`
- `granted_by_user_id`
- `created_at`

索引/约束：

- Composite primary key: `device_id`, `access_group_id`
- Foreign key: `device_id -> devices.id`
- Foreign key: `access_group_id -> access_groups.id`
- Foreign key: `granted_by_user_id -> users.id`
- Unique: `device_id`, `access_group_id`

### `install_packages`

字段：

- `id`
- `created_at`
- `updated_at`
- `device_id`
- `status`
- `file_name`
- `artifact_path`
- `sha256`
- `file_size`
- `signed_status`
- `config_format`
- `wireguard_installer_version`
- `download_attempts`
- `max_download_attempts`
- `download_expires_at`
- `confirmed_at`
- `artifact_deleted_at`
- `last_error`

索引/约束：

- Primary key: `id`
- Foreign key: `device_id -> devices.id`
- Index: `device_id`
- Index: `status`
- Index: `ix_install_packages_device_status` on `device_id`, `status`
- Index: `ix_install_packages_download_expires_at` on `download_expires_at`

说明：

- `config_format` 当前默认固定为 `ini`，对应自解压安装器释放 WireGuard INI 的模式。

### `jobs`

字段：

- `id`
- `created_at`
- `updated_at`
- `job_type`
- `status`
- `payload_json`
- `run_after`
- `locked_at`
- `locked_by`
- `attempts`
- `max_attempts`
- `last_error`

索引/约束：

- Primary key: `id`
- Index: `job_type`
- Index: `status`
- Index: `run_after`
- Index: `ix_jobs_status_run_after` on `status`, `run_after`
- Index: `ix_jobs_locked_at` on `locked_at`

### `worker_heartbeats`

字段：

- `worker_id`
- `hostname`
- `process_id`
- `started_at`
- `last_seen_at`
- `version`

索引/约束：

- Primary key: `worker_id`

### `audit_logs`

字段：

- `id`
- `actor_user_id`
- `actor_type`
- `action`
- `target_type`
- `target_id`
- `before_json`
- `after_json`
- `ip_address`
- `user_agent`
- `created_at`

索引/约束：

- Primary key: `id`
- Foreign key: `actor_user_id -> users.id`
- Index: `ix_audit_logs_created_at` on `created_at`
- Index: `ix_audit_logs_actor_action` on `actor_user_id`, `action`
- Index: `ix_audit_logs_target` on `target_type`, `target_id`

### `traffic_snapshots`

字段：

- `id`
- `device_id`
- `sampled_at`
- `rx_bytes`
- `tx_bytes`
- `latest_handshake_at`
- `endpoint`

索引/约束：

- Primary key: `id`
- Foreign key: `device_id -> devices.id`
- Index: `ix_traffic_snapshots_device_sampled_at` on `device_id`, `sampled_at`

### `server_secrets`

字段：

- `id`
- `key`
- `secret_type`
- `ciphertext`
- `nonce`
- `algorithm`
- `key_version`
- `created_at`

索引/约束：

- Primary key: `id`
- Unique: `key`

说明：

- 只存服务端密文材料，不存客户端 WireGuard private key。
- M3+ 接入真实加密服务后，`algorithm` 和 `key_version` 必须与密钥轮换策略一致。

### `system_settings`

字段：

- `key`
- `value_json`
- `is_secret`
- `updated_at`

索引/约束：

- Primary key: `key`

## Migration Validation

M2 已验证：

- `python -m pytest` 可在 SQLite 临时库上执行 Alembic `upgrade head`。
- 测试会检查 M2 表集合、关键字段、关键索引。
- 测试会使用 SQLAlchemy MySQL 方言编译所有表和索引 DDL，提前发现明显 MySQL 兼容性问题。

## M3 Semantic Notes

- `system_settings.key=setup_completed` stores first-setup completion state as JSON: `{"value": true, "completed_at": "..."}`.
- `password_tokens.purpose` currently uses `setup` and `reset`.
- `sessions.session_token_hash`, `sessions.csrf_token_hash`, and `password_tokens.token_hash` contain SHA-256 hashes of random bearer tokens, never plaintext token values.
- `login_attempts.failure_reason` currently uses `invalid_credentials`, `invalid_credentials_or_status`, and `rate_limited`.
- `audit_logs.action` currently includes `setup.completed`, `setup.rejected`, `auth.login_rejected`, `auth.password_setup`, `auth.password_setup_rejected`, and `security.admin_ip_rejected`.

## M4 Semantic Notes

- Public applications are inserted into `applications` with `status=submitted`.
- Approval moves an application to `account_setup_pending`, creates a `users` row with `status=pending_password`, and inserts zero or more `user_access_groups` rows.
- Approval inserts an `approval_records` row with `action=approve` and a one-time `password_tokens` row with `purpose=setup`.
- Rejection moves an application to `rejected` and inserts `approval_records.action=reject`.
- When SMTP is configured, approval attempts direct SMTP delivery. M4 does not persist email body or password setup URL in a job.
- M4 audit actions include `application.submitted`, `application.approved`, and `application.rejected`.

## M5 Semantic Notes

- `devices.vpn_ip` is allocated from `YOURVPN_VPN_CIDR`, skipping `YOURVPN_VPN_SERVER_IP`.
- M5 fake builder writes `devices.public_key` as a fake value when fake mode is selected; M6 self-pack mode writes a generated WireGuard public key.
- Device creation inherits `user_access_groups` into `device_access_groups`.
- Device creation inserts an `install_packages` row and stores a fake installer artifact path in `artifact_path`.
- M5 package artifacts are not backup material. They are deleted after confirmed download, reset, revoke, or expiry.
- `install_packages.status` moves through `ready_to_download`, `downloading`, and `artifact_deleted` in the fake lifecycle.
- Confirming download inserts a pending `jobs` row with `job_type=apply_peer`.
- Revoking a device inserts a pending `jobs` row with `job_type=remove_peer`.
- M5 audit actions include `device.created` and `install_package.confirmed`.

## M6 Semantic Notes

- M6 does not require a schema migration; it reuses `devices.public_key`, `install_packages.*`, and `jobs.*`.
- `SelfPackInstallerBuilder` generates the client WireGuard keypair during package build.
- Only the client public key is stored in `devices.public_key`; the client private key is not stored in database fields.
- Self-pack artifacts use `install_packages.file_name=wireportal-{device_id}.exe`.
- `install_packages.config_format` remains `ini`.
- `install_packages.wireguard_installer_version` stores the embedded WireGuard MSI version, default `1.1`.
- `install_packages.signed_status` is currently `unsigned`; signing can be added behind the same metadata field later.
- Successful real builds create `jobs.job_type=build_installer` with `status=succeeded`.
- Failed real builds create `jobs.job_type=build_installer` with `status=failed`, set `jobs.last_error`, set `install_packages.status=failed`, and set `install_packages.last_error`.

## M7 Semantic Notes

- M7 does not require a schema migration; it reuses `devices`, `device_access_groups`, `access_group_routes`, `jobs`, and `traffic_snapshots`.
- Confirming package download still creates `jobs.job_type=apply_peer`.
- Worker consumes runtime jobs: `apply_peer`, `remove_peer`, `apply_firewall`, `reconcile_runtime_state`, and `sample_wg_status`.
- `apply_peer` calls wg-agent and moves the device from `download_confirmed` to `active` after wg-agent success.
- Runtime target state includes only devices with `status in ('download_confirmed', 'active')` and a non-null `public_key`.
- Server-side WireGuard peer `AllowedIPs` is always the device VPN IP `/32`.
- Access-group routes are rendered into the dedicated nftables table, not into the server peer `AllowedIPs`.
- `sample_wg_status` updates `devices.latest_handshake_at`, `latest_endpoint`, `rx_bytes`, and `tx_bytes`, then inserts `traffic_snapshots`.
- wg-agent has no database access; all database writes happen in API/Worker/core modules.

## M8 Semantic Notes

- M8 does not require a schema migration; it exposes existing V1 data through the browser console.
- Admin user listing reads `users` and derives `device_count` from `devices`.
- Admin device listing joins each device owner from `users` and includes the current package summary from `install_packages`.
- Admin access-group creation inserts `access_groups` and zero or more `access_group_routes` rows in one transaction.
- `access_group_routes.cidr` is normalized through CIDR parsing before insert, for example `10.20.0.1/16` becomes `10.20.0.0/16`.
- Access-group creation writes `audit_logs.action=access_group.created`.
- Audit log listing reads newest rows from `audit_logs` and clamps the requested limit to `1..200`.
- M8 does not add any field that may contain a client WireGuard private key.

## M9 Semantic Notes

- M9 does not require a schema migration; it deploys the existing schema.
- Default production SQLite path is `/var/lib/yourvpn/db/wireportal.sqlite3`.
- M9 backup scripts include the SQLite database and installer cache, but not `install_packages.artifact_path` targets.
- After restore, Alembic is run to current head and `WgRuntimeModule.reconcile()` reapplies database-authoritative runtime state.
