from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_m9_deployment_assets_exist() -> None:
    required = [
        "deploy/systemd/wireportal-api.service",
        "deploy/systemd/wireportal-worker.service",
        "deploy/systemd/wireportal-wg-agent.service",
        "deploy/nginx/wireportal.conf",
        "deploy/install/install-ubuntu-debian.sh",
        "deploy/ops/backup.sh",
        "deploy/ops/restore.sh",
        "deploy/ops/reconcile.sh",
        "install.sh",
    ]

    for relative in required:
        assert (ROOT / relative).is_file(), relative


def test_systemd_units_keep_wg_agent_local() -> None:
    api = read("deploy/systemd/wireportal-api.service")
    worker = read("deploy/systemd/wireportal-worker.service")
    wg_agent = read("deploy/systemd/wireportal-wg-agent.service")

    assert "EnvironmentFile=/etc/yourvpn/yourvpn.env" in api
    assert "--host 127.0.0.1 --port 8008" in api
    assert "yourvpn_worker.main --interval 5" in worker
    assert "--socket /run/yourvpn/wg-agent.sock" in wg_agent
    assert "--http" not in wg_agent
    assert "RuntimeDirectoryMode=0770" in wg_agent
    assert "CAP_NET_ADMIN" in wg_agent


def test_nginx_proxies_only_api_and_static_frontend() -> None:
    nginx = read("deploy/nginx/wireportal.conf")

    assert "listen __NGINX_LISTEN_PORT__;" in nginx
    assert "proxy_pass http://127.0.0.1:8008/api/" in nginx
    assert "proxy_pass http://127.0.0.1:8009" not in nginx
    assert "wg-agent" not in nginx
    assert "try_files $uri $uri/ /index.html;" in nginx
    assert "proxy_set_header X-Forwarded-For $remote_addr;" in nginx
    assert "$proxy_add_x_forwarded_for" not in nginx


def test_install_script_covers_m9_installation_steps() -> None:
    script = read("deploy/install/install-ubuntu-debian.sh")

    assert script.startswith("#!/usr/bin/env bash")
    assert "set -Eeuo pipefail" in script
    assert "useradd --system" in script
    assert "openssl rand -base64 32" in script
    assert "python\" -m alembic" in script
    assert "pip install --upgrade pip setuptools wheel" in script
    assert "pip install --no-build-isolation -e \"$APP_DIR\"" in script
    package_block = script.split("apt-get install -y", 1)[1].split("}", 1)[0]
    assert "nginx" not in package_block
    assert "require_nginx" in script
    assert "command -v nginx" in script
    assert "NGINX_LISTEN_PORT" in script
    assert "NGINX_CONF_TARGET" in script
    assert "/www/server/panel/vhost/nginx/wireportal.conf" in script
    assert "NGINX_DISABLE_DEFAULT_SITE" in script
    assert 'if [[ "$NGINX_DISABLE_DEFAULT_SITE" == "true" ]]' in script
    assert "rm -f /etc/nginx/sites-enabled/default" in script
    assert "wg genkey" in script
    assert "wg-quick@$WG_INTERFACE.service" in script
    assert "WIREGUARD_MSI_SHA256" in script
    assert "WIREGUARD_MSI_REQUIRED" in script
    assert "--connect-timeout 5 --speed-time 20 --speed-limit 1 --max-time 20" in script
    assert "continuing with fake installer builder until MSI is supplied" in script
    assert "YOURVPN_FAKE_BUILDER_ENABLED=$fake_builder_enabled" in script
    assert "YOURVPN_INSTALLER_BUILDER_MODE=$installer_builder_mode" in script
    assert "sha256sum" in script
    assert "npm run build" in script
    assert "wireportal-api.service" in script
    assert "wireportal-wg-agent.service" in script
    assert "REQUIRED_NODE_MAJOR" in script
    assert "require_node_version" in script
    assert "YOURVPN_SESSION_COOKIE_SECURE=$SESSION_COOKIE_SECURE" in script


def test_root_bootstrap_script_clones_and_runs_installer() -> None:
    script = read("install.sh")

    assert script.startswith("#!/usr/bin/env bash")
    assert "REPO_URL" in script
    assert "RESOLVED_REPO_ROOT=" in script
    assert "BOOTSTRAP_GIT_TIMEOUT_SECONDS=\"${BOOTSTRAP_GIT_TIMEOUT_SECONDS:-20}\"" in script
    assert "NGINX_LISTEN_PORT=\"${NGINX_LISTEN_PORT:-80}\"" in script
    assert "default_base_url=\"http://$SERVER_NAME:$NGINX_LISTEN_PORT\"" in script
    assert 'repo_root="$(resolve_repo_root)"' not in script
    assert 'local source_path="${BASH_SOURCE[0]-}"' in script
    assert "local_script_dir=\"$(script_dir || true)\"" in script
    assert "printf '[wireportal-bootstrap] %s\\n' \"$*\" >&2" in script
    assert "GIT_TERMINAL_PROMPT=0 GIT_ASKPASS=/bin/false timeout --foreground" in script
    assert "detect_public_ip" in script
    assert "prompt_value SERVER_NAME" in script
    assert "prompt_value ADMIN_IP_WHITELIST" in script
    assert "log \"Fetching origin $REPO_REF with ${BOOTSTRAP_GIT_TIMEOUT_SECONDS}s timeout\"" in script
    assert "timed_git clone --branch \"$REPO_REF\" \"$REPO_URL\" \"$CHECKOUT_DIR\" >&2" in script
    assert "timed_git -C \"$CHECKOUT_DIR\" merge --ff-only \"origin/$REPO_REF\" >&2" in script
    assert "Git update did not complete; trying GitHub source archive fallback" in script
    assert "download_repo_archive" in script
    assert "--speed-time \"$BOOTSTRAP_GIT_TIMEOUT_SECONDS\"" in script
    assert "git -C \"$CHECKOUT_DIR\" pull" not in script
    assert "RESOLVED_REPO_ROOT=\"$CHECKOUT_DIR\"" in script
    assert "bash \"$RESOLVED_REPO_ROOT/deploy/install/install-ubuntu-debian.sh\"" in script
    assert "deploy/install/install-ubuntu-debian.sh" in script


def test_ops_scripts_exclude_artifacts_and_support_reconcile() -> None:
    backup = read("deploy/ops/backup.sh")
    restore = read("deploy/ops/restore.sh")
    reconcile = read("deploy/ops/reconcile.sh")

    assert "artifacts_included=false" in backup
    assert "build_tmp_included=false" in backup
    assert "sqlite3" in backup
    assert "wireportal.sqlite3" in restore
    assert "alembic" in restore
    assert "reconcile.sh" in restore
    assert "WgRuntimeModule().reconcile" in reconcile
