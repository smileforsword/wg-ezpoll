# M0 PoC 中文 README

本目录保存 M0 架构验证用的 PoC。M0 的重点是验证高风险技术边界，不实现完整业务流程。

## 文件说明

- `self_packager.py`：项目自带自打包程序 PoC，把固定 WireGuard MSI、设备 INI 和 manifest 打成一个可校验载荷。
- `installer-assets/sample-wireguard.ini`：设备 INI 示例，仅用于 M0 验证。
- `wireguard-windows-installer-manifest.json`：固定 WireGuard Windows MSI 的版本、来源、大小和 SHA256。
- `wg_agent_socket_poc.py`：wg-agent Unix socket 通信 PoC。
- `linux/verify-wireguard-runtime.sh`：Linux 上验证 `wg set`、`wg show` 和 nftables table 替换。
- `access_rules.py`：生成多访问组 `AllowedIPs` 和 nftables 样例。
- `wg_show_parser.py`：解析 `wg show all dump` 输出。
- `samples/`：访问组和 WireGuard dump 示例数据。

## 本机快速验证

```bash
python -m pytest tests/m0
python -m poc.m0.access_rules
python -m poc.m0.wg_show_parser
```

如果已经下载固定 WireGuard MSI：

```bash
python -m poc.m0.self_packager build \
  --wireguard-msi C:/tmp/wireguard-amd64-1.1.msi \
  --device-ini poc/m0/installer-assets/sample-wireguard.ini \
  --output .m0-out/self-packager/wireportal-m0.package \
  --expected-msi-sha256 6DAA5D37A9E2950DFB8C48B95AB8E562CB2BAD1C785D020F38F97BEA4C6A5566

python -m poc.m0.self_packager inspect .m0-out/self-packager/wireportal-m0.package
python -m poc.m0.self_packager extract .m0-out/self-packager/wireportal-m0.package .m0-out/self-packager/extract
```

## Ubuntu/Debian 验证

Unix socket：

```bash
python3 -m poc.m0.wg_agent_socket_poc --smoke
```

WireGuard/nftables：

```bash
sudo bash poc/m0/linux/verify-wireguard-runtime.sh
```

隔离主机上验证真实 table 名称：

```bash
sudo NFT_TABLE=yourvpn ALLOW_YOURVPN_TABLE_REPLACE=1 bash poc/m0/linux/verify-wireguard-runtime.sh
```

## 自打包产物结构

`self_packager.py` 生成的包应包含：

```text
wireportal-package.json
payload/wireguard-amd64.msi
payload/device.ini
```

manifest 中的安装计划应为：

```text
extract_payload
install_or_detect_wireguard
set_wireguard_tunnel_from_ini
remove_intermediate_ini
```

## 注意事项

- M0 自打包产物还不是最终 Windows `.exe` runner；M6 会接入真实 Windows 自解压安装器。
- 客户端 private key 只允许进入临时 INI 和最终安装器产物，不允许入库或写日志。
- 当前开发机只能验证打包、解析、渲染和命令形状；WireGuard interface 和 nftables 必须在 Linux 验证机上验收。
