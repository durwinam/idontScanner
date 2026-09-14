#!/usr/bin/env bash
set -Eeuo pipefail

APP_NAME="idontScanner"
SERVICE_NAME="idontscanner"
APP_DIR="/opt/idontScanner"
ENV_FILE="$APP_DIR/.env"
REPO="https://github.com/durwinam/idontScanner"
BRANCH="main"
RAW_BASE="https://raw.githubusercontent.com/durwinam/idontScanner/main"
ARCHIVE_URL="https://github.com/durwinam/idontScanner/archive/refs/heads/${BRANCH}.tar.gz"

log() { printf '\033[36m[idontScanner]\033[0m %s\n' "$*"; }
ok() { printf '\033[32m[OK]\033[0m %s\n' "$*"; }
warn() { printf '\033[33m[WARN]\033[0m %s\n' "$*" >&2; }
die() { printf '\033[31m[ERROR]\033[0m %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Run as root: sudo bash update.sh"
[[ -d "$APP_DIR" ]] || die "idontScanner is not installed in $APP_DIR"
command -v curl >/dev/null 2>&1 || die "curl is required."
command -v rsync >/dev/null 2>&1 || die "rsync is required."

service_port() {
    local port=""

    if [[ -f "/var/lib/idontscanner/runtime-port" ]]; then
        port="$(tr -d '[:space:]' < "/var/lib/idontscanner/runtime-port")"
    fi

    if [[ ! "$port" =~ ^[0-9]+$ ]] && [[ -f "$ENV_FILE" ]]; then
        port="$(sed -n 's/^IDONTSCANNER_PORT=//p' "$ENV_FILE" | tail -n1)"
    fi

    if [[ ! "$port" =~ ^[0-9]+$ ]]; then
        port="$(systemctl cat "$SERVICE_NAME" 2>/dev/null \
            | sed -n 's/.*--port \([0-9][0-9]*\).*/\1/p' \
            | tail -n1)"
    fi

    printf '%s\n' "${port:-8088}"
}

set_env_port() {
    local port="$1"
    [[ "$port" =~ ^[0-9]+$ ]] || return 1

    if grep -q '^IDONTSCANNER_PORT=' "$ENV_FILE" 2>/dev/null; then
        sed -i "s/^IDONTSCANNER_PORT=.*/IDONTSCANNER_PORT=$port/" "$ENV_FILE"
    else
        printf 'IDONTSCANNER_PORT=%s\n' "$port" >> "$ENV_FILE"
    fi
}

health_check() {
    local port="${1:-}"
    [[ -n "$port" ]] || return 1

    for _ in $(seq 1 30); do
        if curl -fsS --connect-timeout 1 --max-time 3 \
            "http://127.0.0.1:${port}/login/" >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
    done

    return 1
}

catalog_count() {
    local file="/var/lib/idontscanner/target_catalog.txt"
    if [[ ! -f "$file" ]]; then
        printf '0\n'
        return
    fi

    # Count the same domains the Python catalog/runtime validator accepts.
    # Do not use a shell regex here: it incorrectly rejects valid IDNA/punycode
    # TLDs (for example xn--...) and made a real 3,000-line catalog appear as
    # only ~2,300 domains during update.
    if [[ -x "$APP_DIR/.venv/bin/python" && -f "$APP_DIR/tools/sync_target_catalog.py" ]]; then
        "$APP_DIR/.venv/bin/python" - "$file" <<'PYCOUNT'
import sys
from pathlib import Path
from tools.sync_target_catalog import valid_domain
path = Path(sys.argv[1])
seen = set()
for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
    d = raw.strip().lower().rstrip(".")
    if valid_domain(d):
        seen.add(d)
print(len(seen))
PYCOUNT
        return
    fi

    awk 'NF {gsub(/\r/, ""); if ($0 ~ /^[^[:space:]\/:@]+\.[^[:space:]\/:@]+$/) print tolower($0)}' "$file" 2>/dev/null | sort -u | wc -l | tr -d ' '
}

refresh_catalog() {
    local catalog="/var/lib/idontscanner/target_catalog.txt"
    mkdir -p /var/lib/idontscanner
    if id idontscanner >/dev/null 2>&1; then
        chown idontscanner:idontscanner /var/lib/idontscanner
    fi

    local before
    before="$(catalog_count)"
    if (( before >= 3000 )); then
        ok "Target catalog is already ready: ${before}/3000 domains."
        return 0
    fi

    log "Refreshing the 3,000-target benchmark catalog (${before}/3000 currently available)..."
    if [[ ! -x "$APP_DIR/.venv/bin/python" || ! -f "$APP_DIR/tools/sync_target_catalog.py" ]]; then
        warn "Catalog sync files are not available in this installation."
        return 1
    fi

    if runuser -u idontscanner -- env PYTHONPATH="$APP_DIR" \
        "$APP_DIR/.venv/bin/python" "$APP_DIR/tools/sync_target_catalog.py" \
        --output "$catalog" --count 3000; then
        chown idontscanner:idontscanner "$catalog" "$catalog.meta.json" 2>/dev/null || true
        local after
        after="$(catalog_count)"
        if (( after >= 3000 )); then
            ok "3,000 benchmark targets are ready (${after}/3000)."
            return 0
        fi
        warn "Catalog sync returned success but only ${after}/3000 valid domains are present."
        return 1
    fi

    local after
    after="$(catalog_count)"
    warn "Target catalog refresh failed; ${after}/3000 domains remain available."
    return 1
}

TMP_DIR="$(mktemp -d /tmp/idontscanner-update.XXXXXX)"
BACKUP_DIR="$(mktemp -d /tmp/idontscanner-env.XXXXXX)"
cleanup() {
    rm -rf "$TMP_DIR" "$BACKUP_DIR"
}
trap cleanup EXIT

log "Downloading the latest source from GitHub..."
curl -fL --retry 3 --retry-delay 2 --connect-timeout 10 \
    "$ARCHIVE_URL" -o "$TMP_DIR/source.tar.gz" \
    || die "Could not download the latest source."

tar -xzf "$TMP_DIR/source.tar.gz" -C "$TMP_DIR" \
    || die "Downloaded source archive is invalid."

SOURCE_DIR="$(find "$TMP_DIR" -mindepth 1 -maxdepth 1 -type d -print -quit)"
[[ -f "$SOURCE_DIR/VERSION" ]] || die "The downloaded source is invalid."

LATEST_VERSION="$(tr -d '[:space:]' < "$SOURCE_DIR/VERSION")"
[[ "$LATEST_VERSION" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] \
    || die "Invalid release version: $LATEST_VERSION"

INSTALLED_VERSION="unknown"
[[ -f "$APP_DIR/VERSION" ]] && \
    INSTALLED_VERSION="$(tr -d '[:space:]' < "$APP_DIR/VERSION")"

printf 'Installed: %s\n' "$INSTALLED_VERSION"
printf 'Available: %s\n' "$LATEST_VERSION"

version_is_newer() {
    [[ "$1" =~ ^v([0-9]+)\.([0-9]+)\.([0-9]+)$ ]] || return 1
    local remote_major="${BASH_REMATCH[1]}"
    local remote_minor="${BASH_REMATCH[2]}"
    local remote_patch="${BASH_REMATCH[3]}"
    [[ "$2" =~ ^v([0-9]+)\.([0-9]+)\.([0-9]+)$ ]] || return 0
    local local_major="${BASH_REMATCH[1]}"
    local local_minor="${BASH_REMATCH[2]}"
    local local_patch="${BASH_REMATCH[3]}"

    (( remote_major > local_major )) ||
    { (( remote_major == local_major && remote_minor > local_minor )); } ||
    { (( remote_major == local_major && remote_minor == local_minor && remote_patch > local_patch )); }
}

if [[ "$INSTALLED_VERSION" == "$LATEST_VERSION" ]]; then
    ok "The application source is already at $LATEST_VERSION."
    # Do not exit here: older installations may have an incomplete/missing
    # 3,000-domain benchmark catalog. An update command must repair that
    # state even when the application version itself is already current.
    refresh_catalog || true
    ok "No application files needed updating."
    exit 0
fi

if ! version_is_newer "$LATEST_VERSION" "$INSTALLED_VERSION"; then
    die "The available version ($LATEST_VERSION) is not newer than the installed version ($INSTALLED_VERSION)."
fi

if [[ -f "$ENV_FILE" ]]; then
    cp -a "$ENV_FILE" "$BACKUP_DIR/.env"
fi

PORT="$(service_port)"
PORT="${PORT:-8088}"

log "Stopping the panel..."
systemctl stop "$SERVICE_NAME" || true

log "Replacing application files while preserving local data..."
rsync -a --delete \
    --exclude='.env' \
    --exclude='.venv/' \
    --exclude='data/' \
    --exclude='*.db' \
    "$SOURCE_DIR/" "$APP_DIR/" \
    || die "Application files could not be updated."

# Keep the updater executable even when an archive loses file mode metadata.
if [[ -f "$SOURCE_DIR/update.sh" ]]; then
    install -m 755 "$SOURCE_DIR/update.sh" "$APP_DIR/update.sh" \
        || die "Could not install update.sh"
else
    curl -fL --retry 3 --connect-timeout 10 \
        "$RAW_BASE/update.sh" -o "$APP_DIR/update.sh" \
        || die "Could not restore update.sh"
    chmod 755 "$APP_DIR/update.sh"
fi

if [[ -f "$BACKUP_DIR/.env" ]]; then
    cp -f "$BACKUP_DIR/.env" "$APP_DIR/.env"
fi

set_env_port "$PORT"

"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt" \
    || die "Python dependencies could not be updated."

chmod 600 "$APP_DIR/.env" 2>/dev/null || true
chown -R idontscanner:idontscanner "$APP_DIR"

if [[ -f "$APP_DIR/systemd/idontscanner.service" ]]; then
    install -m 644 "$APP_DIR/systemd/idontscanner.service" \
        "/etc/systemd/system/${SERVICE_NAME}.service"
fi

systemctl daemon-reload

refresh_catalog || log "Target catalog refresh failed; preserving the previous catalog."

log "Running database migrations..."
runuser -u idontscanner -- env PYTHONPATH="$APP_DIR" \
    "$APP_DIR/.venv/bin/python" -c \
    'from app.database import init_db; init_db()' \
    || die "Database migration failed."

install -m 755 "$APP_DIR/idontscanner-cli" /usr/local/bin/idontScanner

systemctl daemon-reload
systemctl start "$SERVICE_NAME"

PORT="$(service_port)"

if ! health_check "$PORT"; then
    journalctl -u "$SERVICE_NAME" -n 80 --no-pager
    die "Update completed but the panel did not become ready."
fi

ok "Updated from $INSTALLED_VERSION to $LATEST_VERSION."
printf 'Panel: http://%s:%s/\n' "$(hostname -I 2>/dev/null | awk '{print $1}')" "$PORT"
