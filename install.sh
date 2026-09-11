#!/usr/bin/env bash

set -Eeuo pipefail

APP_NAME="idontScanner"
SERVICE_NAME="idontscanner"

APP_DIR="/opt/idontScanner"
DATA_DIR="/var/lib/idontscanner"
LOG_DIR="/var/log/idontscanner"

SYSTEM_USER="idontscanner"
DEFAULT_PORT=8088
VERSION="v2.0.0"

CYAN=$'\033[36m'
GREEN=$'\033[32m'
YELLOW=$'\033[33m'
RED=$'\033[31m'
RESET=$'\033[0m'


log() {
    printf '%b%s%b %s\n' \
        "$CYAN" "[idontScanner]" "$RESET" "$*" >&2
}

ok() {
    printf '%b%s%b %s\n' \
        "$GREEN" "[OK]" "$RESET" "$*" >&2
}

warn() {
    printf '%b%s%b %s\n' \
        "$YELLOW" "[WARN]" "$RESET" "$*" >&2
}

die() {
    printf '%b%s%b %s\n' \
        "$RED" "[ERROR]" "$RESET" "$*" >&2
    exit 1
}


trap 'die "Installation failed at line ${LINENO}."' ERR


[[ $EUID -eq 0 ]] ||
    die "Run as root: sudo bash install.sh"

command -v apt-get >/dev/null 2>&1 ||
    die "Debian/Ubuntu with apt-get is required."

command -v systemctl >/dev/null 2>&1 ||
    die "systemd is required."


FRESH=0
NO_UFW=0
REQUESTED_PORT="${IDONTSCANNER_PORT:-$DEFAULT_PORT}"


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

            [[ "${1:-}" =~ ^[0-9]+$ ]] ||
                die "--port requires a valid number."

            REQUESTED_PORT="$1"
            ;;

        -h|--help)
            cat <<EOF
$APP_NAME $VERSION

Usage:
  sudo bash install.sh [--fresh] [--port PORT] [--no-ufw]

Options:

  --fresh
      Remove the previous idontScanner installation,
      database and service configuration.

  --port PORT
      Preferred HTTP port.
      Default: 8088
      If busy, the next available port is selected.

  --no-ufw
      Do not modify UFW rules.
EOF
            exit 0
            ;;

        *)
            die "Unknown option: $1"
            ;;
    esac

    shift
done


[[ "$REQUESTED_PORT" =~ ^[0-9]+$ ]] ||
    die "Invalid port."

(( REQUESTED_PORT >= 1024 && REQUESTED_PORT <= 65535 )) ||
    die "Port must be between 1024 and 65535."


echo
echo "============================================================"
echo "                 idontScanner $VERSION"
echo "        Secure HTTP SNI / TLS Diagnostic Panel"
echo "============================================================"
echo


if [[ -f /etc/os-release ]]; then
    . /etc/os-release
fi

case "${ID:-}" in
    ubuntu|debian)
        ok "${PRETTY_NAME:-Debian/Ubuntu}"
        ;;

    *)
        die "Supported OS: Debian/Ubuntu."
        ;;
esac


export DEBIAN_FRONTEND=noninteractive


# ------------------------------------------------------------
# Fresh installation
# ------------------------------------------------------------

if [[ "$FRESH" -eq 1 ]]; then

    log "Removing previous idontScanner installation..."

    systemctl stop "$SERVICE_NAME" 2>/dev/null || true
    systemctl disable "$SERVICE_NAME" 2>/dev/null || true

    rm -f "/etc/systemd/system/${SERVICE_NAME}.service"

    systemctl daemon-reload

    rm -rf "$DATA_DIR"
    rm -rf "$LOG_DIR"

    # Do not blindly remove /opt/idontScanner because the directory
    # may contain unrelated files or other projects.
    if [[ -d "$APP_DIR" ]]; then

        find "$APP_DIR" -mindepth 1 -maxdepth 1 \
            ! -name ".env" \
            ! -name ".venv" \
            ! -name "idontScanner-2.0.0" \
            -exec rm -rf {} + 2>/dev/null || true

    fi

    userdel -r "$SYSTEM_USER" 2>/dev/null || true

    ok "Previous idontScanner installation removed."
fi


# ------------------------------------------------------------
# Required packages
# ------------------------------------------------------------

log "Installing required system packages..."

apt-get update -y

apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    python3-dev \
    sqlite3 \
    curl \
    ca-certificates \
    openssl \
    unzip \
    iproute2 \
    rsync


PYTHON_BIN="$(command -v python3)"

PYTHON_VERSION="$(
    "$PYTHON_BIN" -c \
        'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")'
)"


if ! "$PYTHON_BIN" -c 'import ensurepip' >/dev/null 2>&1; then

    apt-get install -y \
        "python${PYTHON_VERSION}-venv" 2>/dev/null ||
        apt-get install -y python3-venv

fi


"$PYTHON_BIN" -m venv --help >/dev/null 2>&1 ||
    die "Python venv is unavailable."

ok "Python $PYTHON_VERSION ready."


# ------------------------------------------------------------
# Find project source
# ------------------------------------------------------------

log "Detecting idontScanner project source..."

SCRIPT_DIR="$(
    cd "$(dirname "${BASH_SOURCE[0]}")" &&
    pwd
)"


SOURCE_DIR=""


# Case 1:
# install.sh is directly inside the project.
if [[ \
    -f "$SCRIPT_DIR/requirements.txt" &&
    -f "$SCRIPT_DIR/app/main.py"
 ]]; then

    SOURCE_DIR="$SCRIPT_DIR"

fi


# Case 2:
# install.sh is one directory above the actual project.
#
# Example:
#
# /opt/idontScanner/install.sh
# /opt/idontScanner/idontScanner-2.0.0/
#
if [[ -z "$SOURCE_DIR" ]]; then

    if [[ \
        -f "$SCRIPT_DIR/idontScanner-2.0.0/requirements.txt" &&
        -f "$SCRIPT_DIR/idontScanner-2.0.0/app/main.py"
    ]]; then

        SOURCE_DIR="$SCRIPT_DIR/idontScanner-2.0.0"

    fi

fi


# Case 3:
# Search for a valid idontScanner project directly below the
# script directory.
if [[ -z "$SOURCE_DIR" ]]; then

    while IFS= read -r candidate; do

        if [[ \
            -f "$candidate/requirements.txt" &&
            -f "$candidate/app/main.py"
        ]]; then

            SOURCE_DIR="$candidate"
            break

        fi

    done < <(
        find "$SCRIPT_DIR" \
            -mindepth 1 \
            -maxdepth 2 \
            -type d \
            -print 2>/dev/null
    )

fi


# Case 4:
# Remote installation.
#
# This is used when install.sh is executed directly through:
#
# curl ... | bash
#
if [[ -z "$SOURCE_DIR" ]]; then

    command -v curl >/dev/null 2>&1 ||
        die "curl is required for remote installation."

    command -v unzip >/dev/null 2>&1 || {
        log "Installing unzip..."
        apt-get update -y
        apt-get install -y unzip
    }


    TEMP_DIR="$(mktemp -d)"

    cleanup() {
        rm -rf "$TEMP_DIR"
    }

    trap cleanup EXIT


    ARCHIVE_URL="https://github.com/durwinam/idontScanner/archive/refs/heads/main.zip"
    ARCHIVE_FILE="$TEMP_DIR/idontScanner.zip"


    log "Downloading idontScanner from GitHub..."

    curl \
        -fL \
        --retry 3 \
        --connect-timeout 10 \
        "$ARCHIVE_URL" \
        -o "$ARCHIVE_FILE" ||
        die "Unable to download the idontScanner repository."


    unzip -q "$ARCHIVE_FILE" -d "$TEMP_DIR/source"


    SOURCE_DIR="$(
        find "$TEMP_DIR/source" \
            -mindepth 1 \
            -maxdepth 1 \
            -type d \
            -print -quit
    )"


    [[ -n "$SOURCE_DIR" ]] ||
        die "Downloaded repository directory was not found."


    [[ -f "$SOURCE_DIR/requirements.txt" ]] ||
        die "Downloaded repository is missing requirements.txt."

    [[ -f "$SOURCE_DIR/app/main.py" ]] ||
        die "Downloaded repository is missing app/main.py."


    ok "Project files downloaded."

fi


[[ -n "$SOURCE_DIR" ]] ||
    die "Unable to locate a valid idontScanner project source."


[[ -f "$SOURCE_DIR/requirements.txt" ]] ||
    die "requirements.txt was not found in: $SOURCE_DIR"

[[ -f "$SOURCE_DIR/app/main.py" ]] ||
    die "app/main.py was not found in: $SOURCE_DIR"


log "Project source detected:"
log "$SOURCE_DIR"


# ------------------------------------------------------------
# Validate project version
# ------------------------------------------------------------

if [[ -f "$SOURCE_DIR/VERSION" ]]; then

    SOURCE_VERSION="$(
        tr -d '[:space:]' < "$SOURCE_DIR/VERSION"
    )"

    if [[ -n "$SOURCE_VERSION" ]]; then
        VERSION="$SOURCE_VERSION"
    fi

fi


ok "Project version: $VERSION"


# ------------------------------------------------------------
# Service account
# ------------------------------------------------------------

log "Creating dedicated service account..."

if ! id "$SYSTEM_USER" >/dev/null 2>&1; then

    useradd \
        --system \
        --home-dir "$APP_DIR" \
        --shell /usr/sbin/nologin \
        "$SYSTEM_USER"

fi


mkdir -p "$APP_DIR"
mkdir -p "$DATA_DIR"
mkdir -p "$LOG_DIR"


# ------------------------------------------------------------
# Copy project
# ------------------------------------------------------------

log "Installing project files..."

# Keep runtime files such as .env and .venv.
# Do not use --delete-excluded here because that could remove
# preserved runtime files from the destination.

rsync \
    -a \
    --exclude ".env" \
    --exclude ".venv/" \
    --exclude "__pycache__/" \
    --exclude "*.pyc" \
    "$SOURCE_DIR/" \
    "$APP_DIR/"


find "$APP_DIR" \
    -type d \
    -name "__pycache__" \
    -prune \
    -exec rm -rf {} + 2>/dev/null || true


find "$APP_DIR" \
    -type f \
    -name "*.pyc" \
    -delete 2>/dev/null || true


[[ -f "$APP_DIR/requirements.txt" ]] ||
    die "Installed project is missing requirements.txt."

[[ -f "$APP_DIR/app/main.py" ]] ||
    die "Installed project is missing app/main.py."


# ------------------------------------------------------------
# Python environment
# ------------------------------------------------------------

log "Creating isolated Python environment..."

if [[ ! -x "$APP_DIR/.venv/bin/python" ]]; then

    rm -rf "$APP_DIR/.venv"

    "$PYTHON_BIN" -m venv "$APP_DIR/.venv"

fi


"$APP_DIR/.venv/bin/python" \
    -m pip install \
    --disable-pip-version-check \
    --no-cache-dir \
    --upgrade pip wheel


"$APP_DIR/.venv/bin/python" \
    -m pip install \
    --disable-pip-version-check \
    --no-cache-dir \
    -r "$APP_DIR/requirements.txt"


# ------------------------------------------------------------
# Validate Python source
# ------------------------------------------------------------

log "Validating Python application..."

"$APP_DIR/.venv/bin/python" -m compileall -q "$APP_DIR/app" ||
    die "Python source validation failed."


# ------------------------------------------------------------
# Admin credentials
# ------------------------------------------------------------

read -rp "Admin username [admin]: " ADMIN_USER

ADMIN_USER="${ADMIN_USER:-admin}"


[[ "$ADMIN_USER" =~ ^[A-Za-z0-9_.-]{3,32}$ ]] ||
    die "Username must be 3-32 characters: A-Z, a-z, 0-9, _, ., -."


while true; do

    read -rsp \
        "Admin password (minimum 12 characters): " \
        ADMIN_PASS

    echo


    (( ${#ADMIN_PASS} >= 12 )) || {
        warn "Password is too short. Minimum 12 characters."
        continue
    }


    read -rsp \
        "Confirm password: " \
        ADMIN_PASS2

    echo


    if [[ "$ADMIN_PASS" == "$ADMIN_PASS2" ]]; then
        break
    fi


    warn "Passwords do not match."

done


# ------------------------------------------------------------
# Secret
# ------------------------------------------------------------

SECRET="$(
    "$APP_DIR/.venv/bin/python" - <<'PY'
import secrets

print(secrets.token_urlsafe(64))
PY
)"


# ------------------------------------------------------------
# Environment
# ------------------------------------------------------------

cat > "$APP_DIR/.env" <<EOF
IDONTSCANNER_VERSION=$VERSION
IDONTSCANNER_SECRET=$SECRET
IDONTSCANNER_HOST=0.0.0.0
IDONTSCANNER_PORT=$REQUESTED_PORT
IDONTSCANNER_DATA_DIR=$DATA_DIR
IDONTSCANNER_DB_PATH=$DATA_DIR/idontscanner.db
EOF


chmod 600 "$APP_DIR/.env"


# ------------------------------------------------------------
# Database + authentication
# ------------------------------------------------------------

log "Initializing database and provisioning admin credentials..."

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
    hash_password(os.environ["ADMIN_PASS"]),
)

PY


unset ADMIN_PASS
unset ADMIN_PASS2


# ------------------------------------------------------------
# Permissions
# ------------------------------------------------------------

chown -R \
    "$SYSTEM_USER:$SYSTEM_USER" \
    "$APP_DIR" \
    "$DATA_DIR" \
    "$LOG_DIR"


chmod 750 \
    "$APP_DIR" \
    "$DATA_DIR" \
    "$LOG_DIR"


chmod 600 "$APP_DIR/.env"


# ------------------------------------------------------------
# Select available HTTP port
# ------------------------------------------------------------

PORT="$REQUESTED_PORT"


log "Selecting an available HTTP port..."

while ss -H -lnt 2>/dev/null |
    awk '{print $4}' |
    grep -Eq "(:|\])${PORT}$"; do

    warn "TCP/$PORT is already in use; trying $((PORT + 1))."

    PORT=$((PORT + 1))

    (( PORT <= 65535 )) ||
        die "No free TCP port found."

done


ok "HTTP port selected: $PORT"


# Update the final port in .env.
sed -i \
    "s/^IDONTSCANNER_PORT=.*/IDONTSCANNER_PORT=$PORT/" \
    "$APP_DIR/.env"


chown "$SYSTEM_USER:$SYSTEM_USER" "$APP_DIR/.env"
chmod 600 "$APP_DIR/.env"


# ------------------------------------------------------------
# Systemd
# ------------------------------------------------------------

log "Installing systemd service..."

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

ExecStart=$APP_DIR/.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT

Restart=on-failure
RestartSec=3
TimeoutStartSec=30

NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=true

ReadWritePaths=$APP_DIR $DATA_DIR $LOG_DIR

[Install]
WantedBy=multi-user.target
EOF


chmod 644 \
    "/etc/systemd/system/${SERVICE_NAME}.service"


# ------------------------------------------------------------
# CLI
# ------------------------------------------------------------

if [[ -f "$APP_DIR/idontscanner-cli" ]]; then

    chmod 755 "$APP_DIR/idontscanner-cli"

    install \
        -m 755 \
        "$APP_DIR/idontscanner-cli" \
        /usr/local/bin/idontScanner

fi


# ------------------------------------------------------------
# Start service
# ------------------------------------------------------------

systemctl daemon-reload

systemctl enable "$SERVICE_NAME" >/dev/null

systemctl restart "$SERVICE_NAME"


# ------------------------------------------------------------
# Health check
# ------------------------------------------------------------

log "Waiting for idontScanner to become ready..."

HEALTH_OK=0


for _ in $(seq 1 30); do

    if \
        systemctl is-active --quiet "$SERVICE_NAME" &&
        curl \
            -fsS \
            --connect-timeout 1 \
            --max-time 3 \
            "http://127.0.0.1:${PORT}/login/" \
            >/dev/null 2>&1
    then

        HEALTH_OK=1
        break

    fi

    sleep 1

done


if [[ "$HEALTH_OK" -ne 1 ]]; then

    journalctl \
        -u "$SERVICE_NAME" \
        -n 100 \
        --no-pager || true

    die \
        "HTTP health check failed on 127.0.0.1:${PORT}. Service did not become ready within 30 seconds."

fi


ok "idontScanner service is running."


# ------------------------------------------------------------
# UFW
# ------------------------------------------------------------

if \
    [[ "$NO_UFW" -eq 0 ]] &&
    command -v ufw >/dev/null 2>&1 &&
    ufw status 2>/dev/null |
        grep -q '^Status: active'
then

    ufw allow "${PORT}/tcp" >/dev/null

    ok "UFW rule added for TCP/$PORT"

fi


# ------------------------------------------------------------
# Server information
# ------------------------------------------------------------

SERVER_IP="$(
    hostname -I 2>/dev/null |
    awk '{print $1}'
)"

SERVER_IP="${SERVER_IP:-127.0.0.1}"


echo
echo "============================================================"
echo "                  INSTALLATION COMPLETE"
echo "============================================================"
echo
echo " Version       : $VERSION"
echo " Protocol      : HTTP"
echo " Service       : $SERVICE_NAME"
echo " Status        : RUNNING"
echo " Port          : $PORT/tcp"
echo " Panel         : http://${SERVER_IP}:${PORT}/"
echo " Login         : http://${SERVER_IP}:${PORT}/login/"
echo " Username      : $ADMIN_USER"
echo " Password      : [hidden]"
echo
echo " Scheduler     : OFF by default"
echo " Telegram      : Optional / Settings"
echo
echo " Service       : systemctl status $SERVICE_NAME"
echo " Logs          : journalctl -u $SERVICE_NAME -f"
echo
echo "============================================================"
echo
echo -e "${GREEN}idontScanner $VERSION is ready.${RESET}"
echo
