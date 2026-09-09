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

C=$'\033[36m'; G=$'\033[32m'; Y=$'\033[33m'; R=$'\033[31m'; N=$'\033[0m'
log(){ echo -e "${C}[idontScanner]${N} $*"; }
ok(){ echo -e "${G}[OK]${N} $*"; }
warn(){ echo -e "${Y}[WARN]${N} $*"; }
die(){ echo -e "${R}[ERROR]${N} $*"; exit 1; }
trap 'die "Installation failed at line ${LINENO}."' ERR

[[ $EUID -eq 0 ]] || die "Run as root: sudo bash install.sh"
command -v apt-get >/dev/null || die "Debian/Ubuntu is required."

FRESH=0
NO_UFW=0
REQUESTED_PORT=$DEFAULT_PORT
while [[ $# -gt 0 ]]; do
  case "$1" in
    --fresh) FRESH=1 ;;
    --no-ufw) NO_UFW=1 ;;
    --port) shift; [[ "${1:-}" =~ ^[0-9]+$ ]] || die "--port requires a number"; REQUESTED_PORT="$1" ;;
    -h|--help)
      cat <<EOF
$APP_NAME $VERSION

Usage: sudo bash install.sh [--fresh] [--port PORT] [--no-ufw]

  --fresh      Remove the previous installation, database and settings.
  --port PORT  Preferred HTTP port. Defaults to 8088 and auto-increments if busy.
  --no-ufw     Do not change UFW rules.
EOF
      exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
  shift
done

. /etc/os-release
case "${ID:-}" in ubuntu|debian) ;; *) die "Supported OS: Debian/Ubuntu" ;; esac
export DEBIAN_FRONTEND=noninteractive

echo
echo "============================================================"
echo "                 idontScanner $VERSION"
echo "        Secure HTTP SNI / TLS Diagnostic Panel"
echo "============================================================"
echo

log "Installing required system packages..."
apt-get update -y
apt-get install -y python3 python3-pip python3-venv python3-dev curl ca-certificates openssl unzip iproute2
PYTHON_BIN="$(command -v python3)"
PY_VERSION="$($PYTHON_BIN -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
if ! "$PYTHON_BIN" -c 'import ensurepip' >/dev/null 2>&1; then
  apt-get install -y "python${PY_VERSION}-venv" 2>/dev/null || apt-get install -y python3-venv
fi
ok "Python $PY_VERSION ready"

if [[ $FRESH -eq 1 ]]; then
  log "Removing previous installation and all local data..."
  systemctl stop "$SERVICE_NAME" 2>/dev/null || true
  systemctl disable "$SERVICE_NAME" 2>/dev/null || true
  rm -f "/etc/systemd/system/${SERVICE_NAME}.service"
  systemctl daemon-reload
  rm -rf "$APP_DIR" "$DATA_DIR" "$LOG_DIR"
  userdel -r "$SYSTEM_USER" 2>/dev/null || true
  ok "Previous installation removed"
fi

log "Creating dedicated service account..."
if ! id "$SYSTEM_USER" >/dev/null 2>&1; then
  useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$SYSTEM_USER"
fi
mkdir -p "$APP_DIR" "$DATA_DIR" "$LOG_DIR"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cp -a "$SOURCE_DIR"/. "$APP_DIR"/
find "$APP_DIR" -type d -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true
find "$APP_DIR" -type f -name '*.pyc' -delete 2>/dev/null || true
chown -R "$SYSTEM_USER:$SYSTEM_USER" "$APP_DIR" "$DATA_DIR" "$LOG_DIR"
chmod 750 "$APP_DIR" "$DATA_DIR" "$LOG_DIR"

log "Creating isolated Python environment..."
if [[ ! -x "$APP_DIR/.venv/bin/python" ]]; then
  "$PYTHON_BIN" -m venv "$APP_DIR/.venv"
fi
"$APP_DIR/.venv/bin/python" -m pip install --upgrade pip wheel
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"
chown -R "$SYSTEM_USER:$SYSTEM_USER" "$APP_DIR/.venv"

read -rp "Admin username [admin]: " ADMIN_USER
ADMIN_USER="${ADMIN_USER:-admin}"
[[ "$ADMIN_USER" =~ ^[A-Za-z0-9_.-]{3,32}$ ]] || die "Invalid username."
while true; do
  read -rsp "Admin password (minimum 8 characters): " ADMIN_PASS; echo
  [[ ${#ADMIN_PASS} -ge 8 ]] || { warn "Password is too short."; continue; }
  read -rsp "Confirm password: " ADMIN_PASS2; echo
  [[ "$ADMIN_PASS" == "$ADMIN_PASS2" ]] && break
  warn "Passwords do not match."
done

SECRET="$($APP_DIR/.venv/bin/python - <<'PY'
import secrets
print(secrets.token_urlsafe(48))
PY
)"

cat > "$APP_DIR/.env" <<EOF
IDONTSCANNER_VERSION=$VERSION
IDONTSCANNER_SECRET=$SECRET
IDONTSCANNER_DATA_DIR=$DATA_DIR
EOF
chmod 600 "$APP_DIR/.env"
chown "$SYSTEM_USER:$SYSTEM_USER" "$APP_DIR/.env"

log "Initializing database and credential store..."
cd "$APP_DIR"
ADMIN_USER="$ADMIN_USER" ADMIN_PASS="$ADMIN_PASS" PYTHONPATH="$APP_DIR" "$APP_DIR/.venv/bin/python" - <<'PY'
import os
from app.main import init_db, set_setting
from app.auth import hash_password
init_db()
set_setting("username", os.environ["ADMIN_USER"])
set_setting("password", hash_password(os.environ["ADMIN_PASS"]))
PY
unset ADMIN_PASS ADMIN_PASS2
chown -R "$SYSTEM_USER:$SYSTEM_USER" "$DATA_DIR"
chmod 700 "$DATA_DIR"

PORT="$REQUESTED_PORT"
while ss -lntH 2>/dev/null | awk '{print $4}' | grep -Eq "(:|\])${PORT}$"; do
  PORT=$((PORT+1))
  [[ $PORT -le 65535 ]] || die "No free TCP port found."
done

log "Installing systemd service on HTTP port $PORT..."
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
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=true
ReadWritePaths=$APP_DIR $DATA_DIR $LOG_DIR

[Install]
WantedBy=multi-user.target
EOF
chmod 644 "/etc/systemd/system/${SERVICE_NAME}.service"
systemctl daemon-reload
systemctl enable "$SERVICE_NAME" >/dev/null
systemctl restart "$SERVICE_NAME"
sleep 2
systemctl is-active --quiet "$SERVICE_NAME" || { journalctl -u "$SERVICE_NAME" -n 50 --no-pager; die "Service failed to start."; }

curl -fsS "http://127.0.0.1:${PORT}/login/" >/dev/null || { journalctl -u "$SERVICE_NAME" -n 50 --no-pager; die "HTTP health check failed."; }

if [[ $NO_UFW -eq 0 ]] && command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q '^Status: active'; then
  ufw allow "${PORT}/tcp" >/dev/null
  ok "UFW rule added for TCP/$PORT"
fi

SERVER_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
SERVER_IP="${SERVER_IP:-127.0.0.1}"
echo
echo "============================================================"
echo "                  INSTALLATION COMPLETE"
echo "============================================================"
echo " Version       : $VERSION"
echo " Protocol      : HTTP (no SSL)"
echo " Service       : $SERVICE_NAME"
echo " Status        : RUNNING"
echo " Port          : $PORT"
echo " Panel         : http://${SERVER_IP}:${PORT}/"
echo " Login         : http://${SERVER_IP}:${PORT}/login/"
echo " Username      : $ADMIN_USER"
echo " Password      : [hidden]"
echo " Scheduler     : OFF by default"
echo " Telegram      : Optional / Settings"
echo "============================================================"
echo
echo -e "${G}idontScanner is ready.${N}"
