#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="/opt/dpslogger"
BIN_DIR="/usr/local/bin"

usage() {
    cat <<EOF
Usage:
  sudo ./uninstall.sh [--install-dir /opt/dpslogger] [--bin-dir /usr/local/bin] [--yes]

Options:
  --install-dir PATH  Installation directory
  --bin-dir PATH      Directory containing command wrappers
  --yes               Remove without confirmation
  -h, --help          Show this help
EOF
}

log() {
    printf '[INFO] %s\n' "$*"
}

die() {
    printf '[ERROR] %s\n' "$*" >&2
    exit 1
}

require_root() {
    if [[ "${EUID}" -ne 0 ]]; then
        die "This script must be run as root."
    fi
}

CONFIRM="0"

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --install-dir)
                [[ $# -ge 2 ]] || die "Missing value for --install-dir"
                INSTALL_DIR="$2"
                shift 2
                ;;
            --bin-dir)
                [[ $# -ge 2 ]] || die "Missing value for --bin-dir"
                BIN_DIR="$2"
                shift 2
                ;;
            --yes)
                CONFIRM="1"
                shift
                ;;
            -h|--help)
                usage
                exit 0
                ;;
            *)
                die "Unknown argument: $1"
                ;;
        esac
    done
}

confirm_uninstall() {
    if [[ "${CONFIRM}" = "1" ]]; then
        return
    fi

    cat <<EOF
This will remove:

  ${INSTALL_DIR}
  ${BIN_DIR}/dps-logger
  ${BIN_DIR}/dps-term
  ${BIN_DIR}/dps-scan
  ${BIN_DIR}/dps-read
  ${BIN_DIR}/dps-set-address
  ${BIN_DIR}/dps-plot
  ${BIN_DIR}/dps-port-check
  ${BIN_DIR}/dps-loopback-test
  ${BIN_DIR}/dps-setup-udev
  ${BIN_DIR}/dps-serial-debug

Measurement data created by users will NOT be removed.

Continue? [y/N]
EOF

    read -r reply
    case "${reply}" in
        y|Y|yes|YES)
            ;;
        *)
            echo "Aborted."
            exit 0
            ;;
    esac
}

remove_wrapper() {
    local wrapper="$1"
    if [[ -e "${wrapper}" || -L "${wrapper}" ]]; then
        log "Removing ${wrapper}"
        rm -f "${wrapper}"
    fi
}

remove_wrappers() {
    remove_wrapper "${BIN_DIR}/dps-logger"
    remove_wrapper "${BIN_DIR}/dps-term"
    remove_wrapper "${BIN_DIR}/dps-scan"
    remove_wrapper "${BIN_DIR}/dps-read"
    remove_wrapper "${BIN_DIR}/dps-set-address"
    remove_wrapper "${BIN_DIR}/dps-plot"
    remove_wrapper "${BIN_DIR}/dps-port-check"
    remove_wrapper "${BIN_DIR}/dps-loopback-test"
    remove_wrapper "${BIN_DIR}/dps-setup-udev"
    remove_wrapper "${BIN_DIR}/dps-serial-debug"
}

remove_install_dir() {
    if [[ -d "${INSTALL_DIR}" ]]; then
        log "Removing ${INSTALL_DIR}"
        rm -rf "${INSTALL_DIR}"
    else
        log "Install directory not found: ${INSTALL_DIR}"
    fi
}

print_summary() {
    cat <<EOF

Uninstall complete.

Removed:
  ${INSTALL_DIR}
  ${BIN_DIR}/dps-logger
  ${BIN_DIR}/dps-term
  ${BIN_DIR}/dps-scan
  ${BIN_DIR}/dps-read
  ${BIN_DIR}/dps-set-address
  ${BIN_DIR}/dps-plot
  ${BIN_DIR}/dps-port-check
  ${BIN_DIR}/dps-loopback-test
  ${BIN_DIR}/dps-setup-udev
  ${BIN_DIR}/dps-serial-debug

Not removed:
  - User-owned measurement data
  - User-created CSV, PNG, and stats files
EOF
}

main() {
    parse_args "$@"
    require_root
    confirm_uninstall
    remove_wrappers
    remove_install_dir
    print_summary
}

main "$@"
