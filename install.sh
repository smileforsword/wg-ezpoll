#!/usr/bin/env bash
set -Eeuo pipefail

INSTALL_ROOT="${INSTALL_ROOT:-/opt/yourvpn}"
CHECKOUT_DIR="${CHECKOUT_DIR:-$INSTALL_ROOT/source}"
REPO_URL="${REPO_URL:-}"
REPO_REF="${REPO_REF:-main}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log() {
    printf '[wireportal-bootstrap] %s\n' "$*"
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
    apt-get install -y ca-certificates git
}

resolve_repo_root() {
    if [[ -f "$SCRIPT_DIR/deploy/install/install-ubuntu-debian.sh" ]]; then
        printf '%s\n' "$SCRIPT_DIR"
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
        git -C "$CHECKOUT_DIR" fetch origin "$REPO_REF"
        git -C "$CHECKOUT_DIR" checkout "$REPO_REF"
        git -C "$CHECKOUT_DIR" pull --ff-only origin "$REPO_REF"
    else
        log "Cloning $REPO_URL into $CHECKOUT_DIR"
        install -d -m 0755 -o root -g root "$(dirname "$CHECKOUT_DIR")"
        git clone --branch "$REPO_REF" "$REPO_URL" "$CHECKOUT_DIR"
    fi
    printf '%s\n' "$CHECKOUT_DIR"
}

main() {
    require_root
    require_debian_like
    local repo_root
    repo_root="$(resolve_repo_root)"
    log "Running Ubuntu/Debian installer from $repo_root"
    bash "$repo_root/deploy/install/install-ubuntu-debian.sh"
}

main "$@"
