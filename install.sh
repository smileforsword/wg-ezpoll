#!/usr/bin/env bash
set -Eeuo pipefail

INSTALL_ROOT="${INSTALL_ROOT:-/opt/yourvpn}"
CHECKOUT_DIR="${CHECKOUT_DIR:-$INSTALL_ROOT/source}"
REPO_URL="${REPO_URL:-}"
REPO_REF="${REPO_REF:-main}"
WIREGUARD_LISTEN_PORT="${WIREGUARD_LISTEN_PORT:-51820}"
WIREPORTAL_INTERACTIVE_CONFIG="${WIREPORTAL_INTERACTIVE_CONFIG:-true}"
RESOLVED_REPO_ROOT=""

log() {
    printf '[wireportal-bootstrap] %s\n' "$*" >&2
}

script_dir() {
    local source_path="${BASH_SOURCE[0]-}"
    if [[ -z "$source_path" || ! -f "$source_path" ]]; then
        return
    fi
    cd "$(dirname "$source_path")" && pwd
}

require_root() {
    if [[ "${EUID}" -ne 0 ]]; then
        printf 'Run this installer as root, for example with sudo.\n' >&2
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

ensure_git() {
    if command -v git >/dev/null 2>&1; then
        return
    fi
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y ca-certificates curl git
}

detect_public_ip() {
    if ! command -v curl >/dev/null 2>&1; then
        return
    fi

    local ip
    for url in https://api.ipify.org https://ifconfig.me/ip; do
        ip="$(curl -fsSL --max-time 5 "$url" 2>/dev/null || true)"
        if [[ "$ip" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ || "$ip" =~ : ]]; then
            printf '%s\n' "$ip"
            return
        fi
    done
}

ssh_admin_cidr() {
    local source_ip="${SSH_CLIENT%% *}"
    if [[ -z "$source_ip" ]]; then
        return
    fi
    if [[ "$source_ip" == *:* ]]; then
        printf '%s/128\n' "$source_ip"
    else
        printf '%s/32\n' "$source_ip"
    fi
}

prompt_value() {
    local name="$1"
    local label="$2"
    local default_value="$3"
    local current_value="${!name:-}"
    local reply

    if [[ -n "$current_value" ]]; then
        export "$name=$current_value"
        return
    fi

    if [[ "$WIREPORTAL_INTERACTIVE_CONFIG" != "true" || ! -r /dev/tty || ! -w /dev/tty ]]; then
        export "$name=$default_value"
        return
    fi

    if [[ -n "$default_value" ]]; then
        printf '%s [%s]: ' "$label" "$default_value" >/dev/tty
    else
        printf '%s: ' "$label" >/dev/tty
    fi
    IFS= read -r reply </dev/tty
    export "$name=${reply:-$default_value}"
}

configure_install_environment() {
    local public_ip
    public_ip="$(detect_public_ip || true)"

    local default_server_name="${SERVER_NAME:-${public_ip:-$(hostname -f 2>/dev/null || hostname)}}"
    prompt_value SERVER_NAME "Public domain or server public IP" "$default_server_name"

    local default_base_url="${PUBLIC_BASE_URL:-http://$SERVER_NAME}"
    prompt_value PUBLIC_BASE_URL "Public Web base URL" "$default_base_url"

    local default_endpoint="${WIREGUARD_ENDPOINT:-$SERVER_NAME:$WIREGUARD_LISTEN_PORT}"
    prompt_value WIREGUARD_ENDPOINT "WireGuard public endpoint" "$default_endpoint"

    local default_admin_whitelist="${ADMIN_IP_WHITELIST:-$(ssh_admin_cidr || true)}"
    prompt_value ADMIN_IP_WHITELIST "Admin IP whitelist CIDR, for example 203.0.113.10/32" "$default_admin_whitelist"
}

resolve_repo_root() {
    local local_script_dir
    local_script_dir="$(script_dir || true)"
    if [[ -n "$local_script_dir" && -f "$local_script_dir/deploy/install/install-ubuntu-debian.sh" ]]; then
        RESOLVED_REPO_ROOT="$local_script_dir"
        return
    fi
    if [[ -z "$REPO_URL" ]]; then
        printf 'REPO_URL is required when install.sh is not run from a repository checkout.\n' >&2
        printf 'Example: curl -fsSL https://raw.githubusercontent.com/OWNER/REPO/main/install.sh | sudo env REPO_URL=https://github.com/OWNER/REPO.git bash\n' >&2
        exit 1
    fi
    ensure_git
    if [[ -d "$CHECKOUT_DIR/.git" ]]; then
        log "Updating existing checkout at $CHECKOUT_DIR"
        git -C "$CHECKOUT_DIR" fetch origin "$REPO_REF" >&2
        git -C "$CHECKOUT_DIR" checkout "$REPO_REF" >&2
        git -C "$CHECKOUT_DIR" pull --ff-only origin "$REPO_REF" >&2
    else
        log "Cloning $REPO_URL into $CHECKOUT_DIR"
        install -d -m 0755 -o root -g root "$(dirname "$CHECKOUT_DIR")"
        git clone --branch "$REPO_REF" "$REPO_URL" "$CHECKOUT_DIR" >&2
    fi
    RESOLVED_REPO_ROOT="$CHECKOUT_DIR"
}

main() {
    require_root
    require_debian_like
    resolve_repo_root
    configure_install_environment
    log "Running Ubuntu/Debian installer from $RESOLVED_REPO_ROOT"
    bash "$RESOLVED_REPO_ROOT/deploy/install/install-ubuntu-debian.sh"
}

main "$@"
