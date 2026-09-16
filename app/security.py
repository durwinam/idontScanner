"""Authentication-adjacent request and input helpers."""

from __future__ import annotations

import ipaddress
import secrets
import socket
import time

from fastapi import Request

from app.config import SESSION_RETENTION
from app.database import db, get_setting

def csrf(request: Request) -> str:
    token = request.session.get('csrf')
    if not token:
        token = secrets.token_urlsafe(32)
        request.session['csrf'] = token
    return token


def require_auth(request: Request) -> bool:
    return bool(request.session.get('auth'))


def server_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('1.1.1.1', 53))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return socket.gethostbyname(socket.gethostname())


def valid_domain(value: str):
    """Normalize a DNS hostname and reject unsupported input."""
    value = value.strip().lower().rstrip(".")

    if not value or len(value) > 253 or "://" in value or "/" in value or "@" in value:
        return None

    try:
        ipaddress.ip_address(value)
        return None
    except ValueError:
        pass

    labels = value.split(".")
    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789-")
    invalid = any(
        not label
        or len(label) > 63
        or label.startswith("-")
        or label.endswith("-")
        or any(char not in allowed for char in label)
        for label in labels
    )
    return None if len(labels) < 2 or invalid else value


def device_label(user_agent: str):
    ua = user_agent.lower()
    if 'iphone' in ua:
        platform = 'iPhone'
    elif 'ipad' in ua:
        platform = 'iPad'
    elif 'android' in ua:
        platform = 'Android'
    elif 'windows' in ua:
        platform = 'Windows'
    elif 'mac os' in ua or 'macintosh' in ua:
        platform = 'macOS'
    elif 'linux' in ua:
        platform = 'Linux'
    else:
        platform = 'Unknown device'
    if 'edg/' in ua:
        browser = 'Edge'
    elif 'chrome/' in ua and 'chromium' not in ua:
        browser = 'Chrome'
    elif 'firefox/' in ua:
        browser = 'Firefox'
    elif 'safari/' in ua and 'chrome/' not in ua:
        browser = 'Safari'
    else:
        browser = 'Browser'
    return f'{browser} • {platform}'


def remember_session(request: Request):
    """Store the latest authenticated device and retain only three sessions."""
    ip = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "unknown")[:500]
    device = device_label(user_agent)

    with db() as con:
        con.execute(
            """
            INSERT INTO sessions(ip, user_agent, device, last_seen)
            VALUES (?, ?, ?, ?)
            """,
            (ip, user_agent, device, int(time.time())),
        )
        con.execute(
            """
            DELETE FROM sessions
            WHERE id NOT IN (
                SELECT id
                FROM sessions
                ORDER BY id DESC
                LIMIT 3
            )
            """
        )


# --- Authentication hardening / TOTP ---
import base64
import hashlib
import hmac
import struct
from urllib.parse import quote


def client_ip(request) -> str:
    return str(getattr(getattr(request, "client", None), "host", None) or "unknown")[:255]


def auth_state(ip: str) -> dict:
    with db() as con:
        row = con.execute(
            "SELECT failed_count, blocked_until, permanent FROM auth_attempts WHERE ip=?",
            (ip,),
        ).fetchone()
    return dict(row) if row else {"failed_count": 0, "blocked_until": 0, "permanent": 0}


def auth_blocked(ip: str) -> bool:
    state = auth_state(ip)
    return bool(state["permanent"] or int(state["blocked_until"] or 0) > int(time.time()))


def record_failed_login(ip: str) -> dict:
    now = int(time.time())
    with db() as con:
        row = con.execute("SELECT failed_count FROM auth_attempts WHERE ip=?", (ip,)).fetchone()
        count = (int(row[0]) if row else 0) + 1
        blocked_until = 0
        permanent = 0
        if count == 3:
            blocked_until = now + 5 * 60
        elif count == 4:
            blocked_until = now + 20 * 60
        elif count >= 5:
            permanent = 1
        con.execute(
            """INSERT INTO auth_attempts(ip, failed_count, blocked_until, permanent, updated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(ip) DO UPDATE SET failed_count=excluded.failed_count,
               blocked_until=excluded.blocked_until, permanent=excluded.permanent,
               updated_at=excluded.updated_at""",
            (ip, count, blocked_until, permanent, now),
        )
    return {"failed_count": count, "blocked_until": blocked_until, "permanent": permanent}


def clear_failed_login(ip: str) -> None:
    with db() as con:
        con.execute("DELETE FROM auth_attempts WHERE ip=?", (ip,))


def new_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _secret_bytes(secret: str) -> bytes:
    return base64.b32decode(secret.upper() + "=" * (-len(secret) % 8), casefold=True)


def totp_code(secret: str, for_time: int | None = None, digits: int = 6) -> str:
    counter = int((for_time or int(time.time())) // 30)
    digest = hmac.new(_secret_bytes(secret), struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % (10 ** digits)).zfill(digits)


def verify_totp(secret: str, code: str, window: int = 1) -> bool:
    if not secret:
        return False
    clean = "".join(ch for ch in str(code) if ch.isdigit())
    if len(clean) != 6:
        return False
    now = int(time.time())
    return any(hmac.compare_digest(totp_code(secret, now + step * 30), clean) for step in range(-window, window + 1))


def totp_enabled() -> bool:
    return get_setting("totp_enabled", "0") == "1" and bool(get_setting("totp_secret", ""))


def provisioning_uri(username: str, secret: str) -> str:
    issuer = "idontScanner"
    label = f"{issuer}:{username}"
    return f"otpauth://totp/{quote(label, safe=':@')}?secret={secret}&issuer={quote(issuer)}&algorithm=SHA1&digits=6&period=30"
