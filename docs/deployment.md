# Deployment

状态：M9 已补齐 Ubuntu/Debian 单机安装、systemd、Nginx、备份、恢复和 reconcile 操作。

## M0 Linux Validation Host

Use a disposable Ubuntu/Debian host or VM with root access for M0 system capability validation.

Required commands:

- `python3`
- `wireguard-tools` (`wg`)
- `iproute2` (`ip`)
- `nftables` (`nft`)
- `sha256sum`

## M0 Commands

Self-packager:

```bash
export WIREGUARD_MSI_PATH=/opt/yourvpn/installers/wireguard-amd64-1.1.msi
python -m poc.m0.self_packager build \
  --wireguard-msi "$WIREGUARD_MSI_PATH" \
  --device-ini poc/m0/installer-assets/sample-wireguard.ini \
  --output .m0-out/self-packager/wireportal-m0.package \
  --expected-msi-sha256 6DAA5D37A9E2950DFB8C48B95AB8E562CB2BAD1C785D020F38F97BEA4C6A5566
```

WireGuard/nftables:

```bash
sudo bash poc/m0/linux/verify-wireguard-runtime.sh
```

Exact future table-name validation on an isolated host:

```bash
sudo NFT_TABLE=yourvpn ALLOW_YOURVPN_TABLE_REPLACE=1 bash poc/m0/linux/verify-wireguard-runtime.sh
```

## M0 Recovery Notes

- The WireGuard runtime PoC creates a temporary interface `wg-m0-poc` by default and deletes it on exit.
- The nftables PoC uses `yourvpn_m0` by default and deletes it on exit.
- Replacing the exact `yourvpn` table requires explicit opt-in to reduce accidental damage on shared hosts.

## M1 Local Development

API:

```bash
set PYTHONPATH=packages/python/yourvpn-core/src;apps/api/src
python -m uvicorn yourvpn_api.main:app --host 127.0.0.1 --port 8008
```

Worker one-shot heartbeat:

```bash
set PYTHONPATH=packages/python/yourvpn-core/src;apps/worker/src
python -m yourvpn_worker.main --once
```

wg-agent HTTP development health app:

```bash
set PYTHONPATH=packages/python/yourvpn-core/src;apps/wg-agent/src
python -m uvicorn yourvpn_wg_agent.main:app --host 127.0.0.1 --port 8009
```

Frontend:

```bash
cd apps/frontend
npm.cmd install
npm.cmd run dev
```

## M2 Database Migration

Set `YOURVPN_DATABASE_URL` for the target database, then run Alembic from the repository root.

PowerShell example for SQLite development:

```powershell
$env:YOURVPN_DATABASE_URL="sqlite:///./wireportal.dev.sqlite3"
python -m alembic upgrade head
```

Linux example for MySQL production:

```bash
export YOURVPN_DATABASE_URL='mysql+pymysql://yourvpn:password@127.0.0.1:3306/yourvpn'
python -m alembic upgrade head
```

Recovery notes:

- Back up the database before every production migration.
- If migration fails before app startup, keep API/Worker stopped, restore from backup, then rerun after fixing the migration issue.
- wg-agent has no database access and does not participate in migration or recovery.

## M3 Authentication Settings

Environment variables:

- `YOURVPN_SESSION_COOKIE_NAME`: session cookie name, default `wireportal_session`.
- `YOURVPN_SESSION_COOKIE_SECURE`: set to `true` behind HTTPS in production.
- `YOURVPN_SESSION_TTL_MINUTES`: session lifetime, default `480`.
- `YOURVPN_CSRF_HEADER_NAME`: CSRF header name, default `x-csrf-token`.
- `YOURVPN_LOGIN_RATE_LIMIT_ATTEMPTS`: failed attempts before lockout, default `5`.
- `YOURVPN_LOGIN_RATE_LIMIT_WINDOW_MINUTES`: login failure window, default `15`.
- `YOURVPN_ADMIN_IP_WHITELIST`: comma-separated CIDR whitelist for `/api/admin/*`.
- `YOURVPN_PASSWORD_SETUP_TOKEN_TTL_HOURS`: password setup link lifetime, default `72`.
- `YOURVPN_SMTP_HOST`: SMTP host. Empty means approval returns a copyable setup link without sending email.
- `YOURVPN_SMTP_PORT`: SMTP port, default `25`.
- `YOURVPN_SMTP_FROM`: SMTP sender address.
- `YOURVPN_SMTP_USERNAME`: optional SMTP username.
- `YOURVPN_SMTP_PASSWORD`: optional SMTP password.
- `YOURVPN_SMTP_USE_TLS`: whether to call STARTTLS, default `false`.
- `YOURVPN_SMTP_TIMEOUT_SECONDS`: SMTP connection timeout, default `10`.

First setup:

```bash
curl -s http://127.0.0.1:8008/api/setup/status
curl -s -X POST http://127.0.0.1:8008/api/setup \
  -H 'content-type: application/json' \
  -d '{"email":"admin@example.com","display_name":"Admin","password":"GoodPass123"}'
```

After setup, repeat setup calls must return `setup_already_completed`.

## M4 Approval Settings

SMTP fallback:

- If `YOURVPN_SMTP_HOST` or `YOURVPN_SMTP_FROM` is empty, approval still succeeds.
- The approval response returns `notification_status=not_configured`.
- The approval response includes `setup_url` so an admin can copy the password setup link.
- When SMTP is configured, M4 attempts a direct SMTP send and returns `notification_status=sent` or `failed`.
- SMTP send failure does not roll back approval.

## M5/M6 Device And Package Settings

Environment variables:

- `YOURVPN_VPN_CIDR`: VPN client IP pool, default `10.77.0.0/20`.
- `YOURVPN_VPN_SERVER_IP`: server VPN IP, default `10.77.0.1`.
- `YOURVPN_INSTALL_PACKAGE_DOWNLOAD_WINDOW_MINUTES`: default fake artifact download window, default `120`.
- `YOURVPN_INSTALL_PACKAGE_MAX_DOWNLOAD_ATTEMPTS`: default max download attempts, default `5`.
- `YOURVPN_FAKE_BUILDER_ENABLED`: M5 fake builder switch, default `true`.
- `YOURVPN_INSTALLER_BUILDER_MODE`: `auto`, `fake`, or `self_pack`; default `auto`.
- `YOURVPN_WIREGUARD_MSI_PATH`: local fixed WireGuard MSI path for self-pack mode.
- `YOURVPN_WIREGUARD_MSI_SHA256`: pinned MSI SHA256.
- `YOURVPN_WIREGUARD_INSTALLER_VERSION`: embedded WireGuard MSI version, default `1.1`.
- `YOURVPN_WIREGUARD_SERVER_PUBLIC_KEY`: server public key rendered into device INI.
- `YOURVPN_WIREGUARD_ENDPOINT`: public WireGuard endpoint rendered into device INI, for example `vpn.example.com:51820`.
- `YOURVPN_WIREGUARD_PERSISTENT_KEEPALIVE_SECONDS`: device INI keepalive, default `25`.
- `YOURVPN_WIREGUARD_TUNNEL_NAME_PREFIX`: Windows tunnel name prefix, default `WirePortal`.

Artifacts:

- Fake and self-pack installer artifacts are written under `YOURVPN_ARTIFACTS_DIR`.
- M6 temporary INI files are written under `YOURVPN_BUILD_TMP_DIR` and must be deleted after build.
- Artifacts are deleted after confirmed download, reset, revoke, or expiry.
- Artifact directories should not be included in database backups.

## M7 Runtime Settings

Environment variables:

- `YOURVPN_WG_INTERFACE`: WireGuard interface managed by WirePortal, default `wg0`.
- `YOURVPN_NFT_TABLE_NAME`: dedicated nftables table name, default `yourvpn`.
- `YOURVPN_OUTBOUND_INTERFACE`: outbound interface used by MASQUERADE, default `eth0`.
- `YOURVPN_ENABLE_MASQUERADE`: whether to render default SNAT/MASQUERADE, default `true`.
- `YOURVPN_WG_AGENT_SOCKET_PATH`: Unix socket used by API/Worker to call wg-agent, default `/run/yourvpn/wg-agent.sock`.
- `YOURVPN_WG_AGENT_DRY_RUN`: when `true`, wg-agent returns successful command results without executing system commands. Production should keep this `false`.

wg-agent:

```bash
python -m yourvpn_wg_agent.main --socket /run/yourvpn/wg-agent.sock
```

Development TCP listener:

```bash
python -m yourvpn_wg_agent.main --http --host 127.0.0.1 --port 8009
```

Worker runtime job smoke test:

```bash
python -m yourvpn_worker.main --job-once
```

Runtime permissions:

- wg-agent must run as root or with enough capability to execute `wg`, `nft`, and `sysctl`.
- API/Worker must have filesystem permission to connect to the Unix socket.
- wg-agent must not be exposed through Nginx or any public TCP listener.
- wg-agent only accepts replacement rulesets for `YOURVPN_NFT_TABLE_NAME`.

## M8 Frontend Console Deployment

M8 does not add deployment-time environment variables. It expands the Vue frontend into the V1 operator and user console.

Production serving rules:

- Serve the built frontend and `/api` from the same HTTPS origin so `SameSite=Strict` session cookies work without CORS exceptions.
- Keep `/api/admin/*` behind `YOURVPN_ADMIN_IP_WHITELIST`; the browser UI is not a substitute for backend IP allow-listing.
- Do not expose wg-agent to the frontend. Runtime health must continue to flow through `GET /api/admin/runtime/health`.
- When SMTP is not configured, operators must copy the approval `setup_url` from the admin console and deliver it out of band.
- Frontend static files can be rebuilt and replaced without database migration, but API and frontend versions should be deployed together after M8 because the console expects the M8 admin endpoints.

## M9 Ubuntu/Debian Single-Host Install

M9 deployment assets:

- `deploy/install/install-ubuntu-debian.sh`
- `deploy/systemd/wireportal-api.service`
- `deploy/systemd/wireportal-worker.service`
- `deploy/systemd/wireportal-wg-agent.service`
- `deploy/nginx/wireportal.conf`
- `deploy/ops/backup.sh`
- `deploy/ops/restore.sh`
- `deploy/ops/reconcile.sh`

Prerequisites:

- Existing Nginx installation. The installer writes the WirePortal site config and reloads Nginx, but does not install the Nginx package.
- Node.js 18+ for the frontend build.
- Root access, WireGuard kernel support, and outbound network access for Python/npm dependencies and the fixed WireGuard Windows MSI unless local caches are provided.

Default production ports:

- Nginx listens on `80`.
- API listens on `127.0.0.1:8008`.
- wg-agent listens only on `/run/yourvpn/wg-agent.sock`.
- Frontend is served as static files from `/opt/yourvpn/www`; Vite is not used in production.

Minimal install from a repository checkout:

```bash
sudo SERVER_NAME=vpn.example.com \
  PUBLIC_BASE_URL=https://vpn.example.com \
  WIREGUARD_ENDPOINT=vpn.example.com:51820 \
  ADMIN_IP_WHITELIST=203.0.113.0/24 \
  bash deploy/install/install-ubuntu-debian.sh
```

Bootstrap from GitHub on a fresh Ubuntu/Debian host:

```bash
curl -fsSL https://raw.githubusercontent.com/OWNER/REPO/main/install.sh | sudo env \
  REPO_URL=https://github.com/OWNER/REPO.git \
  REPO_REF=main \
  bash
```

The bootstrap script prompts for the public domain or server public IP, public Web base URL, WireGuard endpoint, and admin IP whitelist CIDR. Set any of `SERVER_NAME`, `PUBLIC_BASE_URL`, `WIREGUARD_ENDPOINT`, or `ADMIN_IP_WHITELIST` in the environment to skip that prompt.

The installer defaults `WIREGUARD_MSI_SOURCE` to the fixed official MSI URL and verifies SHA256 before caching it. For offline or internal deployments, provide a local file:

```bash
sudo WIREGUARD_MSI_SOURCE=/srv/installers/wireguard-amd64-1.1.msi \
  SERVER_NAME=vpn.example.com \
  PUBLIC_BASE_URL=https://vpn.example.com \
  WIREGUARD_ENDPOINT=vpn.example.com:51820 \
  bash deploy/install/install-ubuntu-debian.sh
```

The fixed MSI hash remains:

```text
6DAA5D37A9E2950DFB8C48B95AB8E562CB2BAD1C785D020F38F97BEA4C6A5566
```

### Installed Layout

```text
/opt/yourvpn/app                 application source
/opt/yourvpn/venv                Python virtualenv
/opt/yourvpn/www                 built Vue static files
/etc/yourvpn/yourvpn.env         systemd EnvironmentFile
/etc/yourvpn/master.key          local master key placeholder for secret encryption
/etc/yourvpn/wg0.private.key     server WireGuard private key
/etc/yourvpn/wg0.public.key      server WireGuard public key
/etc/wireguard/wg0.conf          wg-quick interface config
/var/lib/yourvpn/db              SQLite database directory
/var/lib/yourvpn/artifacts       downloadable package artifacts
/var/lib/yourvpn/build-tmp       temporary self-pack build directory
/var/lib/yourvpn/installers      fixed WireGuard Windows MSI cache
/var/backups/yourvpn             backup archives
/run/yourvpn/wg-agent.sock       wg-agent Unix socket
```

Ownership:

- `yourvpn` system user owns database, artifact, build-temp, and log directories.
- `/etc/yourvpn` is `root:yourvpn` with private files mode `0640`.
- `/var/lib/yourvpn/build-tmp` is mode `0700` to limit temporary INI exposure.
- wg-agent runs as root with `CAP_NET_ADMIN` and exposes only the Unix socket.

### Systemd

```bash
sudo systemctl status wireportal-api
sudo systemctl status wireportal-worker
sudo systemctl status wireportal-wg-agent
sudo journalctl -u wireportal-api -f
```

Restart after config changes:

```bash
sudo systemctl restart wireportal-wg-agent wireportal-worker wireportal-api
sudo systemctl reload nginx
```

### Nginx

The installed Nginx site serves the frontend and proxies:

- `/api/*` to `http://127.0.0.1:8008/api/*`
- `/health` to `http://127.0.0.1:8008/health`

It must not expose wg-agent. TLS termination should be added through the operator's normal certificate workflow before setting `YOURVPN_SESSION_COOKIE_SECURE=true`.

### Database Initialization

The installer runs:

```bash
python -m alembic -c /opt/yourvpn/app/alembic.ini upgrade head
```

SQLite is stored at `/var/lib/yourvpn/db/wireportal.sqlite3` by default. MySQL remains configurable through `YOURVPN_DATABASE_URL`, but production MySQL backup/restore must use the site's database tooling in addition to the app config backup.

### WireGuard Initialization

The installer:

- generates `/etc/yourvpn/wg0.private.key` and `/etc/yourvpn/wg0.public.key` if absent;
- writes `/etc/wireguard/wg0.conf` if absent;
- enables IPv4 forwarding through `/etc/sysctl.d/99-yourvpn.conf`;
- starts `wg-quick@wg0.service` by default.

Set `ENABLE_WG_QUICK=false` when preparing an image where the interface must not start during install.

## M9 Backup, Restore, And Reconcile

Regular SQLite backup:

```bash
sudo /opt/yourvpn/app/deploy/ops/backup.sh
```

The backup archive includes:

- `/etc/yourvpn`
- `/etc/wireguard`
- `/var/lib/yourvpn/db/wireportal.sqlite3`
- `/var/lib/yourvpn/installers`
- a backup manifest and SHA256 sidecar

It intentionally excludes:

- `/var/lib/yourvpn/artifacts`
- `/var/lib/yourvpn/build-tmp`

Package artifacts are short-lived downloadable material and are deleted after confirmed download/reset/revoke/expiry. They are not disaster-recovery source of truth.

Restore:

```bash
sudo /opt/yourvpn/app/deploy/ops/restore.sh /var/backups/yourvpn/wireportal-YYYYMMDDTHHMMSSZ.tar.gz
```

The restore script stops WirePortal services, restores config/database/installer cache, runs Alembic to current head, restarts services, and invokes reconcile.

Manual reconcile after runtime drift or restore:

```bash
sudo /opt/yourvpn/app/deploy/ops/reconcile.sh
```

Disaster recovery checklist:

1. Restore `/etc/yourvpn/master.key` and `/etc/yourvpn/wg0.private.key` from backup before starting services.
2. Restore the database and WireGuard MSI cache.
3. Run Alembic upgrade head.
4. Start `wg-quick@wg0`, `wireportal-wg-agent`, `wireportal-worker`, and `wireportal-api`.
5. Run reconcile to remove unknown peers and apply database-authoritative peers/firewall rules.
6. Open `/api/admin/runtime/health` from an allowed admin IP and confirm database, job, and wg-agent status.
