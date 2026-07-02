# M0 Development Notes

状态：M0 验证已通过。当前仓库已落 M0 PoC 代码、样例和文档；Ubuntu/Debian 目标机验证已由用户确认成功。

## Checklist

| Task | Status | Evidence |
|---|---|---|
| M0-01 Project self-packager runs on Ubuntu/Debian | Done | `poc/m0/self_packager.py` |
| M0-02 Minimal self-packaged installer payload generated | Done | `poc/m0/self_packager.py` |
| M0-03 Fixed WireGuard Windows installer and SHA256 | Done | `poc/m0/wireguard-windows-installer-manifest.json` |
| M0-04 Minimal package embeds WireGuard installer and sample INI | Done | package contains fixed MSI and sample INI |
| M0-05 Unix socket API/worker to wg-agent communication | Done | `poc/m0/wg_agent_socket_poc.py` |
| M0-06 `wg set` add/remove peer | Done | `poc/m0/linux/verify-wireguard-runtime.sh` |
| M0-07 `wg show` status parsing | Done | `poc/m0/wg_show_parser.py`, tests |
| M0-08 nftables `yourvpn` table create/replace | Done | `poc/m0/linux/verify-wireguard-runtime.sh` |
| M0-09 Multi-access-group `AllowedIPs` and nftables sample | Done | `poc/m0/access_rules.py`, tests |

## Local Validation

```bash
python -m pytest tests/m0
python -m poc.m0.access_rules
python -m poc.m0.wg_show_parser
python -m poc.m0.self_packager build --wireguard-msi <wireguard-amd64-1.1.msi> --output .m0-out/self-packager/wireportal-m0.package --expected-msi-sha256 6DAA5D37A9E2950DFB8C48B95AB8E562CB2BAD1C785D020F38F97BEA4C6A5566
```

## Linux Acceptance

M0 could not be fully accepted from the Windows development environment alone because these items require Linux kernel/system capabilities:

- WireGuard interface creation and `wg set` behavior.
- nftables table replacement behavior and rollback safety.

On 2026-06-26, the user confirmed the Ubuntu/Debian target validation succeeded. M0 is accepted and development may proceed to M1.

## 2026-06-26 Local Development Run

- `python -m pytest tests/m0` passed on Windows with Python 3.13.7.
- `python -m poc.m0.access_rules` rendered the multi-access-group `AllowedIPs` and dedicated nftables table sample.
- `python -m poc.m0.wg_show_parser` parsed the sample `wg show all dump` data.
- `python -m poc.m0.self_packager build` generated a package with the fixed WireGuard MSI and sample INI; `inspect` and `extract` both succeeded.
- `python -m poc.m0.wg_agent_socket_poc --smoke` skipped on Windows because `AF_UNIX` is unavailable in this Python/platform combination.
- `python -m compileall poc tests` passed.
- `bash -n` could not run because local `bash.exe` points to WSL and no WSL distribution is installed.
