#!/usr/bin/env bash

set -Eeuo pipefail
IFS=$'\n\t'

# ============================================================
# idontScanner Installer
# Version: v2.0.0
# ============================================================

APP_NAME="idontScanner"
SERVICE_NAME="idontscanner"
VERSION="v2.0.0"

# Main installation directories.
APP_DIR="/opt/idontScanner"
DATA_DIR="/var/lib/idontscanner"
LOG_DIR="/var/log/idontscanner"

SYSTEM_USER="idontscanner"
DEFAULT_PORT=8088

# GitHub repository used when install.sh is executed through
# curl | bash and therefore has no local project directory.
GITHUB_REPO="https://github.com/durwinam/idontScanner.git"
GITHUB_BRANCH="main"

# Temporary workspace for remote installation.
TEMP_ROOT=""

# Installation state.
FRESH=0
NO_UFW=0
REQUESTED_PORT="$DEFAULT_PORT"

# ------------------------------------------------------------
# Colors
# ------------------------------------------------------------

C=$'\033[36m'
G=$'\033[32m'
Y=$'\033[33m'
R=$'\033[31m'
B=$'\033[1m'
N=$'\033[0m'

# ------------------------------------------------------------
# Logging
# ------------------------------------------------------------

log() {
    echo -e "${C}[idontScanner]${N} $*"
}

ok() {
    echo -e "${G}[OK]${N} $*"
}

warn() {
    echo -e "${Y}[WARN]${N} $*"
}

die() {
    echo -e "${R}[ERROR]${N} $*"
    exit 1
}

# ------------------------------------------------------------
# Cleanup
# ------------------------------------------------------------

cleanup() {
    if [[ -n "${TEMP_ROOT:-}" && -d "$TEMP_ROOT" ]]; then
        rm -rf "$TEMP_ROOT"
    fi
}

trap cleanup EXIT

trap 'die "Installation failed at line ${LINENO}. Command: ${BASH_COMMAND}"' ERR

# ------------------------------------------------------------
# Basic helpers
# ------------------------------------------------------------

command_exists() {
    command -v "$1" >/dev/null 2>&1
}

require_root() {
    [[ "$EUID" -eq 0 ]] || {
        die "Run this installer as root: sudo bash install.sh"
    }
}

check_os() {
    [[ -f /etc/os-release ]] || {
        die "Cannot detect operating system."
    }

    . /etc/os-release

    case "${ID:-}" in
        ubuntu|debian)
            ;;
        *)
            die "Supported operating systems: Debian / Ubuntu."
            ;;
    esac
}

is_valid_port() {
    local port="$1"

    [[ "$port" =~ ^[0-9]+$ ]] || return 1
    (( port >= 1 && port <= 65535 ))
}

port_is_busy() {
    local port="$1"

    if command_exists ss; then
        ss -lntH 2>/dev/null \
            | awk '{print $4}' \
            | grep -Eq "(:|\])${port}$"
        return $?
    fi

    return 1
}

find_free_port() {
    local port="$REQUESTED_PORT"

    while port_is_busy "$port"; do
        port=$((port + 1))

        if (( port > 65535 )); then
            die "No free TCP port was found."
        fi
    done

    echo "$port"
}

# ------------------------------------------------------------
# Arguments
# ------------------------------------------------------------

show_help() {
    cat <<EOF

${B}${APP_NAME} ${VERSION}${N}

Secure HTTP SNI / TLS Diagnostic Panel

Usage:
    sudo bash install.sh [OPTIONS]

Options:
    --fresh
        Remove the previous idontScanner installation,
        database and settings before installing.

    --port PORT
        Preferred HTTP port.
        Default: ${DEFAULT_PORT}
        If the port is busy, the next available port is used.

    --no-ufw
        Do not modify UFW firewall rules.

    -h, --help
        Show this help message.

Examples:

    sudo bash install.sh

    sudo bash install.sh --port 8088

    sudo bash install.sh --fresh

    sudo bash install.sh --no-ufw

EOF
}

parse_arguments() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --fresh)
                FRESH=1
                ;;

            --no-ufw)
                NO_UFW=1
                ;;

            --port)
                shift

                [[ -n "${1:-}" ]] || {
                    die "--port requires a port number."
                }

                is_valid_port "$1" || {
                    die "Invalid port: $1"
                }

                REQUESTED_PORT="$1"
                ;;

            -h|--help)
                show_help
                exit 0
                ;;

            *)
                die "Unknown option: $1"
                ;;
        esac

        shift
    done
}

# ------------------------------------------------------------
# System packages
# ------------------------------------------------------------

install_system_packages() {
    log "Installing required system packages..."

    apt-get update -y

    apt-get install -y \
        python3 \
        python3-pip \
        python3-venv \
        python3-dev \
        curl \
        ca-certificates \
        openssl \
        unzip \
        iproute2 \
        rsync \
        git

    if ! python3 -c 'import ensurepip' >/dev/null 2>&1; then
        local python_version

        python_version="$(
            python3 -c \
                'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")'
        )"

        apt-get install -y \
            "python${python_version}-venv" \
            2>/dev/null \
            || apt-get install -y python3-venv
    fi

    ok "Required system packages are ready."
}

# ------------------------------------------------------------
# Source detection
# ------------------------------------------------------------

script_directory() {
    local source="${BASH_SOURCE[0]:-}"

    if [[ -n "$source" && "$source" != "bash" && "$source" != "/dev/stdin" ]]; then
        if [[ -f "$source" ]]; then
            dirname "$(readlink -f "$source")"
            return 0
        fi
    fi

    return 1
}

directory_is_project_root() {
    local directory="$1"

    [[ -f "$directory/requirements.txt" ]] &&
    [[ -d "$directory/app" ]] &&
    [[ -f "$directory/app/main.py" ]]
}

find_local_project_root() {
    local directory

    directory="$(script_directory 2>/dev/null || true)"

    if [[ -n "$directory" ]] &&
       directory_is_project_root "$directory"; then
        echo "$directory"
        return 0
    fi

    # Common case:
    # /opt/idontScanner/idontScanner-2.0.0
    if directory_is_project_root \
        "$APP_DIR/idontScanner-2.0.0"; then
        echo "$APP_DIR/idontScanner-2.0.0"
        return 0
    fi

    # Another possible extracted directory.
    if [[ -d "$APP_DIR" ]]; then
        local candidate

        while IFS= read -r candidate; do
            if directory_is_project_root "$candidate"; then
                echo "$candidate"
                return 0
            fi
        done < <(
            find "$APP_DIR" \
                -mindepth 1 \
                -maxdepth 2 \
                -type d \
                -print 2>/dev/null
        )
    fi

    return 1
}

download_remote_source() {
    log "Local project source was not found."
    log "Downloading ${APP_NAME} ${VERSION} from GitHub..."

    command_exists git || {
        die "git is required for remote installation."
    }

    TEMP_ROOT="$(mktemp -d -t idontscanner-install-XXXXXX)"

    local checkout="$TEMP_ROOT/source"

    if ! git clone \
        --depth 1 \
        --branch "$GITHUB_BRANCH" \
        "$GITHUB_REPO" \
        "$checkout"; then

        die "Could not download the project from GitHub."
    fi

    directory_is_project_root "$checkout" || {
        die "Downloaded project is missing required files."
    }

    echo "$checkout"
}

resolve_source_directory() {
    local source

    source="$(find_local_project_root 2>/dev/null || true)"

    if [[ -n "$source" ]]; then
        log "Detected local project source:"
        echo "    $source"
        echo
        printf '%s\n' "$source"
        return 0
    fi

    download_remote_source
}

# ------------------------------------------------------------
# Validate source
# ------------------------------------------------------------

validate_project_source() {
    local source="$1"

    log "Validating project source..."

    [[ -d "$source" ]] || {
        die "Project source directory does not exist: $source"
    }

    [[ -f "$source/requirements.txt" ]] || {
        die "requirements.txt was not found in: $source"
    }

    [[ -d "$source/app" ]] || {
        die "app/ directory was not found in: $source"
    }

    [[ -f "$source/app/main.py" ]] || {
        die "app/main.py was not found in: $source"
    }

    [[ -f "$source/app/database.py" ]] || {
        die "app/database.py was not found in: $source"
    }

    [[ -f "$source/app/auth.py" ]] || {
        die "app/auth.py was not found in: $source"
    }

    if [[ -f "$source/VERSION" ]]; then
        local detected_version

        detected_version="$(
            tr -d '[:space:]' < "$source/VERSION"
        )"

        if [[ -n "$detected_version" &&
              "$detected_version" != "$VERSION" ]]; then
            warn "Project VERSION is $detected_version."
            warn "Installer version is $VERSION."
        fi
    fi

    ok "Project source is valid."
}

# ------------------------------------------------------------
# Previous installation
# ------------------------------------------------------------

stop_previous_service() {
    systemctl stop "$SERVICE_NAME" 2>/dev/null || true
    systemctl disable "$SERVICE_NAME" 2>/dev/null || true
}

remove_previous_installation() {
    log "Removing previous idontScanner installation..."

    stop_previous_service

    rm -f \
        "/etc/systemd/system/${SERVICE_NAME}.service"

    systemctl daemon-reload

    # Only remove idontScanner's own installation paths.
    rm -rf "$APP_DIR"
    rm -rf "$DATA_DIR"
    rm -rf "$LOG_DIR"

    # Remove the dedicated service account only if it exists.
    if id "$SYSTEM_USER" >/dev/null 2>&1; then
        userdel "$SYSTEM_USER" 2>/dev/null || true
    fi

    ok "Previous idontScanner installation removed."
}

# ------------------------------------------------------------
# Service account
# ------------------------------------------------------------

create_service_account() {
    log "Creating dedicated service account..."

    if ! id "$SYSTEM_USER" >/dev/null 2>&1; then
        useradd \
            --system \
            --home "$APP_DIR" \
            --shell /usr/sbin/nologin \
            "$SYSTEM_USER"
    fi

    mkdir -p \
        "$APP_DIR" \
        "$DATA_DIR" \
        "$LOG_DIR"

    chown \
        "$SYSTEM_USER:$SYSTEM_USER" \
        "$APP_DIR" \
        "$DATA_DIR" \
        "$LOG_DIR"

    chmod 750 \
        "$APP_DIR" \
        "$DATA_DIR" \
        "$LOG_DIR"

    ok "Service account ready."
}

# ------------------------------------------------------------
# Install project files
# ------------------------------------------------------------

copy_project_files() {
    local source="$1"

    log "Installing project files..."

    mkdir -p "$APP_DIR"

    # Important:
    # Copy the contents of the detected project root, not the
    # parent directory. This prevents:
    #
    # /opt/idontScanner/idontScanner-2.0.0
    #
    # from becoming:
    #
    # /opt/idontScanner/idontScanner-2.0.0/idontScanner-2.0.0
    #
    rsync -a \
        --delete-excluded \
        --exclude '.git/' \
        --exclude '__pycache__/' \
        --exclude '*.pyc' \
        --exclude '.venv/' \
        --exclude '.env' \
        "$source/" \
        "$APP_DIR/"

    find "$APP_DIR" \
        -type d \
        -name '__pycache__' \
        -prune \
        -exec rm -rf {} + \
        2>/dev/null || true

    find "$APP_DIR" \
        -type f \
        -name '*.pyc' \
        -delete \
        2>/dev/null || true

    chown -R \
        "$SYSTEM_USER:$SYSTEM_USER" \
        "$APP_DIR"

    chmod 750 "$APP_DIR"

    [[ -f "$APP_DIR/requirements.txt" ]] || {
        die "Project installation failed: requirements.txt is missing."
    }

    [[ -f "$APP_DIR/app/main.py" ]] || {
        die "Project installation failed: app/main.py is missing."
    }

    ok "Project files installed."
}

# ------------------------------------------------------------
# Python environment
# ------------------------------------------------------------

create_python_environment() {
    log "Creating isolated Python environment..."

    if [[ ! -x "$APP_DIR/.venv/bin/python" ]]; then
        python3 -m venv "$APP_DIR/.venv"
    fi

    "$APP_DIR/.venv/bin/python" \
        -m pip install \
        --upgrade \
        pip \
        wheel

    "$APP_DIR/.venv/bin/pip" \
        install \
        -r "$APP_DIR/requirements.txt"

    chown -R \
        "$SYSTEM_USER:$SYSTEM_USER" \
        "$APP_DIR/.venv"

    ok "Python environment is ready."
}

# ------------------------------------------------------------
# Python validation
# ------------------------------------------------------------

validate_python_source() {
    log "Checking Python source files..."

    cd "$APP_DIR"

    "$APP_DIR/.venv/bin/python" \
        -m compileall \
        -q \
        app

    ok "Python syntax check passed."
}

# ------------------------------------------------------------
# Admin credentials
# ------------------------------------------------------------

read_admin_credentials() {
    echo
    echo "------------------------------------------------------------"
    echo "idontScanner administrator"
    echo "------------------------------------------------------------"

    read -rp \
        "Admin username [admin]: " \
        ADMIN_USER

    ADMIN_USER="${ADMIN_USER:-admin}"

    [[ "$ADMIN_USER" =~ ^[A-Za-z0-9_.-]{3,32}$ ]] || {
        die "Invalid username. Use 3-32 letters, numbers, dot, dash or underscore."
    }

    while true; do
        read -rsp \
            "Admin password (minimum 8 characters): " \
            ADMIN_PASS
        echo

        if (( ${#ADMIN_PASS} < 8 )); then
            warn "Password must contain at least 8 characters."
            continue
        fi

        read -rsp \
            "Confirm password: " \
            ADMIN_PASS2
        echo

        if [[ "$ADMIN_PASS" != "$ADMIN_PASS2" ]]; then
            warn "Passwords do not match."
            continue
        fi

        break
    done
}

# ------------------------------------------------------------
# Environment
# ------------------------------------------------------------

create_environment_file() {
    log "Creating application environment..."

    local secret

    secret="$(
        "$APP_DIR/.venv/bin/python" - <<'PY'
import secrets

print(secrets.token_urlsafe(48))
PY
    )"

    cat > "$APP_DIR/.env" <<EOF
IDONTSCANNER_VERSION=$VERSION
IDONTSCANNER_SECRET=$secret
IDONTSCANNER_DATA_DIR=$DATA_DIR
EOF

    chmod 600 "$APP_DIR/.env"

    chown \
        "$SYSTEM_USER:$SYSTEM_USER" \
        "$APP_DIR/.env"

    ok "Application environment created."
}

# ------------------------------------------------------------
# Database
# ------------------------------------------------------------

initialize_database() {
    log "Initializing database and administrator credentials..."

    cd "$APP_DIR"

    ADMIN_USER="$ADMIN_USER" \
    ADMIN_PASS="$ADMIN_PASS" \
    PYTHONPATH="$APP_DIR" \
    "$APP_DIR/.venv/bin/python" - <<'PY'
import os

from app.auth import hash_password
from app.database import init_db, set_setting

init_db()

set_setting(
    "username",
    os.environ["ADMIN_USER"],
)

set_setting(
    "password",
    hash_password(
        os.environ["ADMIN_PASS"]
    ),
)
PY

    unset ADMIN_PASS
    unset ADMIN_PASS2

    chown -R \
        "$SYSTEM_USER:$SYSTEM_USER" \
        "$DATA_DIR"

    chmod 700 "$DATA_DIR"

    ok "Database initialized."
}

# ------------------------------------------------------------
# Systemd
# ------------------------------------------------------------

create_systemd_service() {
    local port="$1"

    log "Creating systemd service..."

    cat > "/etc/systemd/system/${SERVICE_NAME}.service" <<EOF
[Unit]
Description=idontScanner HTTP Diagnostic Panel
After=network-online.target
Wants=network-online.target

[Service]
Type=simple

User=$SYSTEM_USER
Group=$SYSTEM_USER

WorkingDirectory=$APP_DIR

EnvironmentFile=$APP_DIR/.env
Environment=PYTHONPATH=$APP_DIR

ExecStart=$APP_DIR/.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port $port

Restart=on-failure
RestartSec=3
TimeoutStartSec=30
TimeoutStopSec=30

NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=true

ReadWritePaths=$APP_DIR
ReadWritePaths=$DATA_DIR
ReadWritePaths=$LOG_DIR

[Install]
WantedBy=multi-user.target
EOF

    chmod 644 \
        "/etc/systemd/system/${SERVICE_NAME}.service"

    systemctl daemon-reload

    systemctl enable "$SERVICE_NAME" >/dev/null

    ok "Systemd service created."
}

# ------------------------------------------------------------
# CLI
# ------------------------------------------------------------

install_cli() {
    if [[ -f "$APP_DIR/idontscanner-cli" ]]; then
        chmod 755 "$APP_DIR/idontscanner-cli"

        install \
            -m 755 \
            "$APP_DIR/idontscanner-cli" \
            /usr/local/bin/idontScanner

        ok "idontScanner CLI installed."
    else
        warn "idontscanner-cli was not found. CLI was skipped."
    fi
}

# ------------------------------------------------------------
# Service startup
# ------------------------------------------------------------

start_service() {
    local port="$1"

    log "Starting idontScanner on TCP/$port..."

    systemctl restart "$SERVICE_NAME"

    local health_ok=0
    local attempt

    for attempt in $(seq 1 30); do
        if systemctl is-active \
            --quiet \
            "$SERVICE_NAME"; then

            if curl \
                -fsS \
                --connect-timeout 1 \
                --max-time 3 \
                "http://127.0.0.1:${port}/login/" \
                >/dev/null 2>&1; then

                health_ok=1
                break
            fi
        fi

        sleep 1
    done

    if [[ "$health_ok" -ne 1 ]]; then
        echo
        echo "------------------------------------------------------------"
        echo "Service diagnostic"
        echo "------------------------------------------------------------"

        systemctl status \
            "$SERVICE_NAME" \
            --no-pager \
            || true

        echo
        echo "------------------------------------------------------------"
        echo "Recent logs"
        echo "------------------------------------------------------------"

        journalctl \
            -u "$SERVICE_NAME" \
            -n 100 \
            --no-pager \
            || true

        die \
            "HTTP health check failed on 127.0.0.1:${port}."
    fi

    ok "idontScanner service is running."
}

# ------------------------------------------------------------
# Firewall
# ------------------------------------------------------------

configure_firewall() {
    local port="$1"

    if (( NO_UFW == 1 )); then
        warn "UFW configuration was disabled with --no-ufw."
        return
    fi

    if ! command_exists ufw; then
        return
    fi

    if ! ufw status 2>/dev/null \
        | grep -q '^Status: active'; then
        return
    fi

    ufw allow \
        "${port}/tcp" \
        >/dev/null

    ok "UFW rule added for TCP/$port."
}

# ------------------------------------------------------------
# Final information
# ------------------------------------------------------------

show_installation_result() {
    local port="$1"

    local server_ip

    server_ip="$(
        hostname -I 2>/dev/null \
        | awk '{print $1}'
    )"

    server_ip="${server_ip:-127.0.0.1}"

    echo
    echo "============================================================"
    echo "              idontScanner ${VERSION}"
    echo "             INSTALLATION COMPLETE"
    echo "============================================================"
    echo
    echo " Version       : ${VERSION}"
    echo " Service       : ${SERVICE_NAME}"
    echo " Status        : RUNNING"
    echo " Protocol      : HTTP"
    echo " Port          : ${port}"
    echo
    echo " Panel         : http://${server_ip}:${port}/"
    echo " Login         : http://${server_ip}:${port}/login/"
    echo
    echo " Username      : ${ADMIN_USER}"
    echo " Password      : [hidden]"
    echo
    echo " Scheduler     : OFF by default"
    echo " Telegram      : Optional / Settings"
    echo
    echo " Data          : ${DATA_DIR}"
    echo " Logs          : ${LOG_DIR}"
    echo " Application   : ${APP_DIR}"
    echo
    echo "============================================================"
    echo
    echo -e "${G}idontScanner is ready.${N}"
    echo
}

# ------------------------------------------------------------
# Main
# ------------------------------------------------------------

main() {
    require_root
    parse_arguments "$@"
    check_os

    echo
    echo "============================================================"
    echo "                 ${APP_NAME} ${VERSION}"
    echo "        Secure HTTP SNI / TLS Diagnostic Panel"
    echo "============================================================"
    echo

    install_system_packages

    local source_dir

    source_dir="$(resolve_source_directory)"

    validate_project_source "$source_dir"

    if (( FRESH == 1 )); then
        remove_previous_installation
    else
        # Stop only the existing idontScanner service.
        # Existing application data is intentionally preserved.
        systemctl stop \
            "$SERVICE_NAME" \
            2>/dev/null || true
    fi

    create_service_account

    copy_project_files "$source_dir"

    create_python_environment

    validate_python_source

    read_admin_credentials

    create_environment_file

    initialize_database

    local port

    port="$(find_free_port)"

    create_systemd_service "$port"

    install_cli

    start_service "$port"

    configure_firewall "$port"

    show_installation_result "$port"
}

main "$@"
