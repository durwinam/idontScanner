#!/usr/bin/env bash

set -Eeuo pipefail

APP="idontScanner"
VERSION="v2.1.0"
SERVICE="idontscanner"

APP_DIR="/opt/idontScanner"
DATA_DIR="/var/lib/idontscanner"
LOG_DIR="/var/log/idontscanner"

SYSTEM_USER="idontscanner"
DEFAULT_PORT=8088


cyan=$'\033[36m'
green=$'\033[32m'
yellow=$'\033[33m'
red=$'\033[31m'
reset=$'\033[0m'


log() {
    printf '%b%s%b %s\n' \
        "$cyan" "[idontScanner]" "$reset" "$*"
}

ok() {
    printf '%b%s%b %s\n' \
        "$green" "[OK]" "$reset" "$*"
}

warn() {
    printf '%b%s%b %s\n' \
        "$yellow" "[WARN]" "$reset" "$*"
}

die() {
    printf '%b%s%b %s\n' \
        "$red" "[ERROR]" "$reset" "$*" >&2
    exit 1
}


trap 'echo "[ERROR] Installation failed at line ${LINENO}." >&2' ERR


# ============================================================
# Basic checks
# ============================================================

[[ $EUID -eq 0 ]] ||
    die "Run as root: sudo bash install.sh"

command -v systemctl >/dev/null 2>&1 ||
    die "systemd is required."

command -v apt-get >/dev/null 2>&1 ||
    die "Debian/Ubuntu with apt-get is required."


# ============================================================
# Arguments
# ============================================================

FRESH=0
NO_UFW=0

PORT="${IDONTSCANNER_PORT:-$DEFAULT_PORT}"


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

            PORT="$1"
            ;;

        -h|--help)

            cat <<EOF

$APP $VERSION installer

Usage:

  sudo bash install.sh

  sudo bash install.sh --fresh

  sudo bash install.sh --port 8088

  sudo bash install.sh --no-ufw


Options:

  --fresh
      Remove the previous idontScanner installation,
      database and service configuration.

  --port PORT
      Preferred HTTP port.
      Default: 8088

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


[[ "$PORT" =~ ^[0-9]+$ ]] ||
    die "Invalid port."

(( PORT >= 1024 && PORT <= 65535 )) ||
    die "Port must be between 1024 and 65535."


# ============================================================
# Header
# ============================================================

echo

echo "============================================================"
echo "                 idontScanner $VERSION"
echo "              HTTP SNI / TLS Diagnostic Panel"
echo "============================================================"

echo


# ============================================================
# Operating system
# ============================================================

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


# ============================================================
# Fresh installation
# ============================================================

if [[ "$FRESH" -eq 1 ]]; then

    log "Removing previous idontScanner installation..."


    systemctl stop "$SERVICE" 2>/dev/null || true

    systemctl disable "$SERVICE" 2>/dev/null || true


    rm -f \
        "/etc/systemd/system/${SERVICE}.service"


    systemctl daemon-reload


    rm -rf "$APP_DIR"
    rm -rf "$DATA_DIR"
    rm -rf "$LOG_DIR"


    userdel -r "$SYSTEM_USER" 2>/dev/null || true


    ok "Previous installation removed."

fi


# ============================================================
# Required packages
# ============================================================

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
    iproute2 \
    openssl \
    unzip


PYTHON_BIN="$(command -v python3)"


PYVER="$(
    "$PYTHON_BIN" -c \
        'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")'
)"


if ! "$PYTHON_BIN" -c 'import ensurepip' >/dev/null 2>&1; then

    apt-get install -y \
        "python${PYVER}-venv" \
        2>/dev/null ||
        apt-get install -y python3-venv

fi


"$PYTHON_BIN" -m venv --help >/dev/null 2>&1 ||
    die "Python venv is unavailable."


ok "Python $PYVER ready."


# ============================================================
# Port
# ============================================================

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


# ============================================================
# Detect local project source
# ============================================================

SOURCE_DIR=""


# IMPORTANT:
#
# Do NOT directly use:
#
# ${BASH_SOURCE[0]}
#
# with set -u.
#
# When the script is executed through:
#
# curl ... | sudo bash
#
# there may be no usable BASH_SOURCE entry.
#
# We therefore check it safely.

SCRIPT_DIR=""


if [[ -n "${BASH_SOURCE[0]:-}" ]]; then

    SCRIPT_DIR="$(
        cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null &&
        pwd
    )" || true

fi


# ------------------------------------------------------------
# Direct project
#
# /opt/idontScanner/
#   install.sh
#   requirements.txt
#   app/main.py
# ------------------------------------------------------------

if [[ -n "$SCRIPT_DIR" ]]; then

    if [[ \
        -f "$SCRIPT_DIR/requirements.txt" &&
        -f "$SCRIPT_DIR/app/main.py"
    ]]; then

        SOURCE_DIR="$SCRIPT_DIR"

    fi

fi


# ------------------------------------------------------------
# Nested project
#
# /opt/idontScanner/
#   install.sh
#   idontScanner-2.1.0/
#       requirements.txt
#       app/main.py
# ------------------------------------------------------------

if [[ -z "$SOURCE_DIR" && -n "$SCRIPT_DIR" ]]; then

    if [[ \
        -f "$SCRIPT_DIR/idontScanner-2.1.0/requirements.txt" &&
        -f "$SCRIPT_DIR/idontScanner-2.1.0/app/main.py"
    ]]; then

        SOURCE_DIR="$SCRIPT_DIR/idontScanner-2.1.0"

    fi

fi


# ------------------------------------------------------------
# Search local directories
# ------------------------------------------------------------

if [[ -z "$SOURCE_DIR" && -n "$SCRIPT_DIR" ]]; then

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
            -print \
            2>/dev/null
    )

fi


# ============================================================
# Remote GitHub installation
# ============================================================

# If there is no local source, assume the installer was executed
# through curl | sudo bash and download the project from GitHub.

if [[ -z "$SOURCE_DIR" ]]; then

    log "No local project source detected."

    log "Downloading idontScanner from GitHub..."


    command -v curl >/dev/null 2>&1 ||
        die "curl is required."


    command -v unzip >/dev/null 2>&1 ||
        die "unzip is required."


    TEMP_DIR="$(mktemp -d)"


    cleanup_temp() {
        rm -rf "$TEMP_DIR"
    }


    trap cleanup_temp EXIT


    ARCHIVE_URL="https://github.com/durwinam/idontScanner/archive/refs/heads/main.zip"

    ARCHIVE_FILE="$TEMP_DIR/idontScanner.zip"


    curl \
        -fL \
        --retry 3 \
        --connect-timeout 15 \
        --max-time 300 \
        "$ARCHIVE_URL" \
        -o "$ARCHIVE_FILE" ||
        die "Unable to download idontScanner from GitHub."


    [[ -s "$ARCHIVE_FILE" ]] ||
        die "Downloaded archive is empty."


    unzip -q \
        "$ARCHIVE_FILE" \
        -d "$TEMP_DIR/source" ||
        die "Unable to extract idontScanner archive."


    SOURCE_DIR="$(
        find "$TEMP_DIR/source" \
            -mindepth 1 \
            -maxdepth 1 \
            -type d \
            -print \
            -quit
    )"


    [[ -n "$SOURCE_DIR" ]] ||
        die "Downloaded project directory was not found."


    [[ -f "$SOURCE_DIR/requirements.txt" ]] ||
        die "Downloaded project is missing requirements.txt."


    [[ -f "$SOURCE_DIR/app/main.py" ]] ||
        die "Downloaded project is missing app/main.py."


    ok "Project files downloaded."

fi


# ============================================================
# Final source validation
# ============================================================

[[ -n "$SOURCE_DIR" ]] ||
    die "Unable to locate a valid idontScanner project source."


[[ -f "$SOURCE_DIR/requirements.txt" ]] ||
    die "requirements.txt was not found."


[[ -f "$SOURCE_DIR/app/main.py" ]] ||
    die "app/main.py was not found."


log "Project source detected:"

log "$SOURCE_DIR"


# ============================================================
# Service account
# ============================================================

log "Creating dedicated service account..."


if ! id "$SYSTEM_USER" >/dev/null 2>&1; then

    useradd \
        --system \
        --home-dir "$APP_DIR" \
        --shell /usr/sbin/nologin \
        "$SYSTEM_USER"

fi


mkdir -p \
    "$APP_DIR" \
    "$DATA_DIR" \
    "$LOG_DIR"


# ============================================================
# Copy project
# ============================================================

log "Installing project files..."


# Keep existing runtime configuration if present.
# Do not use --delete-excluded.

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
    -exec rm -rf {} + \
    2>/dev/null || true


find "$APP_DIR" \
    -type f \
    -name "*.pyc" \
    -delete \
    2>/dev/null || true


[[ -f "$APP_DIR/requirements.txt" ]] ||
    die "Installed project is missing requirements.txt."


[[ -f "$APP_DIR/app/main.py" ]] ||
    die "Installed project is missing app/main.py."


# ============================================================
# Python virtual environment
# ============================================================

log "Creating isolated Python environment..."


if [[ ! -x "$APP_DIR/.venv/bin/python" ]]; then

    rm -rf "$APP_DIR/.venv"

    "$PYTHON_BIN" \
        -m venv \
        "$APP_DIR/.venv"

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


# ============================================================
# Python validation
# ============================================================

log "Validating Python application..."


"$APP_DIR/.venv/bin/python" \
    -m compileall \
    -q \
    "$APP_DIR/app" ||
    die "Python source validation failed."


ok "Python source validation passed."


# ============================================================
# Admin credentials
# ============================================================

# When executed as:
#
# curl ... | sudo bash
#
# stdin is occupied by the downloaded shell script.
#
# FD 3 is therefore connected directly to /dev/tty.

if [[ ! -r /dev/tty ]]; then

    die "Interactive terminal (/dev/tty) is required for admin credentials."

fi


exec 3</dev/tty


# ============================================================
# Username
# ============================================================

while true; do

    printf "Admin username [admin]: " >&2


    IFS= read \
        -r \
        -u 3 \
        ADMIN_USER || true


    ADMIN_USER="${ADMIN_USER:-admin}"


    if [[ "$ADMIN_USER" =~ ^[A-Za-z0-9_.-]{3,32}$ ]]; then

        break

    fi


    warn "Username must be 3-32 characters: A-Z, a-z, 0-9, _, ., -."

done


# ============================================================
# Password
# ============================================================

while true; do

    printf \
        "Admin password (minimum 12 characters): " \
        >&2


    IFS= read \
        -r \
        -s \
        -u 3 \
        ADMIN_PASS || true


    printf '\n' >&2


    if (( ${#ADMIN_PASS} < 12 )); then

        warn "Password is too short. Minimum 12 characters."

        unset ADMIN_PASS

        continue

    fi


    printf \
        "Confirm password: " \
        >&2


    IFS= read \
        -r \
        -s \
        -u 3 \
        ADMIN_PASS2 || true


    printf '\n' >&2


    if [[ "$ADMIN_PASS" != "$ADMIN_PASS2" ]]; then

        warn "Passwords do not match."

        unset ADMIN_PASS
        unset ADMIN_PASS2

        continue

    fi


    break

done


# Close terminal descriptor.

exec 3<&-


# ============================================================
# Application secret
# ============================================================

SECRET="$(
    "$APP_DIR/.venv/bin/python" - <<'PY'
import secrets

print(secrets.token_urlsafe(64))
PY
)"


# ============================================================
# Password hash
# ============================================================

PASSWORD_HASH="$(
    "$APP_DIR/.venv/bin/python" - "$ADMIN_PASS" <<'PY'

import hashlib
import secrets
import sys


password = sys.argv[1].encode("utf-8")

salt = secrets.token_bytes(16)

last_error = None


for n in (16384, 8192, 4096):

    try:

        digest = hashlib.scrypt(
            password,
            salt=salt,
            n=n,
            r=8,
            p=1,
            dklen=64,
        )


        print(
            f"scrypt${n}${salt.hex()}${digest.hex()}"
        )


        break


    except ValueError as exc:

        last_error = exc

else:

    raise SystemExit(
        f"Unable to hash password: {last_error}"
    )

PY
)"


unset ADMIN_PASS
unset ADMIN_PASS2


# ============================================================
# Environment
# ============================================================

cat > "$APP_DIR/.env" <<EOF
IDONTSCANNER_VERSION=$VERSION
IDONTSCANNER_SECRET=$SECRET
IDONTSCANNER_HOST=0.0.0.0
IDONTSCANNER_PORT=$PORT
IDONTSCANNER_TIMEOUT=4.0
IDONTSCANNER_DB_PATH=$DATA_DIR/idontscanner.db
EOF


chmod 600 "$APP_DIR/.env"


# ============================================================
# Database
# ============================================================

log "Initializing database and provisioning admin credentials..."


"$APP_DIR/.venv/bin/python" \
    - "$DATA_DIR/idontscanner.db" "$ADMIN_USER" "$PASSWORD_HASH" <<'PY'

import sqlite3
import sys


db, user, password_hash = sys.argv[1:]


connection = sqlite3.connect(db)


connection.executescript(
    """
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS domains (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        label TEXT NOT NULL,
        domain TEXT UNIQUE NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 1,
        is_default INTEGER NOT NULL DEFAULT 0,
        created_at INTEGER NOT NULL
    );

    CREATE TABLE IF NOT EXISTS scans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        started_at INTEGER NOT NULL,
        duration_ms REAL NOT NULL,
        total INTEGER NOT NULL,
        ok INTEGER NOT NULL
    );

    CREATE TABLE IF NOT EXISTS results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        scan_id INTEGER NOT NULL,
        domain_id INTEGER NOT NULL,
        status TEXT NOT NULL,
        latency_ms REAL,
        tls_version TEXT,
        cert_subject TEXT,
        error TEXT,
        FOREIGN KEY(scan_id) REFERENCES scans(id),
        FOREIGN KEY(domain_id) REFERENCES domains(id)
    );
    """
)


connection.execute(
    """
    INSERT OR REPLACE INTO settings(key, value)
    VALUES('username', ?)
    """,
    (user,),
)


connection.execute(
    """
    INSERT OR REPLACE INTO settings(key, value)
    VALUES('password', ?)
    """,
    (password_hash,),
)


connection.commit()

connection.close()

PY


# ============================================================
# Permissions
# ============================================================

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


# ============================================================
# Systemd service
# ============================================================

log "Installing systemd service..."


cat > "/etc/systemd/system/${SERVICE}.service" <<EOF
[Unit]
Description=idontScanner Web Panel
After=network-online.target
Wants=network-online.target

[Service]
Type=simple

User=$SYSTEM_USER
Group=$SYSTEM_USER

WorkingDirectory=$APP_DIR

EnvironmentFile=$APP_DIR/.env

ExecStart=$APP_DIR/.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT

Restart=on-failure
RestartSec=3

NoNewPrivileges=true
PrivateTmp=true

ProtectSystem=strict
ProtectHome=true

ReadWritePaths=$APP_DIR $DATA_DIR $LOG_DIR

RestrictSUIDSGID=true
LockPersonality=true

[Install]
WantedBy=multi-user.target
EOF


chmod 644 \
    "/etc/systemd/system/${SERVICE}.service"


# ============================================================
# CLI
# ============================================================

if [[ -f "$APP_DIR/idontscanner-cli" ]]; then

    chmod 755 \
        "$APP_DIR/idontscanner-cli"


    install \
        -m 755 \
        "$APP_DIR/idontscanner-cli" \
        /usr/local/bin/idontScanner

fi


# ============================================================
# Start service
# ============================================================

systemctl daemon-reload


systemctl enable \
    "$SERVICE" \
    >/dev/null


systemctl restart \
    "$SERVICE"


sleep 2


# ============================================================
# Service check
# ============================================================

if ! systemctl is-active --quiet "$SERVICE"; then

    journalctl \
        -u "$SERVICE" \
        -n 100 \
        --no-pager \
        || true


    die "Service failed to start."

fi


ok "idontScanner service is running."


# ============================================================
# HTTP health check
# ============================================================

log "Checking HTTP service..."


HEALTH_OK=0


for _ in $(seq 1 30); do

    if curl \
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
        -u "$SERVICE" \
        -n 100 \
        --no-pager \
        || true


    die \
        "HTTP health check failed on 127.0.0.1:${PORT}."

fi


ok "HTTP health check passed."


# ============================================================
# UFW
# ============================================================

if \
    [[ "$NO_UFW" -eq 0 ]] &&
    command -v ufw >/dev/null 2>&1 &&
    ufw status 2>/dev/null |
        grep -q '^Status: active'
then

    ufw allow \
        "${PORT}/tcp" \
        >/dev/null


    ok "UFW rule added for TCP/$PORT"

fi


# ============================================================
# Server IP
# ============================================================

IP="$(
    hostname -I 2>/dev/null |
    awk '{print $1}'
)"


IP="${IP:-127.0.0.1}"


# ============================================================
# Installation complete
# ============================================================

echo

echo "============================================================"
echo "              INSTALLATION COMPLETE"
echo "============================================================"

echo
echo " Version   : $VERSION"
echo " Status    : RUNNING"
echo " Protocol  : HTTP"
echo " Port      : $PORT/tcp"
echo " Panel     : http://${IP}:${PORT}/"
echo " Login     : http://${IP}:${PORT}/login/"
echo " Username  : $ADMIN_USER"
echo " Password  : [hidden]"

echo
echo " Service   : systemctl status $SERVICE"
echo " Logs      : journalctl -u $SERVICE -f"

echo
echo "============================================================"

echo
echo -e "${GREEN}idontScanner $VERSION is ready.${RESET}"

echo
