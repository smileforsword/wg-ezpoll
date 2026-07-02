# M2 Development Notes

状态：完成。M2 目标是建立数据库模型、迁移骨架和可单测的核心业务模块。

## Checklist

| Task | Status | Evidence |
|---|---|---|
| M2-01 建立 SQLAlchemy Base 和 Alembic | Done | `yourvpn_core.db.base`, `alembic.ini`, `migrations/` |
| M2-02 创建 users/sessions/password_tokens/login_attempts | Done | `yourvpn_core.db.models` |
| M2-03 创建 access_groups/access_group_routes | Done | `yourvpn_core.db.models` |
| M2-04 创建 applications/approval_records | Done | `yourvpn_core.db.models` |
| M2-05 创建设备与访问组关联表 | Done | `devices`, `user_access_groups`, `device_access_groups` |
| M2-06 创建 install_packages | Done | `install_packages.config_format=ini` |
| M2-07 创建 jobs/worker_heartbeats | Done | `jobs`, `worker_heartbeats` |
| M2-08 创建 audit_logs/traffic_snapshots | Done | `audit_logs`, `traffic_snapshots` |
| M2-09 创建 server_secrets/system_settings | Done | `server_secrets`, `system_settings` |
| M2-10 实现状态机 Module | Done | `yourvpn_core.modules.state_machine` |
| M2-11 实现权限 Module | Done | `yourvpn_core.modules.authorization` |
| M2-12 实现多访问组聚合 Module | Done | `yourvpn_core.modules.access_groups` |
| M2-13 实现 IP 分配 Module | Done | `yourvpn_core.modules.ip_allocator` |
| M2-14 实现审计 Module | Done | `yourvpn_core.modules.audit` |

## Module Boundaries

- State machine: validates legal transitions for application, user, device, install package, and job states.
- Authorization: checks roles, admin IP whitelist membership, and high-privilege access-group grant rules.
- Access groups: aggregates enabled CIDR routes and produces firewall target inputs.
- IP allocator: allocates from VPN CIDR while skipping server IP, allocated IPs, and revoked IPs still in cooldown.
- Audit: writes normalized audit events to `audit_logs`.

## Local Commands

Run all Python tests:

```powershell
$env:TMP=(Resolve-Path '.tmp\pytest').Path
$env:TEMP=$env:TMP
python -m pytest
```

Run Alembic against a local SQLite database:

```powershell
$env:YOURVPN_DATABASE_URL="sqlite:///./wireportal.dev.sqlite3"
python -m alembic upgrade head
```

## 2026-06-26 Validation Run

- `python -m pytest` passed: 17 tests.
- SQLite migration validation passed through Alembic `upgrade head` in a temporary test database.
- MySQL live migration was not run in this workspace because no MySQL service is configured.
- MySQL DDL compatibility is covered by compiling all M2 tables and indexes with SQLAlchemy's MySQL dialect.

## Documentation Updated

- `docs/database-schema.md`: M2 fields, indexes, constraints, and enums.
- `docs/security-model.md`: M2 secrets, token hashing, authorization, and audit boundaries.
- `docs/deployment.md`: M2 Alembic migration commands and recovery notes.
- `docs/api-contract.md`: M2 shared enum values for future API responses.
