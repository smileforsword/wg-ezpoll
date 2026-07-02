#!/usr/bin/env bash
set -Eeuo pipefail

ENV_FILE="${ENV_FILE:-/etc/yourvpn/yourvpn.env}"
APP_DIR="${APP_DIR:-/opt/yourvpn/app}"
VENV_DIR="${VENV_DIR:-/opt/yourvpn/venv}"
SERVICE_USER="${SERVICE_USER:-yourvpn}"
SERVICE_GROUP="${SERVICE_GROUP:-yourvpn}"

if [[ "${EUID}" -ne 0 ]]; then
    printf 'Run restore as root.\n' >&2
    exit 1
fi

archive="${1:-}"
if [[ -z "$archive" || ! -f "$archive" ]]; then
    printf 'Usage: %s /var/backups/yourvpn/wireportal-YYYYMMDDTHHMMSSZ.tar.gz\n' "$0" >&2
    exit 1
fi

stage="$(mktemp -d)"
cleanup() {
    rm -rf "$stage"
}
trap cleanup EXIT

systemctl stop wireportal-api.service wireportal-worker.service wireportal-wg-agent.service || true

tar -xzf "$archive" -C "$stage"

install -d -m 0750 -o root -g "$SERVICE_GROUP" /etc/yourvpn /var/lib/yourvpn/installers
install -d -m 0750 -o "$SERVICE_USER" -g "$SERVICE_GROUP" /var/lib/yourvpn/db
install -d -m 0700 -o root -g root /etc/wireguard

rsync -a "$stage/etc/yourvpn/" /etc/yourvpn/
rsync -a "$stage/var/lib/yourvpn/installers/" /var/lib/yourvpn/installers/
rsync -a "$stage/etc/wireguard/" /etc/wireguard/
install -m 0640 -o "$SERVICE_USER" -g "$SERVICE_GROUP" \
    "$stage/var/lib/yourvpn/db/wireportal.sqlite3" \
    /var/lib/yourvpn/db/wireportal.sqlite3

chown -R root:"$SERVICE_GROUP" /etc/yourvpn /var/lib/yourvpn/installers
chown -R "$SERVICE_USER":"$SERVICE_GROUP" /var/lib/yourvpn/db
chmod 0640 /etc/yourvpn/yourvpn.env /etc/yourvpn/master.key || true
chmod 0600 /etc/wireguard/*.conf || true

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

runuser -u "$SERVICE_USER" -- env \
    PYTHONPATH="$PYTHONPATH" \
    YOURVPN_DATABASE_URL="$YOURVPN_DATABASE_URL" \
    "$VENV_DIR/bin/python" -m alembic -c "$APP_DIR/alembic.ini" upgrade head

systemctl restart "wg-quick@${YOURVPN_WG_INTERFACE:-wg0}.service" || true
systemctl start wireportal-wg-agent.service
systemctl start wireportal-worker.service
systemctl start wireportal-api.service

"$APP_DIR/deploy/ops/reconcile.sh"
