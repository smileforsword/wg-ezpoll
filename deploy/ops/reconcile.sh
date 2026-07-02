#!/usr/bin/env bash
set -Eeuo pipefail

ENV_FILE="${ENV_FILE:-/etc/yourvpn/yourvpn.env}"
APP_DIR="${APP_DIR:-/opt/yourvpn/app}"
VENV_DIR="${VENV_DIR:-/opt/yourvpn/venv}"
SERVICE_USER="${SERVICE_USER:-yourvpn}"

if [[ ! -r "$ENV_FILE" ]]; then
    printf 'Missing env file: %s\n' "$ENV_FILE" >&2
    exit 1
fi

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

runuser -u "$SERVICE_USER" -- env \
    PYTHONPATH="$PYTHONPATH" \
    YOURVPN_DATABASE_URL="$YOURVPN_DATABASE_URL" \
    YOURVPN_WG_AGENT_SOCKET_PATH="$YOURVPN_WG_AGENT_SOCKET_PATH" \
    YOURVPN_WG_INTERFACE="$YOURVPN_WG_INTERFACE" \
    YOURVPN_NFT_TABLE_NAME="$YOURVPN_NFT_TABLE_NAME" \
    YOURVPN_OUTBOUND_INTERFACE="$YOURVPN_OUTBOUND_INTERFACE" \
    YOURVPN_ENABLE_MASQUERADE="$YOURVPN_ENABLE_MASQUERADE" \
    "$VENV_DIR/bin/python" - <<'PY'
from yourvpn_core.config import AppSettings
from yourvpn_core.db.session import create_db_engine, create_session_factory
from yourvpn_core.modules.wg_runtime import WgRuntimeModule

settings = AppSettings()
engine = create_db_engine(settings.database_url)
session_factory = create_session_factory(engine)

with session_factory() as db:
    result = WgRuntimeModule().reconcile(db, settings=settings)
    db.commit()
    print(result)
PY
