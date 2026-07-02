#!/usr/bin/env bash
set -Eeuo pipefail

SERVICE_USER="${SERVICE_USER:-yourvpn}"
SERVICE_GROUP="${SERVICE_GROUP:-yourvpn}"
INSTALL_ROOT="${INSTALL_ROOT:-/opt/yourvpn}"
APP_DIR="${APP_DIR:-$INSTALL_ROOT/app}"
VENV_DIR="${VENV_DIR:-$INSTALL_ROOT/venv}"
STATIC_DIR="${STATIC_DIR:-$INSTALL_ROOT/www}"
CONFIG_DIR="${CONFIG_DIR:-/etc/yourvpn}"
ENV_FILE="${ENV_FILE:-$CONFIG_DIR/yourvpn.env}"
MASTER_KEY_FILE="${MASTER_KEY_FILE:-$CONFIG_DIR/master.key}"
STATE_DIR="${STATE_DIR:-/var/lib/yourvpn}"
DB_DIR="${DB_DIR:-$STATE_DIR/db}"
ARTIFACTS_DIR="${ARTIFACTS_DIR:-$STATE_DIR/artifacts}"
BUILD_TMP_DIR="${BUILD_TMP_DIR:-$STATE_DIR/build-tmp}"
INSTALLERS_DIR="${INSTALLERS_DIR:-$STATE_DIR/installers}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/yourvpn}"
LOG_DIR="${LOG_DIR:-/var/log/yourvpn}"
WG_INTERFACE="${WG_INTERFACE:-wg0}"
VPN_CIDR="${VPN_CIDR:-10.77.0.0/20}"
VPN_SERVER_IP="${VPN_SERVER_IP:-10.77.0.1}"
WIREGUARD_LISTEN_PORT="${WIREGUARD_LISTEN_PORT:-51820}"
HOST_FQDN="$(hostname -f 2>/dev/null || hostname)"
SERVER_NAME="${SERVER_NAME:-$HOST_FQDN}"
PUBLIC_BASE_URL="${PUBLIC_BASE_URL:-http://$SERVER_NAME}"
WIREGUARD_ENDPOINT="${WIREGUARD_ENDPOINT:-$SERVER_NAME:$WIREGUARD_LISTEN_PORT}"
OUTBOUND_INTERFACE="${OUTBOUND_INTERFACE:-eth0}"
ADMIN_IP_WHITELIST="${ADMIN_IP_WHITELIST:-}"
WIREGUARD_MSI_FILE_NAME="${WIREGUARD_MSI_FILE_NAME:-wireguard-amd64-1.1.msi}"
WIREGUARD_MSI_SHA256="${WIREGUARD_MSI_SHA256:-6DAA5D37A9E2950DFB8C48B95AB8E562CB2BAD1C785D020F38F97BEA4C6A5566}"
WIREGUARD_MSI_SOURCE="${WIREGUARD_MSI_SOURCE:-https://download.wireguard.com/windows-client/wireguard-amd64-1.1.msi}"
ENABLE_WG_QUICK="${ENABLE_WG_QUICK:-true}"
ENABLE_SYSTEMD="${ENABLE_SYSTEMD:-true}"
REQUIRED_NODE_MAJOR="${REQUIRED_NODE_MAJOR:-18}"
SESSION_COOKIE_SECURE="${SESSION_COOKIE_SECURE:-}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

log() {
    printf '[wireportal-install] %s\n' "$*"
}

require_root() {
    if [[ "${EUID}" -ne 0 ]]; then
        printf 'Run this installer as root.\n' >&2
        exit 1
    fi
}

require_debian_like() {
    if [[ ! -r /etc/os-release ]]; then
        printf 'Cannot detect OS: /etc/os-release is missing.\n' >&2
        exit 1
    fi
    . /etc/os-release
    case "${ID:-}" in
        debian|ubuntu) ;;
        *)
            case " ${ID_LIKE:-} " in
                *" debian "*) ;;
                *)
                    printf 'Unsupported OS: %s. Use Ubuntu or Debian.\n' "${PRETTY_NAME:-unknown}" >&2
                    exit 1
                    ;;
            esac
            ;;
    esac
}

install_packages() {
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y \
        ca-certificates \
        curl \
        iproute2 \
        nftables \
        nodejs \
        npm \
        openssl \
        python3 \
        python3-pip \
        python3-venv \
        rsync \
        sqlite3 \
        wireguard-tools
}

require_nginx() {
    if ! command -v nginx >/dev/null 2>&1; then
        printf 'Nginx is required but was not found. Install or enable the existing server Nginx before rerunning.\n' >&2
        exit 1
    fi
    install -d -m 0755 -o root -g root /etc/nginx/sites-available /etc/nginx/sites-enabled
}

require_node_version() {
    local major
    major="$(node -p "Number(process.versions.node.split('.')[0])" 2>/dev/null || true)"
    if [[ -z "$major" || "$major" -lt "$REQUIRED_NODE_MAJOR" ]]; then
        printf 'Node.js %s+ is required for the frontend build. Found: %s\n' \
            "$REQUIRED_NODE_MAJOR" "$(node --version 2>/dev/null || printf 'missing')" >&2
        printf 'Install Node.js 18+ before rerunning, or use Ubuntu 24.04+ where the OS package satisfies this.\n' >&2
        exit 1
    fi
}

create_user_and_dirs() {
    if ! getent group "$SERVICE_GROUP" >/dev/null; then
        groupadd --system "$SERVICE_GROUP"
    fi
    if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
        useradd --system --gid "$SERVICE_GROUP" --home-dir "$STATE_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
    fi

    install -d -m 0755 -o root -g root "$INSTALL_ROOT"
    install -d -m 0755 -o root -g root "$APP_DIR" "$STATIC_DIR"
    install -d -m 0750 -o root -g "$SERVICE_GROUP" "$CONFIG_DIR" "$INSTALLERS_DIR"
    install -d -m 0750 -o "$SERVICE_USER" -g "$SERVICE_GROUP" "$STATE_DIR" "$DB_DIR" "$ARTIFACTS_DIR" "$LOG_DIR"
    install -d -m 0700 -o "$SERVICE_USER" -g "$SERVICE_GROUP" "$BUILD_TMP_DIR"
    install -d -m 0700 -o root -g root "$BACKUP_DIR"
    install -d -m 0700 -o root -g root /etc/wireguard
}

install_app_source() {
    rsync -a --delete \
        --exclude '.git/' \
        --exclude '.m0-out/' \
        --exclude '.m1-out/' \
        --exclude '.m3-out/' \
        --exclude '.m4-out/' \
        --exclude '.m5-out/' \
        --exclude '.pytest_cache/' \
        --exclude '.tmp/' \
        --exclude '__pycache__/' \
        --exclude '*.pyc' \
        --exclude 'apps/frontend/node_modules/' \
        --exclude 'apps/frontend/dist/' \
        "$REPO_ROOT/" "$APP_DIR/"
}

install_python_runtime() {
    python3 -m venv "$VENV_DIR"
    "$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel
    "$VENV_DIR/bin/python" -m pip install --no-build-isolation -e "$APP_DIR"
}

build_frontend() {
    (
        cd "$APP_DIR/apps/frontend"
        if [[ -f package-lock.json ]]; then
            npm ci
        else
            npm install
        fi
        npm run build
    )
    rm -rf "$STATIC_DIR"
    install -d -m 0755 -o root -g root "$STATIC_DIR"
    cp -a "$APP_DIR/apps/frontend/dist/." "$STATIC_DIR/"
}

init_master_key() {
    if [[ ! -f "$MASTER_KEY_FILE" ]]; then
        umask 027
        openssl rand -base64 32 >"$MASTER_KEY_FILE"
    fi
    chown root:"$SERVICE_GROUP" "$MASTER_KEY_FILE"
    chmod 0640 "$MASTER_KEY_FILE"
}

init_wireguard_keys() {
    local private_key_file="$CONFIG_DIR/$WG_INTERFACE.private.key"
    local public_key_file="$CONFIG_DIR/$WG_INTERFACE.public.key"
    if [[ ! -f "$private_key_file" ]]; then
        umask 027
        wg genkey >"$private_key_file"
        wg pubkey <"$private_key_file" >"$public_key_file"
    elif [[ ! -f "$public_key_file" ]]; then
        wg pubkey <"$private_key_file" >"$public_key_file"
    fi
    chown root:"$SERVICE_GROUP" "$private_key_file" "$public_key_file"
    chmod 0640 "$private_key_file" "$public_key_file"
}

install_wireguard_msi() {
    local target="$INSTALLERS_DIR/$WIREGUARD_MSI_FILE_NAME"
    local tmp
    tmp="$(mktemp)"
    if [[ "$WIREGUARD_MSI_SOURCE" =~ ^https?:// ]]; then
        curl -fsSL "$WIREGUARD_MSI_SOURCE" -o "$tmp"
    else
        cp "$WIREGUARD_MSI_SOURCE" "$tmp"
    fi
    local actual
    actual="$(sha256sum "$tmp" | awk '{print toupper($1)}')"
    if [[ "$actual" != "$WIREGUARD_MSI_SHA256" ]]; then
        rm -f "$tmp"
        printf 'WireGuard MSI SHA256 mismatch. expected=%s actual=%s\n' "$WIREGUARD_MSI_SHA256" "$actual" >&2
        exit 1
    fi
    install -m 0640 -o root -g "$SERVICE_GROUP" "$tmp" "$target"
    rm -f "$tmp"
}

wireguard_address() {
    VPN_CIDR="$VPN_CIDR" VPN_SERVER_IP="$VPN_SERVER_IP" python3 - <<'PY'
import ipaddress
import os

network = ipaddress.ip_network(os.environ["VPN_CIDR"], strict=False)
print(f'{os.environ["VPN_SERVER_IP"]}/{network.prefixlen}')
PY
}

write_env_file() {
    local server_public_key
    server_public_key="$(tr -d '\n' <"$CONFIG_DIR/$WG_INTERFACE.public.key")"
    if [[ -z "$SESSION_COOKIE_SECURE" ]]; then
        case "$PUBLIC_BASE_URL" in
            https://*) SESSION_COOKIE_SECURE=true ;;
            *) SESSION_COOKIE_SECURE=false ;;
        esac
    fi
    if [[ -f "$ENV_FILE" ]]; then
        log "Preserving existing $ENV_FILE"
        return
    fi
    umask 027
    cat >"$ENV_FILE" <<EOF
PYTHONPATH=$APP_DIR/packages/python/yourvpn-core/src:$APP_DIR/apps/api/src:$APP_DIR/apps/worker/src:$APP_DIR/apps/wg-agent/src
YOURVPN_APP_NAME=WirePortal
YOURVPN_ENVIRONMENT=production
YOURVPN_LOG_LEVEL=INFO
YOURVPN_DATABASE_URL=sqlite:///$DB_DIR/wireportal.sqlite3
YOURVPN_PUBLIC_BASE_URL=$PUBLIC_BASE_URL
YOURVPN_WG_AGENT_SOCKET_PATH=/run/yourvpn/wg-agent.sock
YOURVPN_ARTIFACTS_DIR=$ARTIFACTS_DIR
YOURVPN_BUILD_TMP_DIR=$BUILD_TMP_DIR
YOURVPN_SESSION_COOKIE_NAME=wireportal_session
YOURVPN_SESSION_COOKIE_SECURE=$SESSION_COOKIE_SECURE
YOURVPN_SESSION_TTL_MINUTES=480
YOURVPN_CSRF_HEADER_NAME=x-csrf-token
YOURVPN_LOGIN_RATE_LIMIT_ATTEMPTS=5
YOURVPN_LOGIN_RATE_LIMIT_WINDOW_MINUTES=15
YOURVPN_ADMIN_IP_WHITELIST=$ADMIN_IP_WHITELIST
YOURVPN_PASSWORD_SETUP_TOKEN_TTL_HOURS=72
YOURVPN_SMTP_HOST=
YOURVPN_SMTP_PORT=25
YOURVPN_SMTP_FROM=
YOURVPN_SMTP_USERNAME=
YOURVPN_SMTP_PASSWORD=
YOURVPN_SMTP_USE_TLS=false
YOURVPN_SMTP_TIMEOUT_SECONDS=10
YOURVPN_VPN_CIDR=$VPN_CIDR
YOURVPN_VPN_SERVER_IP=$VPN_SERVER_IP
YOURVPN_INSTALL_PACKAGE_DOWNLOAD_WINDOW_MINUTES=120
YOURVPN_INSTALL_PACKAGE_MAX_DOWNLOAD_ATTEMPTS=5
YOURVPN_FAKE_BUILDER_ENABLED=false
YOURVPN_INSTALLER_BUILDER_MODE=self_pack
YOURVPN_WIREGUARD_MSI_PATH=$INSTALLERS_DIR/$WIREGUARD_MSI_FILE_NAME
YOURVPN_WIREGUARD_MSI_SHA256=$WIREGUARD_MSI_SHA256
YOURVPN_WIREGUARD_INSTALLER_VERSION=1.1
YOURVPN_WIREGUARD_SERVER_PUBLIC_KEY=$server_public_key
YOURVPN_WIREGUARD_ENDPOINT=$WIREGUARD_ENDPOINT
YOURVPN_WIREGUARD_PERSISTENT_KEEPALIVE_SECONDS=25
YOURVPN_WIREGUARD_TUNNEL_NAME_PREFIX=WirePortal
YOURVPN_WG_INTERFACE=$WG_INTERFACE
YOURVPN_NFT_TABLE_NAME=yourvpn
YOURVPN_OUTBOUND_INTERFACE=$OUTBOUND_INTERFACE
YOURVPN_ENABLE_MASQUERADE=true
YOURVPN_WG_AGENT_DRY_RUN=false
YOURVPN_MASTER_KEY_FILE=$MASTER_KEY_FILE
EOF
    chown root:"$SERVICE_GROUP" "$ENV_FILE"
    chmod 0640 "$ENV_FILE"
}

init_database() {
    set -a
    # shellcheck disable=SC1090
    . "$ENV_FILE"
    set +a
    runuser -u "$SERVICE_USER" -- env \
        PYTHONPATH="$PYTHONPATH" \
        YOURVPN_DATABASE_URL="$YOURVPN_DATABASE_URL" \
        "$VENV_DIR/bin/python" -m alembic -c "$APP_DIR/alembic.ini" upgrade head
}

init_wg0() {
    local wg_conf="/etc/wireguard/$WG_INTERFACE.conf"
    local private_key
    private_key="$(tr -d '\n' <"$CONFIG_DIR/$WG_INTERFACE.private.key")"
    if [[ ! -f "$wg_conf" ]]; then
        cat >"$wg_conf" <<EOF
[Interface]
Address = $(wireguard_address)
ListenPort = $WIREGUARD_LISTEN_PORT
PrivateKey = $private_key
EOF
        chmod 0600 "$wg_conf"
    fi
    cat >/etc/sysctl.d/99-yourvpn.conf <<EOF
net.ipv4.ip_forward = 1
EOF
    sysctl --system >/dev/null
    if [[ "$ENABLE_WG_QUICK" == "true" ]]; then
        systemctl enable --now "wg-quick@$WG_INTERFACE.service"
    fi
}

install_systemd_units() {
    install -m 0644 "$APP_DIR/deploy/systemd/wireportal-api.service" /etc/systemd/system/wireportal-api.service
    install -m 0644 "$APP_DIR/deploy/systemd/wireportal-worker.service" /etc/systemd/system/wireportal-worker.service
    install -m 0644 "$APP_DIR/deploy/systemd/wireportal-wg-agent.service" /etc/systemd/system/wireportal-wg-agent.service
    systemctl daemon-reload
}

install_nginx_config() {
    require_nginx
    local target=/etc/nginx/sites-available/wireportal.conf
    sed \
        -e "s#__SERVER_NAME__#$SERVER_NAME#g" \
        -e "s#__STATIC_ROOT__#$STATIC_DIR#g" \
        "$APP_DIR/deploy/nginx/wireportal.conf" >"$target"
    ln -sfn "$target" /etc/nginx/sites-enabled/wireportal.conf
    rm -f /etc/nginx/sites-enabled/default
    nginx -t
}

enable_services() {
    if [[ "$ENABLE_SYSTEMD" != "true" ]]; then
        return
    fi
    systemctl enable --now wireportal-wg-agent.service
    systemctl enable --now wireportal-worker.service
    systemctl enable --now wireportal-api.service
    systemctl reload nginx || systemctl restart nginx
}

main() {
    require_root
    require_debian_like
    log "Installing packages"
    install_packages
    log "Checking Node.js version"
    require_node_version
    log "Creating user and directories"
    create_user_and_dirs
    log "Installing application source"
    install_app_source
    log "Installing Python runtime"
    install_python_runtime
    log "Building frontend"
    build_frontend
    log "Initializing master key and WireGuard keys"
    init_master_key
    init_wireguard_keys
    log "Installing fixed WireGuard Windows MSI"
    install_wireguard_msi
    log "Writing environment file"
    write_env_file
    log "Initializing database"
    init_database
    log "Initializing $WG_INTERFACE"
    init_wg0
    log "Installing systemd and nginx configuration"
    install_systemd_units
    install_nginx_config
    enable_services
    log "Done. Open $PUBLIC_BASE_URL/setup or $PUBLIC_BASE_URL"
}

main "$@"
