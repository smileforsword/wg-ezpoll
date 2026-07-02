# M10 Ubuntu Real-Host Acceptance

Status: draft for real Ubuntu validation.

M10 turns the M9 deployment assets into a release gate. Run this on a clean Ubuntu host before treating WirePortal as production-ready.

## Target Host

Recommended baseline:

- Ubuntu 24.04 LTS.
- Root or passwordless sudo access.
- Public DNS name pointing to the host.
- TCP 80 for the web portal.
- UDP 51820 for WireGuard.
- Existing Nginx installation. The WirePortal installer configures and reloads Nginx, but does not install the package.
- Node.js 18+ available before the installer builds the Vue frontend. Ubuntu 22.04 often needs a newer Node.js source before running the installer.

Record before install:

```bash
lsb_release -a
python3 --version
node --version
npm --version
ip route
```

## Install Command

Run from a repository checkout:

```bash
sudo SERVER_NAME=vpn.example.com \
  PUBLIC_BASE_URL=https://vpn.example.com \
  WIREGUARD_ENDPOINT=vpn.example.com:51820 \
  ADMIN_IP_WHITELIST=203.0.113.0/24 \
  bash deploy/install/install-ubuntu-debian.sh
```

Or bootstrap from GitHub with the root `install.sh`:

```bash
curl -fsSL https://raw.githubusercontent.com/OWNER/REPO/main/install.sh | sudo env \
  REPO_URL=https://github.com/OWNER/REPO.git \
  REPO_REF=main \
  SERVER_NAME=vpn.example.com \
  PUBLIC_BASE_URL=https://vpn.example.com \
  WIREGUARD_ENDPOINT=vpn.example.com:51820 \
  ADMIN_IP_WHITELIST=203.0.113.0/24 \
  bash
```

For offline or controlled environments, provide the fixed WireGuard MSI from local storage:

```bash
sudo WIREGUARD_MSI_SOURCE=/srv/installers/wireguard-amd64-1.1.msi \
  SERVER_NAME=vpn.example.com \
  PUBLIC_BASE_URL=https://vpn.example.com \
  WIREGUARD_ENDPOINT=vpn.example.com:51820 \
  ADMIN_IP_WHITELIST=203.0.113.0/24 \
  bash deploy/install/install-ubuntu-debian.sh
```

If TLS is terminated at this Nginx host or an upstream proxy and `PUBLIC_BASE_URL` starts with `https://`, the installer should write:

```text
YOURVPN_SESSION_COOKIE_SECURE=true
```

If TLS is added after initial HTTP validation, edit `/etc/yourvpn/yourvpn.env`, set `YOURVPN_SESSION_COOKIE_SECURE=true`, then restart:

```bash
sudo systemctl restart wireportal-api
sudo systemctl reload nginx
```

## Service Gates

All services must be enabled and healthy:

```bash
sudo systemctl status wg-quick@wg0
sudo systemctl status wireportal-wg-agent
sudo systemctl status wireportal-worker
sudo systemctl status wireportal-api
sudo systemctl status nginx
```

Verify local listeners:

```bash
sudo ss -lntup
sudo ss -lx | grep wg-agent
```

Acceptance:

- Nginx listens publicly on TCP 80 or the configured TLS port.
- API listens only on `127.0.0.1:8008`.
- wg-agent is not exposed over TCP.
- wg-agent listens only on `/run/yourvpn/wg-agent.sock`.

## Browser Flow

Complete the full UI path:

1. Open `/setup` and create the first admin.
2. Submit a public application.
3. Approve the application from an allowed admin IP.
4. Copy the password setup link if SMTP is not configured.
5. Set the user password.
6. Log in as the user.
7. Create a device.
8. Download the Windows package.
9. Confirm download.
10. Wait for the worker to apply the runtime job.

Then verify:

```bash
sudo wg show wg0
sudo nft list table ip yourvpn
sudo journalctl -u wireportal-worker -n 100 --no-pager
```

## Security Gates

Check these before opening the service beyond a test network:

- `ADMIN_IP_WHITELIST` is set to explicit CIDRs.
- `YOURVPN_SESSION_COOKIE_SECURE=true` after HTTPS is active.
- Nginx sanitizes forwarded client IPs with `X-Forwarded-For $remote_addr`.
- `/api/admin/*` rejects requests outside the admin IP whitelist.
- `/run/yourvpn/wg-agent.sock` is group-readable only by the service group.
- `/etc/yourvpn/master.key` and `/etc/yourvpn/wg0.private.key` are not world-readable.
- `/var/lib/yourvpn/build-tmp` is mode `0700`.
- Package artifacts are deleted after confirmed download.

## Backup, Restore, Reconcile

Create a backup on the first host:

```bash
sudo /opt/yourvpn/app/deploy/ops/backup.sh
sudo sha256sum -c /var/backups/yourvpn/wireportal-*.tar.gz.sha256
```

Restore onto a second clean host with the same app version:

```bash
sudo /opt/yourvpn/app/deploy/ops/restore.sh /var/backups/yourvpn/wireportal-YYYYMMDDTHHMMSSZ.tar.gz
```

Run reconcile after restore or suspected drift:

```bash
sudo /opt/yourvpn/app/deploy/ops/reconcile.sh
sudo wg show wg0
sudo nft list table ip yourvpn
```

Acceptance:

- Restored admin login works.
- Device and user records are present.
- Unknown peers are removed.
- Database-authoritative peers and nftables rules are applied.
- Short-lived artifacts and build temp files are not restored as source of truth.

## Release Decision

Mark M10 accepted only when:

- Local automated tests pass.
- Installer succeeds on the target Ubuntu version.
- The browser flow succeeds end to end.
- Backup and restore succeed on a second host.
- wg-agent is not reachable over TCP or through Nginx.
- TLS and secure cookie settings are confirmed.
- Remaining caveats are written into release notes.
