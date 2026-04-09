#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="/opt/dpslogger"
BIN_DIR="/usr/local/bin"
PYTHON_BIN=""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="${SCRIPT_DIR}/dpslogger"
DOCS_DIR="${SCRIPT_DIR}/docs"
VERSION_FILE="${SCRIPT_DIR}/VERSION"
README_FILE="${SCRIPT_DIR}/README.md"

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

read_version() {
    [[ -f "${VERSION_FILE}" ]] || die "Missing VERSION file: ${VERSION_FILE}"
    VERSION="$(<"${VERSION_FILE}")"
    [[ -n "${VERSION}" ]] || die "VERSION file is empty: ${VERSION_FILE}"
}

check_layout() {
    [[ -d "${SOURCE_DIR}" ]] || die "Expected source directory next to install.sh: ${SOURCE_DIR}"
    [[ -d "${DOCS_DIR}" ]] || die "Expected docs directory next to install.sh: ${DOCS_DIR}"
    [[ -f "${README_FILE}" ]] || die "Missing README.md next to install.sh: ${README_FILE}"
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
    [[ -f "${SOURCE_DIR}/cli/dps_unit.py" ]] || die "Missing dps_unit.py"
    [[ -f "${SOURCE_DIR}/cli/dps_plot.py" ]] || die "Missing dps_plot.py"

    [[ -f "${SOURCE_DIR}/tools/loopback_test.py" ]] || die "Missing loopback_test.py"
    [[ -f "${SOURCE_DIR}/tools/port_check.py" ]] || die "Missing port_check.py"
    [[ -f "${SOURCE_DIR}/tools/setup_udev.py" ]] || die "Missing setup_udev.py"
    [[ -f "${SOURCE_DIR}/dps_autoread_off.py" ]] || die "Missing dps_autoread_off.py"
    [[ -f "${SOURCE_DIR}/tools/dps-serial-debug" ]] || die "Missing dps-serial-debug"
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
    rm -rf "${INSTALL_DIR}"
    mkdir -p "${INSTALL_DIR}"
    mkdir -p "${INSTALL_DIR}/install"
    mkdir -p "${INSTALL_DIR}/docs"
    mkdir -p "${BIN_DIR}"
}

install_package() {
    log "Installing package to ${INSTALL_DIR}/dpslogger"

    mkdir -p "${INSTALL_DIR}/dpslogger"
    cp -a "${SOURCE_DIR}/." "${INSTALL_DIR}/dpslogger/"

    find "${INSTALL_DIR}/dpslogger" -type d -name "__pycache__" -prune -exec rm -rf {} +
    find "${INSTALL_DIR}/dpslogger" -type f -name "*.pyc" -delete
    find "${INSTALL_DIR}/dpslogger" -type f -name "*.old.py" -delete
}

install_docs() {
    log "Installing documentation"
    rm -rf "${INSTALL_DIR}/docs"
    mkdir -p "${INSTALL_DIR}/docs"
    cp -a "${DOCS_DIR}/." "${INSTALL_DIR}/docs/"
}

install_readme() {
    log "Installing package README"
    install -m 644 "${README_FILE}" "${INSTALL_DIR}/README.md"
}

write_version_file() {
    log "Writing VERSION file"
    printf '%s\n' "${VERSION}" > "${INSTALL_DIR}/VERSION"
    chmod 644 "${INSTALL_DIR}/VERSION"
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

write_module_wrapper() {
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

write_tool_wrapper() {
    local wrapper_path="$1"
    local script_rel="$2"
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

exec "\${PYTHON_BIN}" "\${INSTALL_DIR}/${script_rel}" "\$@"
EOF

    chmod 755 "${tmp_file}"
    mv -f "${tmp_file}" "${wrapper_path}"
}

install_wrappers() {
    log "Installing command wrappers to ${BIN_DIR}"

    write_module_wrapper "${BIN_DIR}/dps-logger" "dpslogger.cli.dps_bus_logger"
    write_module_wrapper "${BIN_DIR}/dps-bus-logger" "dpslogger.cli.dps_bus_logger"
    write_module_wrapper "${BIN_DIR}/dps-term" "dpslogger.cli.dps_term"
    write_module_wrapper "${BIN_DIR}/dps-scan" "dpslogger.cli.dps_address_scan"
    write_module_wrapper "${BIN_DIR}/dps-read" "dpslogger.cli.dps_read"
    write_module_wrapper "${BIN_DIR}/dps-set-address" "dpslogger.cli.dps_set_address"
    write_module_wrapper "${BIN_DIR}/dps-unit" "dpslogger.cli.dps_unit"
    write_module_wrapper "${BIN_DIR}/dps-plot" "dpslogger.cli.dps_plot"

    write_tool_wrapper "${BIN_DIR}/dps-port-check" "dpslogger/tools/port_check.py"
    write_tool_wrapper "${BIN_DIR}/dps-loopback-test" "dpslogger/tools/loopback_test.py"
    write_tool_wrapper "${BIN_DIR}/dps-setup-udev" "dpslogger/tools/setup_udev.py"

    write_module_wrapper "${BIN_DIR}/dps-autoread-off" "dpslogger.dps_autoread_off"

    rm -f "${BIN_DIR}/dps-serial-debug"
    ln -s "${INSTALL_DIR}/dpslogger/tools/dps-serial-debug" "${BIN_DIR}/dps-serial-debug"
}

set_permissions() {
    log "Setting permissions"
    chown -R root:root "${INSTALL_DIR}"
    find "${INSTALL_DIR}" -type d -exec chmod 755 {} +
    find "${INSTALL_DIR}" -type f -exec chmod 644 {} +

    chmod 755 "${INSTALL_DIR}/dpslogger/tools/dps-serial-debug"

    chmod 755 "${BIN_DIR}/dps-logger"
    chmod 755 "${BIN_DIR}/dps-bus-logger"
    chmod 755 "${BIN_DIR}/dps-term"
    chmod 755 "${BIN_DIR}/dps-scan"
    chmod 755 "${BIN_DIR}/dps-read"
    chmod 755 "${BIN_DIR}/dps-set-address"
    chmod 755 "${BIN_DIR}/dps-unit"
    chmod 755 "${BIN_DIR}/dps-plot"
    chmod 755 "${BIN_DIR}/dps-port-check"
    chmod 755 "${BIN_DIR}/dps-loopback-test"
    chmod 755 "${BIN_DIR}/dps-setup-udev"
    chmod 755 "${BIN_DIR}/dps-autoread-off"
}

post_install_test() {
    log "Running post-install checks"

    "${BIN_DIR}/dps-term" --help >/dev/null
    "${BIN_DIR}/dps-logger" --help >/dev/null
    "${BIN_DIR}/dps-bus-logger" --help >/dev/null
    "${BIN_DIR}/dps-scan" --help >/dev/null
    "${BIN_DIR}/dps-read" --help >/dev/null
    "${BIN_DIR}/dps-set-address" --help >/dev/null
    "${BIN_DIR}/dps-unit" --help >/dev/null
    "${BIN_DIR}/dps-plot" --help >/dev/null
    "${BIN_DIR}/dps-port-check" --help >/dev/null
    "${BIN_DIR}/dps-loopback-test" --help >/dev/null
    "${BIN_DIR}/dps-setup-udev" --help >/dev/null
    "${BIN_DIR}/dps-autoread-off" --help >/dev/null
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
  ${BIN_DIR}/dps-bus-logger
  ${BIN_DIR}/dps-term
  ${BIN_DIR}/dps-scan
  ${BIN_DIR}/dps-read
  ${BIN_DIR}/dps-set-address
  ${BIN_DIR}/dps-unit
  ${BIN_DIR}/dps-plot
  ${BIN_DIR}/dps-port-check
  ${BIN_DIR}/dps-loopback-test
  ${BIN_DIR}/dps-setup-udev
  ${BIN_DIR}/dps-serial-debug
  ${BIN_DIR}/dps-autoread-off

Notes:
  - DPS Logger is installed as a shared read-only application.
  - Measurement data, plots, statistics, and metadata must be written to user-owned locations.
  - /opt/dpslogger is reserved for the installed application.
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
    read_version
    check_layout
    check_source_tree
    check_python
    prepare_install_tree
    install_package
    install_docs
    install_readme
    write_version_file
    write_config
    install_wrappers
    set_permissions
    post_install_test
    print_summary
}

main "$@"
