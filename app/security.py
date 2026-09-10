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

