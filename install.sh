#!/usr/bin/env bash
set -Eeuo pipefail

INSTALL_ROOT="${INSTALL_ROOT:-/opt/yourvpn}"
CHECKOUT_DIR="${CHECKOUT_DIR:-$INSTALL_ROOT/source}"
REPO_URL="${REPO_URL:-}"
REPO_REF="${REPO_REF:-main}"
BOOTSTRAP_GIT_TIMEOUT_SECONDS="${BOOTSTRAP_GIT_TIMEOUT_SECONDS:-20}"
BOOTSTRAP_CONNECT_TIMEOUT_SECONDS="${BOOTSTRAP_CONNECT_TIMEOUT_SECONDS:-5}"
NGINX_LISTEN_PORT="${NGINX_LISTEN_PORT:-80}"
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

timed_git() {
    GIT_TERMINAL_PROMPT=0 GIT_ASKPASS=/bin/false timeout --foreground "$BOOTSTRAP_GIT_TIMEOUT_SECONDS" git "$@"
}

github_slug() {
    local url="$REPO_URL"
    url="${url%.git}"

    case "$url" in
        https://github.com/*) url="${url#https://github.com/}" ;;
        http://github.com/*) url="${url#http://github.com/}" ;;
        git@github.com:*) url="${url#git@github.com:}" ;;
        ssh://git@github.com/*) url="${url#ssh://git@github.com/}" ;;
        *) return 1 ;;
    esac

    local owner="${url%%/*}"
    local rest="${url#*/}"
    local repo="${rest%%/*}"
    if [[ -z "$owner" || -z "$repo" || "$owner" == "$rest" ]]; then
        return 1
    fi
    printf '%s/%s\n' "$owner" "$repo"
}

replace_checkout_from_dir() {
    local source_dir="$1"
    local parent_dir
    local staging_dir
    local backup_dir

    parent_dir="$(dirname "$CHECKOUT_DIR")"
    staging_dir="$parent_dir/.source-staging.$$"
    backup_dir="$parent_dir/.source-previous.$$"

    rm -rf "$staging_dir"
    mv "$source_dir" "$staging_dir"
    if [[ -e "$CHECKOUT_DIR" ]]; then
        mv "$CHECKOUT_DIR" "$backup_dir"
    fi
    if ! mv "$staging_dir" "$CHECKOUT_DIR"; then
        if [[ -e "$backup_dir" ]]; then
            mv "$backup_dir" "$CHECKOUT_DIR"
        fi
        return 1
    fi
    rm -rf "$backup_dir"
}

download_repo_archive() {
    local slug
    slug="$(github_slug || true)"
    if [[ -z "$slug" ]]; then
        return 1
    fi
    if ! command -v curl >/dev/null 2>&1 || ! command -v tar >/dev/null 2>&1; then
        return 1
    fi

    local tmp_dir
    local tmp_tar
    local archive_ref
    local archive_url
    local archive_urls
    local unpacked_dir
    tmp_dir="$(mktemp -d)"
    tmp_tar="$tmp_dir/source.tar.gz"

    for archive_ref in "refs/heads/$REPO_REF" "refs/tags/$REPO_REF" "$REPO_REF"; do
        archive_urls=(
            "https://github.com/$slug/archive/$archive_ref.tar.gz"
            "https://codeload.github.com/$slug/tar.gz/$archive_ref"
        )
        for archive_url in "${archive_urls[@]}"; do
            find "$tmp_dir" -mindepth 1 -maxdepth 1 -type d -exec rm -rf {} + 2>/dev/null || true
            log "Downloading source archive $archive_url"
            if ! curl -fsSL --connect-timeout "$BOOTSTRAP_CONNECT_TIMEOUT_SECONDS" --speed-time "$BOOTSTRAP_GIT_TIMEOUT_SECONDS" --speed-limit 1 --max-time "$BOOTSTRAP_GIT_TIMEOUT_SECONDS" "$archive_url" -o "$tmp_tar"; then
                continue
            fi
            if ! tar -xzf "$tmp_tar" -C "$tmp_dir"; then
                continue
            fi
            unpacked_dir="$(find "$tmp_dir" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
            if [[ -n "$unpacked_dir" && -f "$unpacked_dir/deploy/install/install-ubuntu-debian.sh" ]]; then
                install -d -m 0755 -o root -g root "$(dirname "$CHECKOUT_DIR")"
                if replace_checkout_from_dir "$unpacked_dir"; then
                    rm -rf "$tmp_dir"
                    return 0
                fi
            fi
        done
    done

    rm -rf "$tmp_dir"
    return 1
}

sync_repo_with_git_or_archive() {
    if [[ -d "$CHECKOUT_DIR/.git" ]]; then
        log "Updating existing checkout at $CHECKOUT_DIR"
        local git_update_ok=true
        log "Fetching origin $REPO_REF with ${BOOTSTRAP_GIT_TIMEOUT_SECONDS}s timeout"
        if ! timed_git -C "$CHECKOUT_DIR" fetch origin "$REPO_REF" >&2; then
            git_update_ok=false
        fi
        if [[ "$git_update_ok" == "true" ]]; then
            log "Checking out $REPO_REF"
            if ! timed_git -C "$CHECKOUT_DIR" checkout "$REPO_REF" >&2; then
                git_update_ok=false
            fi
        fi
        if [[ "$git_update_ok" == "true" ]]; then
            log "Fast-forwarding to origin/$REPO_REF"
            if ! timed_git -C "$CHECKOUT_DIR" merge --ff-only "origin/$REPO_REF" >&2; then
                git_update_ok=false
            fi
        fi
        if [[ "$git_update_ok" != "true" ]]; then
            log "Git update did not complete; trying GitHub source archive fallback"
            download_repo_archive
        fi
        return
    fi

    if [[ -e "$CHECKOUT_DIR" ]]; then
        log "Refreshing existing source directory at $CHECKOUT_DIR from GitHub source archive"
        download_repo_archive
        return
    fi

    log "Cloning $REPO_URL into $CHECKOUT_DIR"
    install -d -m 0755 -o root -g root "$(dirname "$CHECKOUT_DIR")"
    if ! timed_git clone --branch "$REPO_REF" "$REPO_URL" "$CHECKOUT_DIR" >&2; then
        log "Git clone did not complete; trying GitHub source archive fallback"
        download_repo_archive
    fi
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

    local default_base_url="http://$SERVER_NAME"
    if [[ "$NGINX_LISTEN_PORT" != "80" ]]; then
        default_base_url="http://$SERVER_NAME:$NGINX_LISTEN_PORT"
    fi
    default_base_url="${PUBLIC_BASE_URL:-$default_base_url}"
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
    if ! sync_repo_with_git_or_archive; then
        printf 'Unable to prepare source checkout from %s (%s). Check GitHub connectivity or set CHECKOUT_DIR to an existing checkout.\n' "$REPO_URL" "$REPO_REF" >&2
        exit 1
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
