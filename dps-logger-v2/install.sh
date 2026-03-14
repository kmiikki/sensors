#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="/opt/dpslogger"
BIN_DIR="/usr/local/bin"
PYTHON_BIN=""
VERSION="2.0"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="${SCRIPT_DIR}/dpslogger"
DOCS_DIR="${SCRIPT_DIR}/docs"

usage() {
    cat <<EOF
Usage:
  sudo ./install.sh [--python /path/to/python3] [--install-dir /opt/dpslogger] [--bin-dir /usr/local/bin]

Options:
  --python PATH       Python interpreter to use
  --install-dir PATH  Installation directory
  --bin-dir PATH      Directory for command wrappers
  -h, --help          Show this help
EOF
}

log() {
    printf '[INFO] %s\n' "$*"
}

warn() {
    printf '[WARN] %s\n' "$*" >&2
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

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --python)
                [[ $# -ge 2 ]] || die "Missing value for --python"
                PYTHON_BIN="$2"
                shift 2
                ;;
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

detect_python() {
    if [[ -n "${PYTHON_BIN}" ]]; then
        return
    fi

    if command -v python3 >/dev/null 2>&1; then
        PYTHON_BIN="$(command -v python3)"
        return
    fi

    die "Could not locate python3. Use --python to specify interpreter."
}

check_layout() {
    [[ -d "${SOURCE_DIR}" ]] || die "Expected source directory next to install.sh: ${SOURCE_DIR}"
}

check_source_tree() {
    [[ -f "${SOURCE_DIR}/__init__.py" ]] || die "Missing ${SOURCE_DIR}/__init__.py"
    [[ -d "${SOURCE_DIR}/cli" ]] || die "Missing ${SOURCE_DIR}/cli"
    [[ -d "${SOURCE_DIR}/tools" ]] || die "Missing ${SOURCE_DIR}/tools"

    [[ -f "${SOURCE_DIR}/cli/dps_bus_logger.py" ]] || die "Missing dps_bus_logger.py"
    [[ -f "${SOURCE_DIR}/cli/dps_term.py" ]] || die "Missing dps_term.py"
    [[ -f "${SOURCE_DIR}/cli/dps_address_scan.py" ]] || die "Missing dps_address_scan.py"
    [[ -f "${SOURCE_DIR}/cli/dps_read.py" ]] || die "Missing dps_read.py"
    [[ -f "${SOURCE_DIR}/cli/dps_set_address.py" ]] || die "Missing dps_set_address.py"
    [[ -f "${SOURCE_DIR}/cli/dps_plot_csv.py" ]] || die "Missing dps_plot_csv.py"

    [[ -f "${SOURCE_DIR}/tools/port_check.py" ]] || die "Missing port_check.py"
    [[ -f "${SOURCE_DIR}/tools/loopback_test.py" ]] || die "Missing loopback_test.py"
    [[ -f "${SOURCE_DIR}/tools/setup_udev.py" ]] || die "Missing setup_udev.py"
}

check_python() {
    [[ -x "${PYTHON_BIN}" ]] || die "Python interpreter not executable: ${PYTHON_BIN}"

    log "Using Python interpreter: ${PYTHON_BIN}"
    "${PYTHON_BIN}" --version || die "Failed to run Python"

    "${PYTHON_BIN}" -c "import serial" \
        || die "Python environment is missing required module: pyserial.
If you are using a virtual environment, run:
  sudo ./install.sh --python \$(which python3)"

    "${PYTHON_BIN}" -c "import matplotlib, numpy, pandas" \
        || die "Python environment is missing one or more required modules: matplotlib, numpy, pandas.
If you are using a virtual environment, run:
  sudo ./install.sh --python \$(which python3)"
}

prepare_install_tree() {
    log "Creating installation directories"
    mkdir -p "${INSTALL_DIR}"
    mkdir -p "${INSTALL_DIR}/install"
    mkdir -p "${INSTALL_DIR}/docs"
    mkdir -p "${BIN_DIR}"
}

install_package() {
    log "Installing package to ${INSTALL_DIR}/dpslogger"

    rm -rf "${INSTALL_DIR}/dpslogger"
    mkdir -p "${INSTALL_DIR}/dpslogger"

    cp -a "${SOURCE_DIR}/." "${INSTALL_DIR}/dpslogger/"

    rm -rf "${INSTALL_DIR}/dpslogger/tests"
    find "${INSTALL_DIR}/dpslogger" -type d -name "__pycache__" -prune -exec rm -rf {} +
    find "${INSTALL_DIR}/dpslogger" -type f -name "*.pyc" -delete
    find "${INSTALL_DIR}/dpslogger" -type f -name "*.old.py" -delete
}

install_docs() {
    if [[ -d "${DOCS_DIR}" ]]; then
        log "Installing documentation"
        rm -rf "${INSTALL_DIR}/docs"
        mkdir -p "${INSTALL_DIR}/docs"
        cp -a "${DOCS_DIR}/." "${INSTALL_DIR}/docs/"
    else
        warn "No docs directory found at ${DOCS_DIR}; skipping docs install"
    fi
}

write_version_file() {
    log "Writing VERSION file"
    printf '%s\n' "${VERSION}" > "${INSTALL_DIR}/VERSION"
}

write_config() {
    local config_file="${INSTALL_DIR}/install/dpslogger.conf"

    log "Writing config file: ${config_file}"
    cat > "${config_file}" <<EOF
PYTHON_BIN=${PYTHON_BIN}
INSTALL_DIR=${INSTALL_DIR}
VERSION=${VERSION}
EOF

    chmod 644 "${config_file}"
}

write_wrapper() {
    local wrapper_path="$1"
    local module_name="$2"
    local tmp_file

    tmp_file="$(mktemp "${wrapper_path}.tmp.XXXXXX")"

    cat > "${tmp_file}" <<EOF
#!/usr/bin/env bash
set -euo pipefail

CONFIG_FILE="${INSTALL_DIR}/install/dpslogger.conf"
if [[ ! -f "\${CONFIG_FILE}" ]]; then
    echo "[ERROR] Missing config file: \${CONFIG_FILE}" >&2
    exit 1
fi

# shellcheck disable=SC1090
source "\${CONFIG_FILE}"

export PYTHONPATH="\${INSTALL_DIR}"

if [[ "\${DPSLOGGER_DEBUG:-0}" = "1" ]]; then
    echo "[DEBUG] CONFIG_FILE=\${CONFIG_FILE}"
    echo "[DEBUG] PYTHON_BIN=\${PYTHON_BIN}"
    echo "[DEBUG] PYTHONPATH=\${PYTHONPATH}"
fi

if [[ ! -x "\${PYTHON_BIN}" ]]; then
    echo "[ERROR] Python interpreter not found: \${PYTHON_BIN}" >&2
    exit 1
fi

exec "\${PYTHON_BIN}" -m ${module_name} "\$@"
EOF

    chmod 755 "${tmp_file}"
    mv -f "${tmp_file}" "${wrapper_path}"
}

install_wrappers() {
    log "Installing command wrappers to ${BIN_DIR}"

    write_wrapper "${BIN_DIR}/dps-logger" "dpslogger.cli.dps_bus_logger"
    write_wrapper "${BIN_DIR}/dps-term" "dpslogger.cli.dps_term"
    write_wrapper "${BIN_DIR}/dps-scan" "dpslogger.cli.dps_address_scan"
    write_wrapper "${BIN_DIR}/dps-read" "dpslogger.cli.dps_read"
    write_wrapper "${BIN_DIR}/dps-set-address" "dpslogger.cli.dps_set_address"
    write_wrapper "${BIN_DIR}/dps-plot" "dpslogger.cli.dps_plot_csv"

    write_wrapper "${BIN_DIR}/dps-port-check" "dpslogger.tools.port_check"
    write_wrapper "${BIN_DIR}/dps-loopback-test" "dpslogger.tools.loopback_test"
    write_wrapper "${BIN_DIR}/dps-setup-udev" "dpslogger.tools.setup_udev"
    write_wrapper "${BIN_DIR}/dps-serial-debug" "dpslogger.tools.dps-serial-debug"
}

set_permissions() {
    log "Setting permissions"
    chown -R root:root "${INSTALL_DIR}"
    find "${INSTALL_DIR}" -type d -exec chmod 755 {} +
    find "${INSTALL_DIR}" -type f -exec chmod 644 {} +

    chmod 755 "${BIN_DIR}/dps-logger"
    chmod 755 "${BIN_DIR}/dps-term"
    chmod 755 "${BIN_DIR}/dps-scan"
    chmod 755 "${BIN_DIR}/dps-read"
    chmod 755 "${BIN_DIR}/dps-set-address"
    chmod 755 "${BIN_DIR}/dps-plot"
    chmod 755 "${BIN_DIR}/dps-port-check"
    chmod 755 "${BIN_DIR}/dps-loopback-test"
    chmod 755 "${BIN_DIR}/dps-setup-udev"
    chmod 755 "${BIN_DIR}/dps-serial-debug"
}

post_install_test() {
    log "Running post-install checks"

    "${BIN_DIR}/dps-term" --help >/dev/null
    "${BIN_DIR}/dps-logger" --help >/dev/null
    "${BIN_DIR}/dps-scan" --help >/dev/null
    "${BIN_DIR}/dps-read" --help >/dev/null
    "${BIN_DIR}/dps-set-address" --help >/dev/null
    "${BIN_DIR}/dps-plot" --help >/dev/null
    "${BIN_DIR}/dps-port-check" --help >/dev/null
    "${BIN_DIR}/dps-loopback-test" --help >/dev/null
    "${BIN_DIR}/dps-setup-udev" --help >/dev/null
    "${BIN_DIR}/dps-serial-debug" --help >/dev/null
}

print_summary() {
    cat <<EOF

Installation complete.

Installed package:
  ${INSTALL_DIR}/dpslogger

Config file:
  ${INSTALL_DIR}/install/dpslogger.conf

Version:
  ${VERSION}

Python:
  ${PYTHON_BIN}

Commands:
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

Notes:
  - DPS Logger is installed as a shared read-only application.
  - Measurement data and plots must be written to user-owned locations.
  - The tools do not implement a serial port lock.
  - Only one process should normally access a serial device at a time.
  - Concurrent access is intended only for debugging.

Serial device access:
  Users may need to be added to the appropriate serial device group.

Typical example:
  sudo usermod -aG dialout <username>

After changing group membership:
  The user must log out and log back in.
EOF
}

main() {
    parse_args "$@"
    require_root
    detect_python
    check_layout
    check_source_tree
    check_python
    prepare_install_tree
    install_package
    install_docs
    write_version_file
    write_config
    install_wrappers
    set_permissions
    post_install_test
    print_summary
}

main "$@"

