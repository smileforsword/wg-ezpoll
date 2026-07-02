# M0 Architecture Validation

M0 validates the risky system seams before the business skeleton begins in M1.

Chinese README: `poc/m0/README.zh-CN.md`.

## Coverage

- M0-01/M0-02: `poc/m0/self_packager.py` checks the project self-packager and builds a minimal self-packaged installer payload.
- M0-03/M0-04: `poc/m0/wireguard-windows-installer-manifest.json` fixes the embedded WireGuard amd64 MSI and SHA256; the self-packager embeds it together with `poc/m0/installer-assets/sample-wireguard.ini`.
- M0-05: `poc/m0/wg_agent_socket_poc.py` proves HTTP-style API/worker calls over a Unix socket.
- M0-06/M0-07/M0-08: `poc/m0/linux/verify-wireguard-runtime.sh` proves `wg set`, `wg show all dump`, and nftables table replacement on Linux.
- M0-09: `poc/m0/access_rules.py` renders sample `AllowedIPs` and a dedicated nftables table.

## Local checks

These checks avoid root-only Linux system calls and can run on the development machine:

```bash
python -m pytest tests/m0
python -m poc.m0.access_rules
python -m poc.m0.wg_show_parser
python -m poc.m0.self_packager build --wireguard-msi C:/tmp/wireguard-amd64-1.1.msi --output .m0-out/self-packager/wireportal-m0.package --expected-msi-sha256 6DAA5D37A9E2950DFB8C48B95AB8E562CB2BAD1C785D020F38F97BEA4C6A5566
```

The Unix socket smoke test is Linux-oriented:

```bash
python -m poc.m0.wg_agent_socket_poc --smoke
```

## Linux host checks

Run on a disposable Ubuntu/Debian host or VM.

```bash
python -m poc.m0.self_packager build \
  --wireguard-msi /opt/yourvpn/installers/wireguard-amd64-1.1.msi \
  --device-ini poc/m0/installer-assets/sample-wireguard.ini \
  --output .m0-out/self-packager/wireportal-m0.package \
  --expected-msi-sha256 6DAA5D37A9E2950DFB8C48B95AB8E562CB2BAD1C785D020F38F97BEA4C6A5566
```

```bash
sudo bash poc/m0/linux/verify-wireguard-runtime.sh
```

To verify the exact future table name, use an isolated host and opt in explicitly:

```bash
sudo NFT_TABLE=yourvpn ALLOW_YOURVPN_TABLE_REPLACE=1 bash poc/m0/linux/verify-wireguard-runtime.sh
```

## M0 boundary

Current development machine validation can prove parsing, rendering, command-shape, hash pinning, and self-packager payload assembly. WireGuard kernel and nftables replacement still need a Linux host acceptance run before M0 is marked fully accepted.
