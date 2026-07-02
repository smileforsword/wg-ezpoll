#!/usr/bin/env bash
set -Eeuo pipefail

ENV_FILE="${ENV_FILE:-/etc/yourvpn/yourvpn.env}"
BACKUP_ROOT="${BACKUP_ROOT:-/var/backups/yourvpn}"
APP_DIR="${APP_DIR:-/opt/yourvpn/app}"
VENV_DIR="${VENV_DIR:-/opt/yourvpn/venv}"

if [[ "${EUID}" -ne 0 ]]; then
    printf 'Run backup as root.\n' >&2
    exit 1
fi

if [[ ! -r "$ENV_FILE" ]]; then
    printf 'Missing env file: %s\n' "$ENV_FILE" >&2
    exit 1
fi

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
stage="$(mktemp -d)"
archive="$BACKUP_ROOT/wireportal-$timestamp.tar.gz"
mkdir -p "$BACKUP_ROOT"

cleanup() {
    rm -rf "$stage"
}
trap cleanup EXIT

mkdir -p "$stage/etc" "$stage/var/lib/yourvpn/db" "$stage/var/lib/yourvpn/installers" "$stage/etc/wireguard"
rsync -a /etc/yourvpn/ "$stage/etc/yourvpn/"
if [[ -d /var/lib/yourvpn/installers ]]; then
    rsync -a /var/lib/yourvpn/installers/ "$stage/var/lib/yourvpn/installers/"
fi
if [[ -d /etc/wireguard ]]; then
    rsync -a /etc/wireguard/ "$stage/etc/wireguard/"
fi

db_path="$("$VENV_DIR/bin/python" - <<'PY'
import os
from urllib.parse import unquote, urlparse

url = os.environ["YOURVPN_DATABASE_URL"]
if not url.startswith("sqlite:///"):
    raise SystemExit("Only SQLite online backup is implemented by this script. Dump MySQL separately.")
parsed = urlparse(url)
print(unquote(parsed.path))
PY
)"

sqlite3 "$db_path" ".backup '$stage/var/lib/yourvpn/db/wireportal.sqlite3'"

cat >"$stage/backup-manifest.txt" <<EOF
created_at=$timestamp
database=sqlite
artifacts_included=false
build_tmp_included=false
EOF

tar -C "$stage" -czf "$archive" .
sha256sum "$archive" >"$archive.sha256"
chmod 0600 "$archive" "$archive.sha256"
printf '%s\n' "$archive"
