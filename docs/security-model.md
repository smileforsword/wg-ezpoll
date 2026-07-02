# Security Model

状态：M9 已补齐单机部署安全边界。M10 会继续补齐发布加固。

## M0 Decisions

- wg-agent is local-only over a Unix socket and must never be exposed through Nginx or TCP.
- wg-agent must not read application databases or business configuration.
- API/Worker own policy decisions and pass explicit target state to wg-agent.
- nftables changes are constrained to a dedicated `yourvpn` table.
- The embedded WireGuard Windows MSI is pinned by SHA256 before any self-packager build.
- The official MSI is preferred over `wireguard-installer.exe` to avoid user-install-time network downloads.
- Windows packages are self-extracting installers that release a device-specific WireGuard INI and set it as the tunnel configuration.

## Private Key Boundary

- Client private keys are generated during package build and must only enter the temporary WireGuard INI and the self-extracting installer artifact.
- Client private keys must not be persisted in the database or logs.
- M6 automated tests verify temporary build INI deletion after build.
- M6 Windows runner includes cleanup for the intermediate released INI after tunnel installation; Windows 10/11 manual acceptance must still verify it on target hosts.
- M5/M6 must delete installer artifacts after confirmed download.

## M0 Safety Defaults

- Runtime validation scripts use `wg-m0-poc` and `yourvpn_m0` by default.
- Replacing the production table name `yourvpn` requires `ALLOW_YOURVPN_TABLE_REPLACE=1`.
- M0 scripts are intended for disposable Linux validation hosts, not production machines.

## M2 Database Security Boundaries

- `server_secrets` stores only encrypted server-side secret material: `ciphertext`, `nonce`, `algorithm`, and `key_version`.
- Client WireGuard private keys are still outside the database boundary. They may only exist in temporary build inputs and installer artifacts until M6 artifact cleanup is confirmed.
- `system_settings.is_secret=true` marks values that must not be returned by public/admin APIs without explicit redaction logic.
- `sessions.session_token_hash`, `sessions.csrf_token_hash`, and `password_tokens.token_hash` store hashes only; plaintext tokens must not be persisted.
- `login_attempts` records success/failure by email and IP for future throttling and audit review.

## M2 Authorization Rules

- `Role.ADMIN` can perform all admin-level actions and can grant high-privilege access groups.
- `Role.APPROVER` can grant ordinary access groups but cannot grant `access_groups.is_high_privilege=true`.
- Admin API IP whitelist checks are represented in `AuthorizationModule.require_admin_ip_allowed()` and wired to API middleware in M3.
- The state machine module is the authority for legal transitions of applications, users, devices, install packages, and worker jobs.

## M2 Audit Model

- `audit_logs` records actor, action, target, optional before/after JSON, IP, user agent, and creation time.
- Security-sensitive M3/M4 state changes call the audit module.
- `traffic_snapshots` records WireGuard peer traffic samples separately from audit logs so operational telemetry does not dilute security audit history.

## M3 Authentication Model

- Password hashes use Argon2id through `argon2-cffi`.
- Password policy requires at least 8 characters, at least one letter, and at least one number.
- Session tokens, CSRF tokens, and password setup/reset tokens are generated with `secrets.token_urlsafe(32)`.
- Only token hashes are persisted in `sessions` and `password_tokens`.
- `pending_password` users cannot log in until a password setup token is consumed.
- Login failures are recorded in `login_attempts` and mirrored to `audit_logs` as `auth.login_rejected`.
- Login rate limiting is enforced by email or source IP over the configured rolling window.

## M3 Cookie And CSRF Rules

- Session cookie default name: `wireportal_session`.
- Cookie attributes: `HttpOnly`, `SameSite=Strict`, `Path=/`.
- Production must set `YOURVPN_SESSION_COOKIE_SECURE=true`.
- Unsafe authenticated endpoints require the CSRF token returned by login in the configured header, default `x-csrf-token`.
- CSRF failures return `csrf_failed`.

## M3 Setup And Admin IP Boundary

- First setup is allowed only when no admin exists and `system_settings.setup_completed` is not true.
- Successful setup creates the first `admin`, stores `setup_completed`, and writes `setup.completed`.
- Repeated setup attempts are rejected and audited as `setup.rejected`.
- `/api/admin/*` is protected by the configured CIDR whitelist before route handling.
- Admin IP whitelist rejections are audited as `security.admin_ip_rejected`.

## M4 Application Approval Boundary

- Public applications do not require authentication and are limited to 1-3 requested devices.
- Approval endpoints require authenticated `admin` or `approver` role.
- Approval and rejection POST endpoints require CSRF.
- `approver` cannot grant `access_groups.is_high_privilege=true`; only `admin` can.
- M4 caps `approved_device_limit` at 10. Higher limits must be handled by a later admin-only management flow.
- Approval creates a `pending_password` user, optional user access-group grants, a one-time password setup token, an approval record, and an audit log.
- SMTP being unavailable does not block approval. The API returns `setup_url` for background copy.
- Approval and rejection are audited as `application.approved` and `application.rejected`.

## M5 Device And Package Boundary

- Users may only list, download, confirm, and report lost for their own devices and packages.
- Device creation is capped by `users.approved_device_limit`.
- Confirming download is the first point where an `apply_peer` job is enqueued; before confirmation, runtime peer activation is not requested.
- Package download attempts are counted and capped by `max_download_attempts`.
- Package artifacts are deleted after confirmed download and are not intended for backups.
- M5 fake builder does not generate real private keys. M6 self-pack mode generates client private keys only inside the temporary INI and final artifact; tests verify private keys do not enter manifest or database fields.
- Admin reset and revoke endpoints require `admin` role and CSRF.

## M7 Runtime Execution Boundary

- wg-agent exposes HTTP only over a Unix domain socket in production.
- wg-agent has no database imports or database access path; it only executes payloads from API/Worker.
- API/Worker/core build runtime target state from database authority.
- Runtime target state includes only `download_confirmed` and `active` devices.
- Server WireGuard peer `AllowedIPs` is restricted to each device VPN IP `/32`.
- Access-group destination routes are enforced through the dedicated nftables table.
- wg-agent validates that firewall payloads target only `YOURVPN_NFT_TABLE_NAME`, default `yourvpn`.
- nftables replacement is performed with `nft -f -` against a complete single-table ruleset.
- Reconcile removes WireGuard peers not present in the supplied target state before applying target peers.
- `sample_wg_status` writes operational traffic snapshots, not security audit records.

## M8 Browser Console Boundary

- The Vue console is a same-origin browser client for the API; it does not receive privileged secrets beyond the session cookie and CSRF token returned by login.
- The UI does not bypass backend authorization. All admin console calls still use `/api/admin/*`, the admin IP whitelist middleware, session authentication, and route-level role checks.
- Approval list/detail, user list, device list, access-group list/detail, audit-log list, and runtime health require an authenticated `admin` or `approver`.
- Access-group creation requires `admin` role and CSRF, because it can expand future network reachability.
- Device reset and revoke remain `admin` only and require CSRF.
- The console shows SMTP fallback setup URLs only from the approval response. These one-time URLs must not be stored in frontend state beyond the current browser session.
- Audit-log browsing is read-only; M8 does not add audit deletion or mutation APIs.
- Runtime health exposes wg-agent/database/job status, but wg-agent remains local-only and is never called directly from the browser.

## M9 Deployment Security Boundary

- Production systemd services read `/etc/yourvpn/yourvpn.env`; this file is `root:yourvpn` and mode `0640`.
- The installer initializes `/etc/yourvpn/master.key` for future server secret encryption support. It is not stored in the database or repository.
- Server WireGuard private key material lives in `/etc/yourvpn/wg0.private.key` and `/etc/wireguard/wg0.conf`; both must be included in disaster backups and protected as host secrets.
- API and Worker run as the unprivileged `yourvpn` user.
- wg-agent runs as root with network capabilities and exposes only `/run/yourvpn/wg-agent.sock`; Nginx never proxies wg-agent.
- The fixed WireGuard Windows MSI is cached under `/var/lib/yourvpn/installers` only after SHA256 verification.
- `/var/lib/yourvpn/build-tmp` is mode `0700` because temporary per-device INI files may contain client private keys during package build.
- Backups intentionally exclude package artifacts and build-temp content. Database state, server keys, config, and fixed installer cache are the recovery source of truth.
- Restore must run reconcile before accepting production traffic so runtime peers and nftables rules return to database-authoritative state.
