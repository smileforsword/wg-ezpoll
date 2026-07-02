# M5 Development Notes

状态：完成。M5 目标是用 fake builder 跑通用户设备与安装包生命周期。

## Checklist

| Task | Status | Evidence |
|---|---|---|
| M5-01 用户设备列表 | Done | `GET /api/me/devices` |
| M5-02 用户创建设备 | Done | `POST /api/me/devices` |
| M5-03 设备额度检查 | Done | `quota_exceeded` |
| M5-04 设备继承用户访问组 | Done | `device_access_groups` |
| M5-05 VPN IP 分配 | Done | `IpAllocatorModule` |
| M5-06 创建 install_package | Done | `install_packages` row |
| M5-07 fake builder job | Done | `build_installer_fake` job + fake artifact |
| M5-08 下载详情接口 | Done | `GET /api/me/packages/{id}` |
| M5-09 下载接口和下载次数 | Done | `GET /api/me/packages/{id}/download` |
| M5-10 确认下载接口 | Done | `POST /api/me/packages/{id}/confirm-download` |
| M5-11 确认后删除 artifact | Done | `artifact_deleted_at` + file deletion |
| M5-12 管理员重置设备 | Done | `POST /api/admin/devices/{id}/reset` |
| M5-13 管理员吊销设备 | Done | `POST /api/admin/devices/{id}/revoke` |

## Implemented Flow

1. Approved user logs in.
2. User creates a device.
3. Device inherits user access groups.
4. VPN IP is allocated.
5. Fake builder creates a fake installer artifact and marks package `ready_to_download`.
6. User downloads the artifact; attempts are counted.
7. User confirms download.
8. Artifact is deleted.
9. `apply_peer` job is enqueued.

## Frontend

The Vue app now includes a `设备` view:

- user device list;
- device creation;
- fake package download;
- download confirmation;
- lost-device reporting.

## 2026-06-28 Validation Run

- `python -m pytest` passed: 34 tests.
- `npm.cmd run lint` passed.
- `npm.cmd run build` passed.

## Documentation Updated

- `docs/api-contract.md`: M5 device/package API contract.
- `docs/database-schema.md`: M5 lifecycle semantics.
- `docs/security-model.md`: M5 ownership, quota, download, and artifact boundaries.
- `docs/deployment.md`: M5 IP pool and package settings.
- `docs/installer-build.md`: fake builder behavior and M6 replacement boundary.
