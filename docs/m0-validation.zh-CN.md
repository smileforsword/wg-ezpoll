# M0 验证说明

本文档用于验收 WirePortal V1 的 M0 架构验证。M0 的目标不是完成业务功能，而是在进入 M1 工程骨架前，先确认高风险技术边界可行。

## 验证范围

| 编号 | 验证项 | 当前产物 |
|---|---|---|
| M0-01 | 项目自带自打包程序可运行 | `poc/m0/self_packager.py` |
| M0-02 | 可生成最小自打包安装器载荷 | `poc/m0/self_packager.py` |
| M0-03 | 固定 WireGuard Windows 安装器版本和 SHA256 | `poc/m0/wireguard-windows-installer-manifest.json` |
| M0-04 | 自打包产物内置 WireGuard MSI 和设备 INI | `poc/m0/installer-assets/sample-wireguard.ini` |
| M0-05 | API/Worker 到 wg-agent 的 Unix socket 通信 | `poc/m0/wg_agent_socket_poc.py` |
| M0-06 | `wg set` 添加和移除 peer | `poc/m0/linux/verify-wireguard-runtime.sh` |
| M0-07 | `wg show all dump` 状态解析 | `poc/m0/wg_show_parser.py` |
| M0-08 | nftables 专用 table 创建和替换 | `poc/m0/linux/verify-wireguard-runtime.sh` |
| M0-09 | 多访问组 `AllowedIPs` 和 nftables 样例生成 | `poc/m0/access_rules.py` |

## 本机可验证项目

这些命令不需要 Linux root 网络能力，可在开发机运行。

```bash
python -m pytest tests/m0
python -m poc.m0.access_rules
python -m poc.m0.wg_show_parser
```

如果本机已有固定版本 WireGuard MSI，可验证自打包流程：

```bash
python -m poc.m0.self_packager build \
  --wireguard-msi C:/tmp/wireguard-amd64-1.1.msi \
  --device-ini poc/m0/installer-assets/sample-wireguard.ini \
  --output .m0-out/self-packager/wireportal-m0.package \
  --expected-msi-sha256 6DAA5D37A9E2950DFB8C48B95AB8E562CB2BAD1C785D020F38F97BEA4C6A5566

python -m poc.m0.self_packager inspect .m0-out/self-packager/wireportal-m0.package
python -m poc.m0.self_packager extract .m0-out/self-packager/wireportal-m0.package .m0-out/self-packager/extract
```

通过标准：

- pytest 全部通过。
- `access_rules` 输出去重后的 `AllowedIPs` 和 `table ip yourvpn` 样例。
- `wg_show_parser` 输出 peer JSON。
- self-packager 产物包含：
  - `wireportal-package.json`
  - `payload/wireguard-amd64.msi`
  - `payload/device.ini`
- manifest 中的安装计划包含：
  - `extract_payload`
  - `install_or_detect_wireguard`
  - `set_wireguard_tunnel_from_ini`
  - `remove_intermediate_ini`

## Ubuntu/Debian 目标机验收

以下项目必须在一次性 Ubuntu/Debian 验证机或 VM 上运行。不要在生产机直接执行。

### 自打包程序

```bash
python3 -m poc.m0.self_packager build \
  --wireguard-msi /opt/yourvpn/installers/wireguard-amd64-1.1.msi \
  --device-ini poc/m0/installer-assets/sample-wireguard.ini \
  --output .m0-out/self-packager/wireportal-m0.package \
  --expected-msi-sha256 6DAA5D37A9E2950DFB8C48B95AB8E562CB2BAD1C785D020F38F97BEA4C6A5566
```

### Unix socket smoke test

```bash
python3 -m poc.m0.wg_agent_socket_poc --smoke
```

通过标准：

- 返回 JSON 中 `health_status` 为 `200`。
- 返回 JSON 中 `apply_status` 为 `200`。
- `health.database_access` 为 `false`。

### WireGuard 与 nftables

```bash
sudo bash poc/m0/linux/verify-wireguard-runtime.sh
```

通过标准：

- 脚本能创建临时 WireGuard interface。
- `wg set` 能添加 peer。
- `wg show` dump 能输出 peer 状态。
- `wg set peer remove` 能移除 peer。
- nftables 能创建并替换 PoC table。
- 脚本退出后会清理临时 interface 和 table。

如需验证未来真实 table 名称，必须使用隔离主机并显式确认：

```bash
sudo NFT_TABLE=yourvpn ALLOW_YOURVPN_TABLE_REPLACE=1 bash poc/m0/linux/verify-wireguard-runtime.sh
```

## 固定 WireGuard MSI

M0 固定资产：

- 文件名：`wireguard-amd64-1.1.msi`
- 来源：`https://download.wireguard.com/windows-client/wireguard-amd64-1.1.msi`
- SHA256：`6DAA5D37A9E2950DFB8C48B95AB8E562CB2BAD1C785D020F38F97BEA4C6A5566`
- 大小：`3227648` bytes

如果 SHA256 不匹配，不允许继续打包。必须重新人工确认来源和版本。

## M0 完成标准

M0 可标记完成需要同时满足：

- 本机单元测试和样例输出通过。
- 自打包程序能使用固定 MSI 生成、检查、解包产物。
- Ubuntu/Debian 上 Unix socket smoke test 通过。
- Ubuntu/Debian 上 WireGuard/nftables runtime 脚本通过。
- 验证输出记录到 `docs/m0-development-notes.md`。

当前 Windows 开发机不能完整验收 M0，因为 WireGuard interface、`wg set` 和 nftables 替换依赖 Linux 内核网络能力。
