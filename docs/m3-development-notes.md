# M3 Development Notes

状态：完成。M3 目标是跑通首次 setup 和登录，并建立认证、安全拒绝审计、CSRF、管理端 IP 白名单基础。

## Checklist

| Task | Status | Evidence |
|---|---|---|
| M3-01 实现 `/api/setup/status` | Done | `apps/api/src/yourvpn_api/main.py` |
| M3-02 实现 `/api/setup` | Done | `SetupModule.complete_setup()` |
| M3-03 初始化第一个 admin | Done | `Role.ADMIN`, `system_settings.setup_completed` |
| M3-04 Argon2id 密码哈希 | Done | `argon2-cffi`, `PasswordService` |
| M3-05 密码复杂度校验 | Done | 最少 8 位，含字母和数字 |
| M3-06 session cookie | Done | `wireportal_session` HttpOnly cookie |
| M3-07 CSRF 防护 | Done | 登录返回 CSRF token，登出校验 header |
| M3-08 登录/登出 | Done | `/api/auth/login`, `/api/auth/logout`, `/api/me` |
| M3-09 密码设置 token | Done | `/api/auth/password/setup`, `/api/auth/password/reset` |
| M3-10 登录限流 | Done | `login_attempts` by email/IP |
| M3-11 API 层 IP 白名单 middleware | Done | `/api/admin/*` middleware |
| M3-12 安全拒绝审计 | Done | login/setup/admin IP/password token rejections |

## Local Commands

Run all Python tests:

```powershell
$env:TMP=(Resolve-Path '.tmp\pytest').Path
$env:TEMP=$env:TMP
$env:PYTHONDONTWRITEBYTECODE='1'
python -m pytest
```

Run API locally:

```powershell
$env:PYTHONPATH="packages/python/yourvpn-core/src;apps/api/src"
$env:YOURVPN_DATABASE_URL="sqlite:///./wireportal.dev.sqlite3"
python -m alembic upgrade head
python -m uvicorn yourvpn_api.main:app --host 127.0.0.1 --port 8008
```

## 2026-06-26 Validation Run

- `python -m pytest` passed: 23 tests.
- M3 API tests cover setup status, first admin setup, repeated setup rejection, login, `/api/me`, CSRF logout, password setup token, password reset token, login rate limit, and admin IP whitelist audit.

## Documentation Updated

- `docs/api-contract.md`: M3 setup/auth/admin IP whitelist API contract.
- `docs/security-model.md`: M3 Argon2id, token hashing, Cookie/CSRF, setup and admin IP boundaries.
- `docs/deployment.md`: M3 auth environment variables and first setup command.
- `docs/database-schema.md`: M3 semantic notes for existing M2 tables.
