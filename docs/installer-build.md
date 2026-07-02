# Installer Build

状态：M6 已接入 `SelfPackInstallerBuilder`。当前实现会生成每设备专属 self-pack 安装器 artifact，内含固定 WireGuard MSI、设备 INI、Windows runner 脚本和 manifest；Windows 10/11 手动运行验收仍需在目标环境执行。

## Package Mode

V1 Windows packages are produced by the project self-packager.

Each package embeds:

- the fixed official WireGuard Windows MSI;
- one device-specific WireGuard INI file generated during build;
- a package manifest describing hashes, install plan, tunnel name, and cleanup behavior.

At install time, the Windows self-extracting runner installs or detects WireGuard, releases the INI file, sets it as the WireGuard tunnel configuration, and removes intermediate released files.

## Fixed WireGuard Asset

V1 embeds a fixed official WireGuard Windows MSI instead of downloading during user installation.

```json
{
  "file_name": "wireguard-amd64-1.1.msi",
  "architecture": "amd64",
  "version": "1.1",
  "source_url": "https://download.wireguard.com/windows-client/wireguard-amd64-1.1.msi",
  "sha256": "6DAA5D37A9E2950DFB8C48B95AB8E562CB2BAD1C785D020F38F97BEA4C6A5566",
  "size_bytes": 3227648,
  "verified_at": "2026-06-26"
}
```

The official index also provides `wireguard-installer.exe`, but that utility is a downloader/verifier for MSI files. For V1's no-download installation requirement, the embedded asset is the MSI.

## M0 PoC

Files:

- `poc/m0/wireguard-windows-installer-manifest.json`
- `poc/m0/installer-assets/sample-wireguard.ini`
- `poc/m0/self_packager.py`

Local validation:

```bash
python -m poc.m0.self_packager build \
  --wireguard-msi /opt/yourvpn/installers/wireguard-amd64-1.1.msi \
  --device-ini poc/m0/installer-assets/sample-wireguard.ini \
  --output .m0-out/self-packager/wireportal-m0.package \
  --expected-msi-sha256 6DAA5D37A9E2950DFB8C48B95AB8E562CB2BAD1C785D020F38F97BEA4C6A5566

python -m poc.m0.self_packager inspect .m0-out/self-packager/wireportal-m0.package
python -m poc.m0.self_packager extract .m0-out/self-packager/wireportal-m0.package .m0-out/self-packager/extract
```

Success criteria:

- The self-packager runs as a project-owned packaging command.
- The WireGuard MSI SHA256 matches the fixed manifest before packaging.
- The package contains `wireportal-package.json`, `payload/wireguard-amd64.msi`, and `payload/device.ini`.
- The manifest records the install plan: extract payload, install or detect WireGuard, set tunnel from INI, remove intermediate INI.

## M6 SelfPackInstallerBuilder

实现位置：

- `packages/python/yourvpn-core/src/yourvpn_core/modules/installer_builder.py`
- `packages/python/yourvpn-core/src/yourvpn_core/modules/devices.py`

构建输入来自设备生命周期：

- `device_id`
- `package_id`
- `device_name`
- `vpn_ip`
- inherited access group IDs
- compiled client `AllowedIPs`
- `YOURVPN_WIREGUARD_MSI_PATH`
- `YOURVPN_WIREGUARD_MSI_SHA256`
- `YOURVPN_WIREGUARD_INSTALLER_VERSION`
- `YOURVPN_WIREGUARD_SERVER_PUBLIC_KEY`
- `YOURVPN_WIREGUARD_ENDPOINT`

构建步骤：

1. 校验 WireGuard MSI 文件存在。
2. 计算 MSI SHA256，并与固定配置比对。
3. 在 `YOURVPN_BUILD_TMP_DIR` 下创建临时构建目录。
4. 生成客户端 WireGuard keypair。
5. 只把 public key 写入 `devices.public_key`。
6. 渲染临时 `device.ini`，private key 只进入该临时 INI 和最终 artifact。
7. 写入 Windows runner `runner/install-wireportal.ps1`。
8. 生成 `wireportal-package.json` manifest。
9. 生成 `wireportal-{device_id}.exe` artifact。
10. 计算 artifact SHA256 和 file size，写入 `install_packages`。
11. 删除临时构建目录，并验证临时 INI 已清理。

当前 artifact 内容：

- `wireportal-package.json`
- `payload/wireguard-amd64.msi`
- `payload/device.ini`
- `runner/install-wireportal.ps1`

Builder 模式：

- `YOURVPN_INSTALLER_BUILDER_MODE=self_pack`：强制真实 self-pack builder。
- `YOURVPN_INSTALLER_BUILDER_MODE=fake`：强制 M5 fake builder。
- `YOURVPN_INSTALLER_BUILDER_MODE=auto`：配置了 `YOURVPN_WIREGUARD_MSI_PATH` 时使用 self-pack，否则在 `YOURVPN_FAKE_BUILDER_ENABLED=true` 时回退 fake。

失败边界：

- MSI 缺失、SHA256 不匹配、endpoint/server public key 缺失时返回 `installer_build_failed`。
- 对应 `jobs` 记录为 `failed`，`install_packages.status=failed`，错误写入 `last_error`。

## M6 Windows Acceptance

M6 replaces the M0 package-only PoC with the `SelfPackInstallerBuilder` adapter while preserving the package manifest and asset contract.

Windows acceptance must verify:

- the generated artifact is runnable on Windows 10 and Windows 11;
- WireGuard is installed when missing and skipped when already present;
- the device INI is released and set as the WireGuard tunnel configuration;
- intermediate released INI files are removed after setup;
- client private keys are not written to the database or logs.

## Failure Boundaries

- If the self-packager format is insufficient, keep the `InstallerBuilder` seam and replace only the builder adapter.
- If the fixed MSI hash changes upstream, treat it as a security review event. Update the manifest only after manual verification.
- Automated M6 tests validate payload assembly, hashing, manifest content, private-key database boundary, failed build recording, and build-temp INI cleanup.
- Final Windows runner behavior remains a manual acceptance item on Windows 10/11.

## M9 Linux Build Environment

M9 installs the self-pack build environment on Ubuntu/Debian through `deploy/install/install-ubuntu-debian.sh`.

Production paths:

- `YOURVPN_WIREGUARD_MSI_PATH=/var/lib/yourvpn/installers/wireguard-amd64-1.1.msi`
- `YOURVPN_WIREGUARD_MSI_SHA256=6DAA5D37A9E2950DFB8C48B95AB8E562CB2BAD1C785D020F38F97BEA4C6A5566`
- `YOURVPN_ARTIFACTS_DIR=/var/lib/yourvpn/artifacts`
- `YOURVPN_BUILD_TMP_DIR=/var/lib/yourvpn/build-tmp`
- `YOURVPN_INSTALLER_BUILDER_MODE=self_pack`
- `YOURVPN_FAKE_BUILDER_ENABLED=false`

The installer accepts `WIREGUARD_MSI_SOURCE` as either a local path or HTTPS URL, copies the asset into the local cache, and verifies SHA256 before writing the production env file.

Directory permissions:

- `/var/lib/yourvpn/artifacts`: owned by `yourvpn:yourvpn`, mode `0750`.
- `/var/lib/yourvpn/build-tmp`: owned by `yourvpn:yourvpn`, mode `0700`.
- `/var/lib/yourvpn/installers`: owned by `root:yourvpn`, mode `0750`; MSI files are mode `0640`.

M9 backups include the fixed MSI cache but exclude artifacts and build-temp files.

## M5 Fake Builder

M5 introduces a fake builder to exercise the device and package lifecycle before the real self-extracting installer is connected.

Behavior:

- Creates a text artifact named `wireportal-{device_id}.fake-installer.txt`.
- Writes fake metadata: device ID, device name, VPN IP, fake public key, inherited access group IDs, and `config_format=ini`.
- Stores SHA256, file size, artifact path, fake signed status, and fake WireGuard installer version on `install_packages`.
- Moves the package to `ready_to_download`.
- Deletes the fake artifact after confirmed download, reset, revoke, or expiry.

Boundaries:

- No real WireGuard private key is generated in M5.
- M6 replaced only the builder adapter while preserving the package lifecycle APIs and state transitions.
