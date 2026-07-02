# M9 Development Notes

状态：已完成。

## Scope

M9 delivers the single-host deployment and recovery layer for V1:

- systemd services for API, Worker, and wg-agent.
- Nginx static frontend and API proxy configuration.
- Ubuntu/Debian installer script.
- system user, directory, key, database, WireGuard, and fixed MSI initialization.
- backup, restore, and reconcile operations.

## Deployment Assets

- `deploy/systemd/wireportal-api.service`
- `deploy/systemd/wireportal-worker.service`
- `deploy/systemd/wireportal-wg-agent.service`
- `deploy/nginx/wireportal.conf`
- `deploy/install/install-ubuntu-debian.sh`
- `deploy/ops/backup.sh`
- `deploy/ops/restore.sh`
- `deploy/ops/reconcile.sh`

## Defaults

- API: `127.0.0.1:8008`
- wg-agent: `/run/yourvpn/wg-agent.sock`
- Frontend: built static files in `/opt/yourvpn/www`
- SQLite: `/var/lib/yourvpn/db/wireportal.sqlite3`
- Fixed MSI cache: `/var/lib/yourvpn/installers/wireguard-amd64-1.1.msi`

## Validation

Validated on 2026-06-28:

```bash
python -m pytest tests/m9/test_deployment_assets.py
python -m compileall packages apps/api apps/worker apps/wg-agent tests/m9
```

Results:

- M9 deployment asset tests: `5 passed`.
- Python compile validation: passed.

## Notes For M10

- M10 should run the installer on a clean Ubuntu/Debian VM and verify `/setup`, service restart persistence, backup/restore, and reconcile.
- M10 should add a TLS/cookie-secure checklist before marking production release ready.
