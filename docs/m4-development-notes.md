# M4 Development Notes

状态：完成。M4 目标是跑通公开申请、审批、密码设置、登录的第一个业务闭环。

## Checklist

| Task | Status | Evidence |
|---|---|---|
| M4-01 公开申请接口 | Done | `POST /api/applications` |
| M4-02 公开申请页 | Done | `apps/frontend/src/App.vue` |
| M4-03 审批列表接口 | Done | `GET /api/admin/applications` |
| M4-04 审批详情接口 | Done | `GET /api/admin/applications/{id}` |
| M4-05 审批通过接口 | Done | `POST /api/admin/applications/{id}/approve` |
| M4-06 审批拒绝接口 | Done | `POST /api/admin/applications/{id}/reject` |
| M4-07 多访问组授权 | Done | `user_access_groups` grants |
| M4-08 高权限访问组仅 admin 授权 | Done | `AuthorizationModule.can_grant_access_groups()` |
| M4-09 创建密码设置链接 | Done | `PasswordToken` + returned `setup_url` |
| M4-10 SMTP 通知 | Done | SMTP configured 时直接发送，失败不阻断审批 |
| M4-11 SMTP 不可用时后台复制链接 | Done | approval response returns `setup_url` |
| M4-12 审批审计 | Done | `application.approved`, `application.rejected` |

## Implemented Flow

1. Applicant submits `POST /api/applications`.
2. Admin or approver logs in.
3. Admin loads applications and access groups.
4. Admin or approver approves ordinary access groups.
5. Admin may approve high-privilege access groups.
6. Approval creates a `pending_password` user and password setup token.
7. Applicant sets password with `/api/auth/password/setup`.
8. Applicant logs in with `/api/auth/login`.

## Frontend

M4 replaces the M1 skeleton with an operational Vue screen:

- `申请`: public application form.
- `初始化`: first admin setup form.
- `密码`: password setup form.
- `登录`: admin login form.
- `审批`: application list/detail, approve/reject forms, access-group selection, setup-link copy.

The current Vite dev proxy sends `/api` traffic to `http://127.0.0.1:8008`, and the frontend dev server listens on `http://127.0.0.1:5566`.

## 2026-06-28 Validation Run

- `python -m pytest` passed: 29 tests.
- `npm.cmd run lint` passed.
- `npm.cmd run build` passed.

## Documentation Updated

- `docs/api-contract.md`: M4 public application and admin approval contracts.
- `docs/security-model.md`: M4 approval authorization and audit boundaries.
- `docs/deployment.md`: M4 SMTP settings and fallback behavior.
- `docs/database-schema.md`: M4 semantic notes for existing tables.
