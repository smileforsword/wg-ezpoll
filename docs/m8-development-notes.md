# M8 Development Notes

状态：已完成。

## Scope

M8 delivers the first complete V1 browser experience on top of the M4-M7 API surface:

- Public application submission.
- Password setup.
- Login/logout.
- User device portal with create, download, confirm, and lost-device reporting.
- Admin approval list/detail with SMTP fallback setup URL copy.
- Admin user, device, access-group, runtime health, and audit-log views.

## Backend Additions

- `GET /api/admin/access-groups/{id}` returns one access group with routes.
- `POST /api/admin/access-groups` creates an access group and optional routes. It is admin-only and CSRF-protected.
- `GET /api/admin/users` returns users with derived `device_count`.
- `GET /api/admin/audit-logs` returns newest audit logs with a clamped `limit`.
- `GET /api/admin/devices` now includes owner email and display name.
- Access-group creation records `audit_logs.action=access_group.created`.

## Frontend Additions

- Replaced the M7 minimal shell with a Vue TypeScript workbench in `apps/frontend/src/App.vue`.
- Added responsive layout and operational styling in `apps/frontend/src/styles.css`.
- The admin workbench has sections for approvals, users, devices, access groups, runtime health, and audit logs.
- Device reset/revoke and download confirmation use explicit browser confirmations.
- The UI keeps all admin actions routed through the existing cookie session and CSRF token.

## Validation

Validated on 2026-06-28:

```bash
python -m pytest
npm.cmd run lint
npm.cmd run build
```

Results:

- Backend tests: `45 passed`.
- Frontend lint: passed with `--max-warnings=0`.
- Frontend production build: passed.

## Notes For M9/M10

- M8 adds no schema migration and no new deployment environment variables.
- M9 should package the frontend/API/worker/wg-agent as one deployable release so the console and API contract stay aligned.
- M10 should add release checklist coverage for the admin console paths and SMTP fallback copy flow.
