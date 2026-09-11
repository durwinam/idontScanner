#!/usr/bin/env bash

set -Eeuo pipefail

trap 'echo "[ERROR] Installation failed at line ${LINENO}." >&2' ERR


APP="idontScanner"
VERSION="v1.0.0"
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
    printf '%b%s%b %s\n' "$cyan" "[idontScanner]" "$reset" "$*"
}

ok() {
    printf '%b%s%b %s\n' "$green" "[OK]" "$reset" "$*"
}

warn() {
    printf '%b%s%b %s\n' "$yellow" "[WARN]" "$reset" "$*"
}

die() {
    printf '%b%s%b %s\n' "$red" "[ERROR]" "$reset" "$*" >&2
    exit 1
}


[[ $EUID -eq 0 ]] || die "Run as root: sudo bash install.sh"
command -v systemctl >/dev/null || die "systemd is required."
command -v apt-get >/dev/null || die "Debian/Ubuntu with apt-get is required."


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
            PORT="${1:-}"
            ;;
        -h|--help)
            cat <<EOF
idontScanner $VERSION installer

Usage:
  sudo bash install.sh [--fresh] [--port PORT] [--no-ufw]

  --fresh       Completely remove the previous idontScanner data/service first.
  --port PORT   Preferred HTTP port (default: 8088).
  --no-ufw      Do not add a UFW rule.
EOF
            exit 0
            ;;
        *)
            die "Unknown option: $1"
            ;;
    esac

    shift
done


[[ "$PORT" =~ ^[0-9]+$ ]] || die "Invalid port."
(( PORT >= 1024 && PORT <= 65535 )) || die "Port must be between 1024 and 65535."


echo
echo "============================================================"
echo "                 idontScanner $VERSION"
echo "              HTTP SNI / TLS Diagnostic Panel"
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


if [[ "$FRESH" -eq 1 ]]; then
    log "Removing previous installation and ALL local data..."

    systemctl stop "$SERVICE" 2>/dev/null || true
    systemctl disable "$SERVICE" 2>/dev/null || true

    rm -f "/etc/systemd/system/${SERVICE}.service"

    systemctl daemon-reload

    rm -rf "$APP_DIR" "$DATA_DIR" "$LOG_DIR"
    userdel -r "$SYSTEM_USER" 2>/dev/null || true

    ok "Previous installation removed."
fi


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
    openssl


PYTHON_BIN="$(command -v python3)"
PYVER="$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"

if ! "$PYTHON_BIN" -c 'import ensurepip' >/dev/null 2>&1; then
    apt-get install -y "python${PYVER}-venv" 2>/dev/null ||
        apt-get install -y python3-venv
fi

"$PYTHON_BIN" -m venv --help >/dev/null ||
    die "Python venv is unavailable."

ok "Python $PYVER ready."


log "Selecting an available HTTP port..."

while ss -H -lnt 2>/dev/null |
    awk '{print $4}' |
    grep -Eq "(:|\])${PORT}$"; do

    warn "TCP/$PORT is already in use; trying $((PORT+1))."

    PORT=$((PORT+1))

    (( PORT <= 65535 )) || die "No free TCP port found."
done

ok "HTTP port selected: $PORT"


SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# When launched remotely with `bash <(curl ...)`, the script is not inside
# the project tree. In that case, download the matching repository archive
# and continue with the exact same installation flow.
if [[ ! -f "$SOURCE_DIR/requirements.txt" || ! -f "$SOURCE_DIR/app/main.py" ]]; then
    command -v curl >/dev/null 2>&1 || die "curl is required for remote installation."
    command -v unzip >/dev/null 2>&1 || {
        log "Installing unzip for remote installation..."
        apt-get update -y
        apt-get install -y unzip
    }

    TEMP_DIR="$(mktemp -d)"
    trap 'rm -rf "$TEMP_DIR"' EXIT

    ARCHIVE_URL="https://github.com/durwinam/idontScanner/archive/refs/heads/main.zip"
    ARCHIVE="$TEMP_DIR/idontScanner.zip"

    log "Downloading idontScanner from GitHub..."
    curl -fL --retry 3 --connect-timeout 10 "$ARCHIVE_URL" -o "$ARCHIVE" ||
        die "Unable to download the idontScanner repository."

    unzip -q "$ARCHIVE" -d "$TEMP_DIR/source"
    SOURCE_DIR="$(find "$TEMP_DIR/source" -mindepth 1 -maxdepth 1 -type d -print -quit)"

    [[ -n "$SOURCE_DIR" && -f "$SOURCE_DIR/requirements.txt" && -f "$SOURCE_DIR/app/main.py" ]] ||
        die "Downloaded repository is incomplete."

    ok "Project files downloaded."
fi


log "Creating dedicated service account..."

if ! id "$SYSTEM_USER" >/dev/null 2>&1; then
    useradd \
        --system \
        --home-dir "$APP_DIR" \
        --shell /usr/sbin/nologin \
        "$SYSTEM_USER"
fi


mkdir -p "$APP_DIR" "$DATA_DIR" "$LOG_DIR"

cp -a "$SOURCE_DIR"/. "$APP_DIR"/

find "$APP_DIR" -type d -name __pycache__ -prune -exec rm -rf {} +
find "$APP_DIR" -type f -name '*.pyc' -delete


log "Creating isolated Python environment..."

rm -rf "$APP_DIR/.venv"

"$PYTHON_BIN" -m venv "$APP_DIR/.venv"

"$APP_DIR/.venv/bin/python" -m pip install \
    --disable-pip-version-check \
    --no-cache-dir \
    --upgrade pip wheel

"$APP_DIR/.venv/bin/python" -m pip install \
    --disable-pip-version-check \
    --no-cache-dir \
    -r "$APP_DIR/requirements.txt"


read -rp "Admin username [admin]: " ADMIN_USER
ADMIN_USER="${ADMIN_USER:-admin}"

[[ "$ADMIN_USER" =~ ^[A-Za-z0-9_.-]{3,32}$ ]] ||
    die "Username must be 3-32 characters: A-Z, a-z, 0-9, _, ., -."


while true; do
    read -rsp "Admin password (minimum 12 characters): " ADMIN_PASS
    echo

    (( ${#ADMIN_PASS} >= 12 )) || {
        warn "Password is too short."
        continue
    }

    read -rsp "Confirm password: " ADMIN_PASS2
    echo

    [[ "$ADMIN_PASS" == "$ADMIN_PASS2" ]] && break

    warn "Passwords do not match."
done


SECRET="$("$APP_DIR/.venv/bin/python" - <<'PY'
import secrets

print(secrets.token_urlsafe(64))
PY
)"


# Generate the password hash without importing the application package.
# The app uses the same scrypt format and has its own low-memory fallback.
PASSWORD_HASH="$("$APP_DIR/.venv/bin/python" - "$ADMIN_PASS" <<'PY'
import hashlib
import secrets
import sys


password = sys.argv[1].encode("utf-8")
salt = secrets.token_bytes(16)
last = None

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

        print(f"scrypt${n}${salt.hex()}${digest.hex()}")
        break

    except ValueError as e:
        last = e

else:
    raise SystemExit(f"Unable to hash password: {last}")
PY
)"

unset ADMIN_PASS ADMIN_PASS2


cat > "$APP_DIR/.env" <<EOF
IDONTSCANNER_VERSION=$VERSION
IDONTSCANNER_SECRET=$SECRET
IDONTSCANNER_HOST=0.0.0.0
IDONTSCANNER_PORT=$PORT
IDONTSCANNER_TIMEOUT=4.0
IDONTSCANNER_DB_PATH=$DATA_DIR/idontscanner.db
EOF

chmod 600 "$APP_DIR/.env"


log "Initializing database and provisioning admin credentials..."

"$APP_DIR/.venv/bin/python" - "$DATA_DIR/idontscanner.db" "$ADMIN_USER" "$PASSWORD_HASH" <<'PY'
import sqlite3
import sys
import time


db, user, ph = sys.argv[1:]

con = sqlite3.connect(db)

con.executescript(
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

con.execute(
    "INSERT OR REPLACE INTO settings(key,value) VALUES('username',?)",
    (user,),
)

con.execute(
    "INSERT OR REPLACE INTO settings(key,value) VALUES('password',?)",
    (ph,),
)

con.commit()
con.close()
PY


chown -R "$SYSTEM_USER:$SYSTEM_USER" "$APP_DIR" "$DATA_DIR" "$LOG_DIR"

chmod 750 "$APP_DIR" "$DATA_DIR" "$LOG_DIR"
chmod 600 "$APP_DIR/.env"


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

chmod 644 "/etc/systemd/system/${SERVICE}.service"


systemctl daemon-reload
systemctl enable "$SERVICE" >/dev/null
systemctl restart "$SERVICE"

sleep 2


if ! systemctl is-active --quiet "$SERVICE"; then
    journalctl -u "$SERVICE" -n 80 --no-pager || true
    die "Service failed to start."
fi


curl -fsS "http://127.0.0.1:${PORT}/" -o /dev/null || {
    journalctl -u "$SERVICE" -n 80 --no-pager || true
    die "HTTP health check failed."
}


if [[ "$NO_UFW" -eq 0 ]] &&
    command -v ufw >/dev/null 2>&1 &&
    ufw status 2>/dev/null | grep -q "Status: active"; then

    ufw allow "${PORT}/tcp" >/dev/null
    ok "UFW rule added for TCP/$PORT"
fi


IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
IP="${IP:-127.0.0.1}"


echo
echo "============================================================"
echo "              INSTALLATION COMPLETE"
echo "============================================================"
echo " Version   : $VERSION"
echo " Status    : RUNNING"
echo " Protocol  : HTTP"
echo " Port      : $PORT/tcp"
echo " Panel     : http://${IP}:${PORT}/"
echo " Login     : http://${IP}:${PORT}/login/"
echo " Username  : $ADMIN_USER"
echo " Password  : [hidden]"
echo " Service   : systemctl status $SERVICE"
echo " Logs      : journalctl -u $SERVICE -f"
echo "============================================================"
echo
