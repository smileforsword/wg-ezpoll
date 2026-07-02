# M6 Development Notes

状态：完成。M6 目标是接入 `SelfPackInstallerBuilder`，把 M5 fake builder 边界替换为可配置的真实 self-pack 构建链路。

## Checklist

| Task | Status | Evidence |
|---|---|---|
| M6-01 定义 `InstallerBuilder` Interface | Done | `yourvpn_core.modules.installer_builder.InstallerBuilder` |
| M6-02 实现 `SelfPackInstallerBuilder` | Done | `SelfPackInstallerBuilder` |
| M6-03 渲染 WireGuard INI 配置 | Done | `render_wireguard_ini()` |
| M6-04 生成 self-pack manifest | Done | `wireportal-package.json` |
| M6-05 校验固定 WireGuard installer SHA256 | Done | `sha256_file()` + configured hash |
| M6-06 调用项目自打包程序 | Done | builder writes self-pack artifact with manifest/payload/runner |
| M6-07 计算 artifact SHA256 和 file size | Done | `BuildInstallerResult` metadata |
| M6-08 删除临时 INI | Done | `TemporaryDirectory` cleanup + test assertion |
| M6-09 构建失败记录 | Done | failed `build_installer` job + package `last_error` |
| M6-10 下载页显示 `signed_status` | Done | Vue package panel |
| M6-11 Windows 手动安装验收 | Pending manual | Windows 10/11 target hosts required |

## Builder Modes

- `auto`: if `YOURVPN_WIREGUARD_MSI_PATH` is configured, use self-pack; otherwise use fake when `YOURVPN_FAKE_BUILDER_ENABLED=true`.
- `self_pack`: require WireGuard MSI path, pinned SHA256, server public key, and endpoint.
- `fake`: keep the M5 fake builder for local development and regression tests.

## Security Boundary

- Client private key is generated during build.
- Client private key is rendered only into the temporary device INI and final artifact.
- Database stores only `devices.public_key`.
- Manifest stores only public key, allowed IPs, asset hashes, and install plan.
- Build temp INI cleanup is verified by automated tests.

## 2026-06-28 Validation Run

- `python -m pytest` passed: 36 tests.
- `npm.cmd run lint` passed.
- `npm.cmd run build` passed.

## Documentation Updated

- `docs/api-contract.md`: M6 builder mode and `installer_build_failed`.
- `docs/database-schema.md`: M6 package/job semantics.
- `docs/installer-build.md`: self-pack builder inputs, output, cleanup, and Windows acceptance.
- `docs/deployment.md`: M6 environment variables and artifact directories.
- `docs/security-model.md`: M6 private-key and cleanup boundary.
