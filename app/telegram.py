"""Telegram integration for idontScanner.

The bot deliberately keeps Telegram as a thin presentation layer. Scanner,
Check-Host and network diagnostics continue to live in their existing service
modules so the web panel and Telegram bot share the same behaviour.
"""

from __future__ import annotations

import asyncio
import html
import json
import secrets
import logging
import os
import math
from datetime import datetime, timezone
from urllib.request import Request as URLRequest, urlopen
import uuid

from app.telegram_chart import build_scan_chart

from app.check_host import IRAN_NODES, fetch_result, normalize_results, start_check
from app.connection import diagnose_config, parse_config, probe_services
from app.database import (
    db,
    get_setting,
    telegram_admin_ids,
    telegram_allowed_chat,
    telegram_configured_ids,
    set_setting,
)
from app.network import measure_network_quality
from app.scanner import run_scan
from app.auth import hash_password, verify_password
from app.security import new_totp_secret, provisioning_uri, totp_enabled, verify_totp

logger = logging.getLogger("idontscanner.telegram")


PREMIUM_EMOJIS = {
    "👋": "5454390891466726015",
    "⚡️": "5085022089103016925",
    "⚙️": "5116222002851480476",
    "🔒": "5397731992135545615",
    "✅": "6016907976609107800",
    "🔴": "6001066256025785838",
    "🟡": "6001542748287539188",
    "🔵": "6001233652376146830",
    "👤": "5974038293120027938",
    "🌐": "5974475701179387553",
    "📊": "5118775128980718591",
    "❗️": "5976801477509778431",
    "🔄": "6019082338162446951",
    "⏰": "5809742105987259196",
    "⏲": "5976544483846654540",
    "📶": "5783105032350076195",
    "📜": "5264821604935804414",
    "🔐": "5836690092306992715",
    "🛰": "5321304062715517873",
    "🟢": "5787293020600671888",
    "🟡_status": "5926980668624998964",
    "🔴_status": "5927031220390072917",
    "⏱": "5382194935057372936",
    "🏅": "5803357151770449172",
    "⚡": "5846020586635006056",
    "🟢_quality": "5418210421972690992",
    "🔵_info": "6001233652376146830",
    "🟠": "5845692803320909362",
    "🏆": "5312315739842026755",
    "🐢": "5219739304619694291",
    "👑": "5053412040337524042",
    "✍️": "5258331647358540449",
    "🚪": "5258084656674250503",
}


NORMAL_EMOJIS = {
    "iran": "🦁",
    "scan": "⚡️",
    "check_host": "🌐",
    "smart": "📶",
    "speed": "⏲",
    "status": "📊",
    "history": "📜",
    "diagnostics": "🛰",
    "scheduler": "⏰",
    "settings": "⚙️",
    "success": "🟢",
    "warning": "🟡",
    "error": "🔴",
    "back": "🔄",
    "info": "🔵",
    "score": "🏅",
}

BUTTON_STYLES = {
    "scan": "primary",
    "check_host": "primary",
    "smart": "success",
    "speed": "success",
    "status": "success",
    "history": "primary",
    "diagnostics": "danger",
    "scheduler": "success",
    "settings": "primary",
    "refresh": "primary",
    "help": "primary",
    "menu": "primary",
    "check_ping": "success",
    "check_http": "primary",
    "check_tcp": "primary",
    "check_udp": "danger",
    "check_dns": "primary",
    "check_global": "primary",
    "check_iran": "success",
    "security": "primary",
    "security_username": "primary",
    "security_password": "primary",
    "security_reset": "danger",
    "security_logout": "danger",
    "security_2fa": "primary",
    "security_2fa_enable": "success",
    "security_2fa_disable": "danger",
    "security_2fa_back": "primary",
    "security_2fa_web": "primary",
}

BUTTON_ICONS = {
    "scan": "⚡️",
    "check_host": "🌐",
    "smart": "📶",
    "speed": "⏲",
    "status": "📊",
    "history": "📜",
    "diagnostics": "🛰",
    "scheduler": "⏰",
    "settings": "⚙️",
    "refresh": "🔄",
    "help": "❗️",
    "menu": "🔄",
    "check_ping": "⚡",
    "check_http": "🌐",
    "check_tcp": "🔐",
    "check_udp": "📶",
    "check_dns": "🛰",
    "check_global": "🌐",
    "check_iran": "👑",
    "security": "🔒",
    "security_username": "✍️",
    "security_password": "🔐",
    "security_reset": "🔄",
    "security_logout": "🚪",
    "security_2fa": "🔒",
    "security_2fa_enable": "🔒",
    "security_2fa_disable": "🔒",
}


SMART_CONFIG_SCHEMES = ("vless://", "vmess://", "trojan://", "ss://", "hysteria2://")


async def _iran_service_matrix() -> dict[str, dict]:
    """Measure service reachability from the six configured Iran nodes."""
    endpoints = {
        "Instagram": "www.instagram.com:443",
        "Telegram": "telegram.org:443",
        "YouTube": "www.youtube.com:443",
    }

    async def one(name: str, target: str):
        try:
            started = await start_check("ping", target, nodes=list(IRAN_NODES))
            raw = {}
            normalized = {"results": [], "complete": False}
            for _ in range(5):
                raw = await fetch_result(started["request_id"])
                normalized = normalize_results("ping", raw, started.get("nodes", {}))
                if normalized.get("complete"):
                    break
                await asyncio.sleep(0.5)
            return name, normalized
        except Exception as exc:
            return name, {"results": [], "complete": False, "error": str(exc)[:160]}

    pairs = await asyncio.gather(*(one(name, target) for name, target in endpoints.items()))
    return dict(pairs)


def _smart_config_text(config_results: list[dict], services: dict, iran: dict, premium: bool) -> str:
    lines = [
        f"<b>{ui_emoji('📶', premium)} Smart Testing</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        f"{ui_emoji('🔐', premium)} Configs: <b>{len(config_results)}</b>",
        "",
    ]
    for item in config_results:
        cfg = item.get("config") or {}
        protocol = html.escape(str(cfg.get("protocol") or cfg.get("scheme") or "Unknown"))
        host = html.escape(str(cfg.get("host") or "-"))
        status = item.get("status", "failed")
        marker = ui_emoji("🟢" if status in {"ok", "resolved"} else "🔴", premium)
        latency = item.get("latency_ms")
        latency_text = f"{latency} ms" if latency is not None else status.upper()
        lines.append(f"{marker} <b>{protocol}</b> · <code>{host}</code> · {latency_text}")
        if item.get("alpn") or item.get("tls_version"):
            lines.append(f"   TLS: <b>{html.escape(str(item.get('tls_version') or '-'))}</b> · ALPN: <b>{html.escape(str(item.get('alpn') or '-'))}</b>")

    lines += ["", f"{ui_emoji('🌐', premium)} <b>Service reachability</b>"]
    for name in ("Instagram", "Telegram", "YouTube"):
        result = services.get(name) or {}
        latency = result.get("latency_ms")
        marker = ui_emoji("🟢" if result.get("status") == "ok" else "🔴", premium)
        lines.append(f"{marker} {name}: <b>{latency} ms</b>" if latency is not None else f"{marker} {name}: <b>Unavailable</b>")

    lines += ["", f"{ui_emoji('👑', premium)} <b>Iran · 6 Nodes</b>"]
    for name in ("Instagram", "Telegram", "YouTube"):
        result = iran.get(name) or {}
        values = [x.get("avg_ms") for x in result.get("results", []) if x.get("status") == "online" and x.get("avg_ms") is not None]
        avg = round(sum(values) / len(values), 1) if values else None
        online = len(values)
        lines.append(f"{name}: <b>{avg} ms</b> · {online}/6 nodes" if avg is not None else f"{name}: <b>N/A</b> · {online}/6 nodes")

    lines += ["", "<i>Upload/download are measured only against controlled test endpoints; arbitrary public services are never treated as throughput endpoints.</i>"]
    return "\n".join(lines)[:3900]


async def run_smart_testing(raw_text: str, premium: bool) -> str:
    configs = []
    for line in raw_text.replace("\r", "").split("\n"):
        line = line.strip()
        if not line or not line.lower().startswith(SMART_CONFIG_SCHEMES):
            continue
        try:
            cfg = parse_config(line)
            result = await diagnose_config(cfg)
            configs.append(result)
        except Exception as exc:
            configs.append({"status": "failed", "error": str(exc)[:160], "config": {"protocol": "Unknown", "host": "-"}})
        if len(configs) >= 8:
            break

    if not configs:
        raise ValueError("No supported VLESS, VMess, Trojan, Shadowsocks, or Hysteria2 configuration was detected.")

    services_task = asyncio.create_task(probe_services())
    iran_task = asyncio.create_task(_iran_service_matrix())
    vps_task = asyncio.create_task(asyncio.to_thread(measure_network_quality))
    services, iran, vps = await asyncio.gather(services_task, iran_task, vps_task)
    text = _smart_config_text(configs, services, iran, premium)
    text += (
        f"\n\n{ui_emoji('⏲', premium)} <b>VPS Network</b>\n"
        f"Download: <b>{vps.get('download_mbps', 'N/A')} Mbps</b>\n"
        f"Upload: <b>{vps.get('upload_mbps', 'N/A')} Mbps</b>\n"
        f"{ui_emoji('⏱', premium)} Latency: <b>{vps.get('latency_ms', 'N/A')} ms</b> · Jitter: <b>{vps.get('jitter_ms', 'N/A')} ms</b>"
    )
    return text[:3900]


# Target entry state is intentionally in-memory. It is only a short-lived
# conversation helper and never stores credentials or persistent user data.
_PENDING_CHECKS: dict[int, dict[str, str]] = {}
_PENDING_SECURITY: dict[int, str] = {}


def telegram_request(token: str, method: str, payload: dict | None = None):
    """Call one Telegram Bot API method and return its decoded response."""
    request = URLRequest(
        f"https://api.telegram.org/bot{token}/{method}",
        data=json.dumps(payload or {}).encode(),
        headers={"Content-Type": "application/json"},
    )
    # Keep interactive callbacks responsive. Long polling gets its own longer
    # socket timeout because Telegram may hold getUpdates for up to 25 seconds.
    request_timeout = 30 if method == "getUpdates" else 12
    with urlopen(request, timeout=request_timeout) as response:
        return json.loads(response.read().decode())


def telegram_send(
    text: str,
    reply_markup: dict | None = None,
    chat_id: int | str | None = None,
) -> bool:
    """Send a message to one chat or all configured Telegram recipients."""
    token = get_setting("telegram_token")
    recipients = [str(chat_id)] if chat_id is not None else telegram_configured_ids()
    recipients = [item for item in recipients if telegram_allowed_chat(item)]

    if not token or not recipients:
        return False

    sent = False
    for recipient in recipients:
        payload = {
            "chat_id": int(recipient),
            "text": text,
            "parse_mode": "HTML",
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        try:
            telegram_request(token, "sendMessage", payload)
            sent = True
        except Exception:
            continue
    return sent


def _telegram_send_photo(token: str, chat_id: int | str, path: str, caption: str, reply_markup: dict | None = None) -> bool:
    """Upload a generated chart as a photo using Telegram's multipart API."""
    boundary = f"----idontScanner{uuid.uuid4().hex}"
    data = open(path, "rb").read()
    fields = {
        "chat_id": str(chat_id),
        "caption": caption[:1024],
        "parse_mode": "HTML",
        "show_caption_above_media": "true",
    }
    if reply_markup:
        import json as _json
        fields["reply_markup"] = _json.dumps(reply_markup, separators=(",", ":"))

    chunks = []
    for key, value in fields.items():
        chunks.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{value}\r\n".encode())
    chunks.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"scan.jpg\"\r\nContent-Type: image/jpeg\r\n\r\n".encode()
        + data + b"\r\n"
    )
    chunks.append(f"--{boundary}--\r\n".encode())
    request = URLRequest(
        f"https://api.telegram.org/bot{token}/sendPhoto",
        data=b"".join(chunks),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urlopen(request, timeout=20) as response:
            result = json.loads(response.read().decode())
        return bool(result.get("ok"))
    except Exception:
        logger.exception("Telegram scan chart upload failed")
        return False


async def send_scan_result_async(token: str, chat_id: int | str, scan: dict, premium: bool = True, scheduled: bool = False, fallback_markup: dict | None = None) -> bool:
    """Send a scan as a chart with a compact, factual caption.

    If chart rendering/upload fails, fall back to the existing text summary so
    a visualization failure can never hide the actual scan result.
    """
    path = None
    try:
        path = await asyncio.to_thread(build_scan_chart, scan, scheduled)
        if path:
            caption = format_scan_caption(scan, premium, scheduled)
            sent = await asyncio.to_thread(_telegram_send_photo, token, chat_id, path, caption, fallback_markup)
            if sent:
                return True
    except Exception:
        logger.exception("Telegram scan chart generation failed")
    finally:
        if path:
            try:
                os.unlink(path)
            except OSError:
                pass
    return await telegram_send_async(format_scan_message(scan, premium, scheduled), fallback_markup, chat_id)


def is_premium_user(user: dict | None) -> bool:
    return bool((user or {}).get("is_premium", False))


def premium_emoji(emoji: str) -> str:
    emoji_id = PREMIUM_EMOJIS.get(emoji)
    if not emoji_id:
        return emoji
    return f'<tg-emoji emoji-id="{emoji_id}">{emoji}</tg-emoji>'


def ui_emoji(emoji: str, premium: bool = True) -> str:
    """Use the supplied Premium emoji, with a safe Unicode fallback."""
    if premium and emoji in PREMIUM_EMOJIS:
        return premium_emoji(emoji)
    return emoji


def button(text: str, callback_data: str, premium: bool = True) -> dict:
    """Build a resilient inline callback button.

    ``callback_data`` is the actual action channel; visual emoji are optional.
    When the bot/account supports Telegram custom emoji button icons we attach
    the icon id, while retaining a plain-text fallback for older clients.
    """
    icon = BUTTON_ICONS.get(callback_data, "🔵")
    label = text
    if not premium:
        label = f"{icon} {text}"

    payload = {"text": label, "callback_data": callback_data}
    style = BUTTON_STYLES.get(callback_data)
    if style:
        payload["style"] = style
    emoji_id = PREMIUM_EMOJIS.get(icon) if premium else None
    if emoji_id:
        payload["icon_custom_emoji_id"] = emoji_id
    return payload


def main_keyboard(premium: bool = True) -> dict:
    return {
        "inline_keyboard": [
            [button("Domain Scanner", "scan", premium), button("Check Host", "check_host", premium)],
            [button("Smart Connection", "smart", premium), button("VPS Speed", "speed", premium)],
            [button("Server Status", "status", premium), button("History", "history", premium)],
            [button("Network Diagnostics", "diagnostics", premium), button("Scheduler", "scheduler", premium)],
            [button("Settings", "settings", premium), button("Account Security", "security", premium)],
            [button("Refresh", "refresh", premium)],
            [button("Help", "help", premium)],
        ]
    }


def security_keyboard(premium: bool = True) -> dict:
    """Account Security actions using stable Telegram Bot API buttons."""
    return {
        "inline_keyboard": [
            [button("Change Username", "security_username", premium)],
            [button("Change Password", "security_password", premium)],
            [button("Reset Password", "security_reset", premium)],
            [button("Two-Factor Authentication", "security_2fa", premium)],
            [button("Logout All Sessions", "security_logout", premium)],
            [button("Back to Menu", "menu", premium)],
        ]
    }


def two_factor_keyboard(premium: bool = True) -> dict:
    enabled = totp_enabled()
    action = "security_2fa_disable" if enabled else "security_2fa_enable"
    label = "Disable 2FA" if enabled else "Enable 2FA"
    return {
        "inline_keyboard": [
            [button(label, action, premium)],
            [button("Open Web Panel 2FA", "security_2fa_web", premium)],
            [button("Back to Account Security", "security", premium)],
            [button("Back to Menu", "menu", premium)],
        ]
    }


def two_factor_text() -> str:
    status = "Enabled" if totp_enabled() else "Disabled"
    return (
        f"<b>{ui_emoji('🛡️', True)} Two-Factor Authentication</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"Status: <b>{status}</b>\n\n"
        "Protect the web panel with a 6-digit TOTP code from an authenticator app.\n"
        "You can enable or disable it from this menu or manage it in the web panel."
    )


def security_text() -> str:
    status = "Enabled" if totp_enabled() else "Disabled"
    return (
        f"<b>{ui_emoji('🔒', True)} Account Security</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Please select an option from the menu below.\n\n"
        f"{ui_emoji('🛡️', True)} Two-Factor Authentication: <b>{status}</b>"
    )


def menu_text(premium: bool, first_name: str | None = None) -> str:
    name = html.escape(first_name or "User")
    badge = f" {premium_emoji('👋')}" if premium else ""
    tier = "Premium" if premium else "Standard"
    return (
        f"<b>{ui_emoji('🛰', premium)} idontScanner</b>{badge}\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"{ui_emoji('👤', premium)} <b>{name}</b> · <b>{tier}</b>\n\n"
        f"{ui_emoji('⚡️', premium)} <b>Network intelligence at your fingertips.</b>\n"
        "Choose a diagnostic tool below."
    )


def _back_keyboard(premium: bool) -> dict:
    return {"inline_keyboard": [[button("Back to Menu", "menu", premium)]]}


def format_scan_caption(scan: dict, premium: bool = True, scheduled: bool = False) -> str:
    """Caption paired with the scan chart; keep it within Telegram's limit."""
    results = scan.get("chart_results") or scan.get("results") or []
    successful = [
        r for r in results
        if r.get("status") == "ok" and _finite_latency(r.get("latency_ms")) is not None
    ]
    fastest = min(successful, key=lambda r: float(r.get("latency_ms"))) if successful else None
    slowest = max(successful, key=lambda r: float(r.get("latency_ms"))) if successful else None
    title = "Scheduled Scan Complete" if scheduled else "Scan Complete"
    lines = [
        f"<b>{ui_emoji('🛰', premium)} {title}</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        f"{ui_emoji('🌐', premium)} Targets: <b>{scan.get('total', 0)}</b> · Online: <b>{scan.get('ok', 0)}</b>",
        f"{ui_emoji('⚡', premium)} Average: <b>{scan.get('average_ms', 'N/A')} ms</b>",
        f"{ui_emoji('🏅', premium)} Score: <b>{scan.get('score', 'N/A')}/100</b> · <b>{html.escape(str(scan.get('score_label', 'N/A')))}</b>",
    ]
    if fastest:
        domain = html.escape(str(fastest.get("domain", "Target")))
        ping = float(fastest.get("latency_ms"))
        lines.append(f"🏆 <b>Best domain:</b> <code>{domain}</code> · <b>{ping:.1f} ms</b>")
        lines.append(f"⚡ <b>Lowest ping:</b> <b>{ping:.1f} ms</b>")
    if slowest:
        domain = html.escape(str(slowest.get("domain", "Target")))
        ping = float(slowest.get("latency_ms"))
        lines.append(f"🐢 <b>Worst domain:</b> <code>{domain}</code> · <b>{ping:.1f} ms</b>")
    lines.append(f"⏱ <b>Duration:</b> {scan.get('duration_ms', 'N/A')} ms")
    return "\n".join(lines)[:1024]


def _finite_latency(value):
    try:
        value = float(value)
        return value if value >= 0 and math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def format_scan_message(scan: dict, premium: bool = True, scheduled: bool = False) -> str:
    results = scan.get("results", [])
    successful = [
        result for result in results
        if result.get("status") == "ok" and result.get("latency_ms") is not None
    ]
    fastest = min(successful, key=lambda item: item["latency_ms"]) if successful else None
    slowest = max(successful, key=lambda item: item["latency_ms"]) if successful else None

    ranks = {"excellent": 0, "good": 0, "normal": 0, "slow": 0, "very_slow": 0, "critical": 0}
    for result in successful:
        latency = float(result["latency_ms"])
        if latency < 100:
            ranks["excellent"] += 1
        elif latency < 250:
            ranks["good"] += 1
        elif latency < 500:
            ranks["normal"] += 1
        elif latency < 1000:
            ranks["slow"] += 1
        elif latency < 2000:
            ranks["very_slow"] += 1
        else:
            ranks["critical"] += 1

    title = "Scheduled Scan Complete" if scheduled else "Scan Complete"
    lines = [
        f"<b>{ui_emoji('🛰', premium)} idontScanner</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        f"{ui_emoji('🏆', premium)} <b>{title}</b>",
        "",
        f"{ui_emoji('🌐', premium)} Targets: <b>{scan.get('total', 0)}</b>",
        f"{ui_emoji('🟢', premium)} Online: <b>{scan.get('ok', 0)}</b>",
        f"{ui_emoji('🟡', premium)} Slow: <b>{scan.get('slow', 0)}</b>",
        f"{ui_emoji('🔴', premium)} Failed: <b>{scan.get('failed', 0)}</b>",
        "",
        f"{ui_emoji('⚡', premium)} Average: <b>{scan.get('average_ms', 'N/A')} ms</b>",
        f"{ui_emoji('⏱', premium)} Duration: <b>{scan.get('duration_ms', 'N/A')} ms</b>",
        f"{ui_emoji('🏅', premium)} Score: <b>{scan.get('score', 'N/A')}/100</b> · <b>{scan.get('score_label', 'N/A')}</b>",
    ]

    if fastest:
        lines.append(
            f"\n🏆 Fastest: <b>{html.escape(fastest['domain'])}</b> · {fastest['latency_ms']} ms"
        )
    if slowest:
        lines.append(
            f"🐢 Slowest: <b>{html.escape(slowest['domain'])}</b> · {slowest['latency_ms']} ms"
        )

    custom = scan.get("custom_target")
    if custom:
        lines.extend([
            "",
            f"{ui_emoji('🎯', premium)} <b>Custom IP</b>",
            f"Target: <code>{html.escape(custom.get('target', ''))}</code>",
            f"Mode: <b>Raw Ping + TCP fallback</b>",
            f"Status: <b>{html.escape(str(custom.get('status', 'unknown')).upper())}</b>",
        ])
    return "\n".join(lines)


def format_status(premium: bool) -> str:
    with db() as con:
        row = con.execute("SELECT * FROM scheduler WHERE id=1").fetchone()
    enabled = bool(row["enabled"])
    return "\n".join([
        f"<b>{ui_emoji('📊', premium)} Server Status</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        f"{ui_emoji('🟢' if enabled else '🔴', premium)} Scheduler: <b>{'ONLINE' if enabled else 'OFF'}</b>",
        f"{ui_emoji('⏱', premium)} Interval: <b>{row['interval_minutes']} min</b>",
        f"{ui_emoji('🔒', premium)} Access: <b>Authorized</b>",
    ])


def format_history(premium: bool = True) -> str:
    with db() as con:
        rows = con.execute(
            """
            SELECT id, started_at, total, ok, slow, failed, average_ms
            FROM scans
            ORDER BY id DESC
            LIMIT 5
            """
        ).fetchall()

    if not rows:
        return f"<b>{ui_emoji('📜', premium)} Scan History</b>\n━━━━━━━━━━━━━━━━━━━━\nNo scans recorded yet."

    lines = [f"<b>{ui_emoji('📜', premium)} Scan History</b>", "━━━━━━━━━━━━━━━━━━━━"]
    for row in rows:
        stamp = datetime.fromtimestamp(row["started_at"], timezone.utc).strftime("%Y-%m-%d %H:%M")
        avg = f"{row['average_ms']} ms" if row["average_ms"] is not None else "N/A"
        lines.append(
            f"<b>#{row['id']}</b> · {stamp}\n"
            f"🌐 {row['total']} · 🟢 {row['ok']} · 🟡 {row['slow']} · 🔴 {row['failed']} · ⚡ {avg}"
        )
    return "\n\n".join(lines)


def format_diagnostics(premium: bool) -> str:
    with db() as con:
        row = con.execute("SELECT * FROM scheduler WHERE id=1").fetchone()
    token = bool(get_setting("telegram_token"))
    owner = bool(get_setting("telegram_owner_id"))
    admins = bool(get_setting("telegram_admin_ids"))
    return "\n".join([
        f"<b>{ui_emoji('🛰', premium)} Network Diagnostics</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        f"{ui_emoji('🟢', premium)} Database: <b>OK</b>",
        f"{ui_emoji('🟢' if token else '🔴', premium)} Telegram Token: <b>{'Configured' if token else 'Missing'}</b>",
        f"{ui_emoji('🟢' if owner else '🔴', premium)} Owner ID: <b>{'Configured' if owner else 'Missing'}</b>",
        f"{ui_emoji('🟢' if admins else '🟡', premium)} Admin IDs: <b>{'Configured' if admins else 'Not set'}</b>",
        f"{ui_emoji('🟢' if row['enabled'] else '🟡', premium)} Scheduler: <b>{'Running' if row['enabled'] else 'Disabled'}</b>",
    ])


def format_help(premium: bool) -> str:
    return "\n".join([
        f"<b>{ui_emoji('❗️', premium)} idontScanner Help</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        "<b>Available tools</b>",
        "⚡️ Domain Scanner — scan the configured 150 domains.",
        "🌐 Check Host — global or Iran multi-node diagnostics.",
        "📶 Smart Connection — Download, Upload, Latency and Jitter.",
        "⏲ VPS Speed — bounded VPS network-quality test.",
        "📜 History — recent scanner runs.",
        "",
        "<b>Commands</b>",
        "/start · /menu · /scan · /status",
        "/checkhost example.com",
        "/ping 1.1.1.1",
    ])


def format_check_host_picker(premium: bool) -> str:
    return "\n".join([
        f"<b>{ui_emoji('🌐', premium)} Check Host</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        "Choose a test type, then send a hostname or IP.",
        "",
        "The result is collected from real Check-Host nodes.",
    ])


def check_host_keyboard(premium: bool) -> dict:
    return {
        "inline_keyboard": [
            [button("Ping", "check_ping", premium), button("HTTP", "check_http", premium)],
            [button("TCP Port", "check_tcp", premium), button("UDP Port", "check_udp", premium)],
            [button("DNS", "check_dns", premium), button("Global", "check_global", premium)],
            [button("Iran · 6 Nodes", "check_iran", premium)],
            [button("Back to Menu", "menu", premium)],
        ]
    }


def format_network_quality(result: dict, premium: bool) -> str:
    return "\n".join([
        f"<b>{ui_emoji('📶', premium)} Smart Connection</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        f"{ui_emoji('⬇️', premium)} Download: <b>{result.get('download_mbps', 'N/A')} Mbps</b>",
        f"{ui_emoji('⬆️', premium)} Upload: <b>{result.get('upload_mbps', 'N/A')} Mbps</b>",
        f"{ui_emoji('⏱', premium)} Latency: <b>{result.get('latency_ms', 'N/A')} ms</b>",
        f"{ui_emoji('⏱', premium)} Jitter: <b>{result.get('jitter_ms', 'N/A')} ms</b>",
        f"{ui_emoji('🏅', premium)} Samples: <b>{result.get('samples', 'N/A')}</b>",
    ])


def format_check_results(check: dict, result: dict, premium: bool) -> str:
    lines = [
        f"<b>{ui_emoji('🌐', premium)} Check Host · {html.escape(check['type'].upper())}</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        f"Target: <code>{html.escape(check['target'])}</code>",
        f"Location: <b>{'Iran · 6 Nodes' if check['group'] == 'iran' else 'Global'}</b>",
        "",
        f"{ui_emoji('🟢', premium)} Online: <b>{result.get('online', 0)}/{result.get('total', 0)}</b>",
        f"{ui_emoji('⏱', premium)} Average: <b>{result.get('average_ms', 'N/A')} ms</b>",
        "",
    ]

    for node in result.get("results", []):
        city = html.escape(node.get("city") or node.get("country") or node.get("id", "Node"))
        status = node.get("status", "unknown")
        marker = "🟢" if status == "online" else "🔴" if status == "failed" else "🟡"
        latency = node.get("avg_ms", node.get("latency_ms"))
        latency_text = f"{latency} ms" if latency is not None else status.upper()
        lines.append(f"{marker} <b>{city}</b> · {latency_text}")
    return "\n".join(lines)


def _legacy_markup(markup: dict | None) -> dict | None:
    """Remove optional Bot API button fields for older Telegram clients."""
    if not markup:
        return markup
    rows = []
    for row in markup.get("inline_keyboard", []):
        rows.append([
            {key: value for key, value in button_item.items() if key != "icon_custom_emoji_id"}
            for button_item in row
        ])
    return {"inline_keyboard": rows}


def edit_message(token: str, chat_id: int, message_id: int, text: str, markup: dict | None = None):
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML",
    }
    if markup is not None:
        payload["reply_markup"] = markup
    try:
        return telegram_request(token, "editMessageText", payload)
    except Exception:
        # Do not leave a working menu blank if the Telegram client/bot account
        # cannot use the newer colored/custom-emoji button fields.
        if markup is None:
            raise
        payload["reply_markup"] = _legacy_markup(markup)
        return telegram_request(token, "editMessageText", payload)


def callback_response(token: str, callback_id: str):
    try:
        telegram_request(token, "answerCallbackQuery", {"callback_query_id": callback_id})
    except Exception:
        pass


def send_dashboard(token: str, chat_id: int, user: dict):
    premium = is_premium_user(user)
    payload = {
        "chat_id": chat_id,
        "text": menu_text(premium, user.get("first_name")),
        "parse_mode": "HTML",
        "reply_markup": main_keyboard(premium),
    }
    try:
        return telegram_request(token, "sendMessage", payload)
    except Exception:
        payload["reply_markup"] = _legacy_markup(payload["reply_markup"])
        return telegram_request(token, "sendMessage", payload)


async def telegram_request_async(token: str, method: str, payload: dict | None = None):
    """Run blocking Telegram HTTP calls off the asyncio event loop."""
    return await asyncio.to_thread(telegram_request, token, method, payload)


async def telegram_send_async(
    text: str,
    reply_markup: dict | None = None,
    chat_id: int | str | None = None,
) -> bool:
    return await asyncio.to_thread(telegram_send, text, reply_markup, chat_id)


async def edit_message_async(
    token: str, chat_id: int, message_id: int, text: str, markup: dict | None = None
):
    return await asyncio.to_thread(edit_message, token, chat_id, message_id, text, markup)


async def security_message_async(
    token: str, chat_id: int, message_id: int | None, text: str, markup: dict | None = None
):
    """Update a security message, falling back to a fresh message on edit errors."""
    if message_id:
        try:
            result = await edit_message_async(token, chat_id, message_id, text, markup)
            if result and result.get("ok", True):
                return result
        except Exception:
            logger.exception("Telegram security message edit failed")
    return await telegram_request_async(token, "sendMessage", {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        **({"reply_markup": markup} if markup else {}),
    })


async def delete_message_async(token: str, chat_id: int, message_id: int | None):
    if not message_id:
        return
    try:
        await telegram_request_async(token, "deleteMessage", {"chat_id": chat_id, "message_id": message_id})
    except Exception:
        # Telegram may reject deletion depending on chat/client state; never block security flows.
        pass


async def callback_response_async(token: str, callback_id: str):
    return await asyncio.to_thread(callback_response, token, callback_id)


async def send_dashboard_async(token: str, chat_id: int, user: dict):
    return await asyncio.to_thread(send_dashboard, token, chat_id, user)


async def run_check_host_flow(token: str, chat_id: int, user: dict, check_type: str, target: str, group: str):
    premium = is_premium_user(user)
    if group == "iran":
        from app.check_host import IRAN_NODES
        started = await start_check(check_type, target, nodes=list(IRAN_NODES))
    else:
        started = await start_check(check_type, target)

    node_map = json.dumps(started.get("nodes", {}), separators=(",", ":"))
    await asyncio.sleep(1.0)
    raw = await fetch_result(started["request_id"])
    normalized = normalize_results(check_type, raw, started.get("nodes", {}))

    # A short polling window gives slower nodes time to report without making
    # the Telegram worker block indefinitely.
    for _ in range(5):
        if normalized.get("complete"):
            break
        await asyncio.sleep(1.0)
        raw = await fetch_result(started["request_id"])
        normalized = normalize_results(check_type, raw, started.get("nodes", {}))

    text = format_check_results({"type": check_type, "target": target, "group": group}, normalized, premium)
    markup = _back_keyboard(premium)
    await telegram_request_async(token, "sendMessage", {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "reply_markup": markup,
    })


async def security_alert(token: str, event: str, chat_id: int | str, detail: str = "") -> None:
    """Send a concise security event to configured Telegram recipients.

    The current owner chat is excluded from duplicate alerts when the event
    was already triggered by an interactive security action.
    """
    ip = str(chat_id)
    text = (
        f"<b>{ui_emoji('🔒', True)} Security Alert</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"Event: <b>{html.escape(event)}</b>\n"
        f"Source: <code>{html.escape(ip)}</code>"
    )
    if detail:
        text += f"\nDetail: {html.escape(detail[:180])}"
    await telegram_send_async(text)


async def _handle_callback_safe(token: str, callback: dict):
    """Never let one callback exception silently kill a security action."""
    try:
        await handle_callback(token, callback)
    except Exception as exc:
        logger.exception("Telegram callback failed: action=%s", callback.get("data"))
        try:
            await callback_response_async(token, callback.get("id"))
        except Exception:
            pass
        message = callback.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        if chat_id and telegram_allowed_chat(chat_id):
            try:
                await telegram_request_async(token, "sendMessage", {
                    "chat_id": chat_id,
                    "text": "<b>Security action failed.</b>\n\nPlease try again. The failure was logged on the server.",
                    "parse_mode": "HTML",
                    "reply_markup": _back_keyboard(is_premium_user(callback.get("from") or {})),
                })
            except Exception:
                logger.exception("Unable to report Telegram callback failure")


async def handle_callback(token: str, callback: dict):
    message = callback.get("message") or {}
    chat = message.get("chat") or {}
    user = callback.get("from") or {}
    chat_id = chat.get("id")
    action = callback.get("data", "")
    message_id = message.get("message_id")
    premium = is_premium_user(user)

    await callback_response_async(token, callback.get("id"))
    if not chat_id or chat.get("type") != "private" or not telegram_allowed_chat(chat_id):
        return

    if action == "menu":
        await edit_message_async(token, chat_id, message_id, menu_text(premium, user.get("first_name")), main_keyboard(premium))
        return

    if action == "refresh":
        await edit_message_async(token, chat_id, message_id, menu_text(premium, user.get("first_name")), main_keyboard(premium))
        return

    if action == "security":
        if str(chat_id) != telegram_owner_id():
            await security_message_async(token, chat_id, message_id, "<b>Owner access required.</b>", _back_keyboard(premium))
            return
        await security_message_async(token, chat_id, message_id, security_text(), security_keyboard(premium))
        return

    if action == "security_2fa":
        if str(chat_id) != telegram_owner_id():
            await security_message_async(token, chat_id, message_id, "<b>Owner access required.</b>", _back_keyboard(premium))
            return
        await security_message_async(token, chat_id, message_id, two_factor_text(), two_factor_keyboard(premium))
        return

    if action == "security_2fa_web":
        if str(chat_id) != telegram_owner_id():
            return
        public_url = get_setting("public_panel_url", "").strip().rstrip("/")
        if public_url:
            markup = {"inline_keyboard": [[{"text": "Open Web Panel 2FA", "url": public_url + "/account/2fa/"}], [button("Back", "security_2fa", premium)]]}
            await security_message_async(token, chat_id, message_id, "<b>Web Panel · Two-Factor Authentication</b>\n\nOpen the dedicated 2FA section:", markup)
        else:
            await security_message_async(token, chat_id, message_id, "<b>Web Panel · Two-Factor Authentication</b>\n\nSet <code>IDONTSCANNER_PUBLIC_URL</code> or the <code>public_panel_url</code> setting first so Telegram can generate a secure web-panel link.", two_factor_keyboard(premium))
        return

    if action == "security_username":
        if str(chat_id) != telegram_owner_id():
            return
        _PENDING_SECURITY[chat_id] = "username"
        await security_message_async(token, chat_id, message_id, "<b>Change Username</b>\n\nSend the new panel username (3–32 characters).", _back_keyboard(premium))
        return

    if action == "security_password":
        if str(chat_id) != telegram_owner_id():
            return
        _PENDING_SECURITY[chat_id] = "password_current"
        await security_message_async(token, chat_id, message_id, "<b>Change Password</b>\n\nSend your current password. It will not be echoed back.", _back_keyboard(premium))
        return

    if action == "security_reset":
        if str(chat_id) != telegram_owner_id():
            return
        markup = {
            "inline_keyboard": [
                [button("Confirm Reset Password", "security_reset_confirm", premium)],
                [button("Cancel", "security", premium)],
            ]
        }
        await security_message_async(
            token, chat_id, message_id,
            "<b>Reset Password</b>\n\nThis will immediately invalidate all active web sessions and generate a new password.\n\nAre you sure?",
            markup,
        )
        return

    if action == "security_reset_confirm":
        if str(chat_id) != telegram_owner_id():
            return
        new_password = secrets.token_urlsafe(12)
        set_setting("password", hash_password(new_password))
        with db() as con:
            con.execute("DELETE FROM sessions")
        await security_message_async(
            token, chat_id, message_id,
            f"<b>Password reset complete.</b>\n\nYour new temporary password is:\n<code>{html.escape(new_password)}</code>\n\nAll web sessions were revoked. Save this password now; it will not be shown again.",
            security_keyboard(premium),
        )
        await security_alert(token, "Password reset", chat_id)
        return

    if action == "security_2fa_enable":
        if str(chat_id) != telegram_owner_id():
            return
        if totp_enabled():
            await security_message_async(token, chat_id, message_id, security_text(), security_keyboard(premium))
            return
        secret = new_totp_secret()
        _PENDING_SECURITY[chat_id] = "2fa_enable:" + secret
        uri = provisioning_uri(get_setting("username", "admin"), secret)
        text = (
            f"<b>{ui_emoji('🛡️', premium)} Enable 2FA</b>\n\n"
            "Add this account to your TOTP authenticator.\n\n"
            f"Secret: <code>{html.escape(secret)}</code>\n"
            f"Setup URI: <code>{html.escape(uri)}</code>\n\n"
            "Then send the current 6-digit code here to confirm activation."
        )
        await security_message_async(token, chat_id, message_id, text, _back_keyboard(premium))
        return

    if action == "security_2fa_disable":
        if str(chat_id) != telegram_owner_id() or not totp_enabled():
            return
        _PENDING_SECURITY[chat_id] = "2fa_disable_password"
        await security_message_async(token, chat_id, message_id, "<b>Disable 2FA</b>\n\nSend the current panel password.", _back_keyboard(premium))
        return

    if action == "security_logout":
        if str(chat_id) != telegram_owner_id():
            return
        with db() as con:
            con.execute("DELETE FROM sessions")
        await security_message_async(token, chat_id, message_id, "<b>All web sessions have been revoked.</b>", security_keyboard(premium))
        await security_alert(token, "All sessions revoked", chat_id)
        return

    if action == "scan":
        await edit_message_async(token, chat_id, message_id, f"{ui_emoji('⚡️', premium)} <b>Scanning 150 domains + six Iran nodes...</b>", _back_keyboard(premium))
        scan = await run_scan()
        await edit_message_async(token, chat_id, message_id, f"{ui_emoji('🏆', premium)} <b>Scan complete — chart generated.</b>", _back_keyboard(premium))
        await send_scan_result_async(token, chat_id, scan, premium, False, _back_keyboard(premium))
        return

    if action == "check_host":
        await edit_message_async(token, chat_id, message_id, format_check_host_picker(premium), check_host_keyboard(premium))
        return

    if action.startswith("check_"):
        if action in {"check_global", "check_iran"}:
            group = "iran" if action == "check_iran" else "global"
            _PENDING_CHECKS[chat_id] = {"type": "ping", "group": group}
            label = "Iran · 6 Nodes" if group == "iran" else "Global"
            await edit_message_async(token, chat_id, message_id, f"<b>{label}</b>\n\nSend the hostname or IP to check.", _back_keyboard(premium))
            return

        check_type = action.removeprefix("check_")
        _PENDING_CHECKS[chat_id] = {"type": check_type, "group": "global"}
        await edit_message_async(token, chat_id, message_id, f"<b>{check_type.upper()} Check</b>\n\nSend the hostname or IP to check.", _back_keyboard(premium))
        return

    if action == "smart":
        await edit_message_async(
            token, chat_id, message_id,
            f"{ui_emoji('📶', premium)} <b>Smart Testing</b>\n\nSend one or more supported configs (VLESS / VMess / Trojan / Shadowsocks / Hysteria2).\n\nThe bot will test the endpoint, Instagram, Telegram, YouTube and the six Iran nodes.",
            _back_keyboard(premium),
        )
        return

    if action == "speed":
        await edit_message_async(token, chat_id, message_id, f"{ui_emoji('⏲', premium)} <b>Running VPS network test...</b>", _back_keyboard(premium))
        try:
            result = await asyncio.to_thread(measure_network_quality)
            text = "\n".join([
                f"<b>{ui_emoji('⏲', premium)} VPS Speed</b>",
                "━━━━━━━━━━━━━━━━━━━━",
                f"⬇️ Download: <b>{result.get('download_mbps', 'N/A')} Mbps</b>",
                f"⬆️ Upload: <b>{result.get('upload_mbps', 'N/A')} Mbps</b>",
                f"⏱ Latency: <b>{result.get('latency_ms', 'N/A')} ms</b>",
                f"⏱ Jitter: <b>{result.get('jitter_ms', 'N/A')} ms</b>",
                f"🏅 Samples: <b>{result.get('samples', 'N/A')}</b>",
            ])
        except Exception as exc:
            text = f"{ui_emoji('🔴', premium)} <b>VPS test failed</b>\n\n<code>{html.escape(str(exc)[:180])}</code>"
        await edit_message_async(token, chat_id, message_id, text, _back_keyboard(premium))
        return

    handlers = {
        "status": lambda: format_status(premium),
        "history": lambda: format_history(premium),
        "diagnostics": lambda: format_diagnostics(premium),
        "help": lambda: format_help(premium),
        "scheduler": lambda: format_status(premium),
        "settings": lambda: (
            "<b>⚙️ Telegram Settings</b>\n━━━━━━━━━━━━━━━━━━━━\n"
            f"Token: <b>{'Configured' if get_setting('telegram_token') else 'Missing'}</b>\n"
            f"Owner: <b>{'Configured' if get_setting('telegram_owner_id') else 'Missing'}</b>\n"
            "Sensitive credentials are never displayed."
        ),
    }
    if action in handlers:
        await edit_message_async(token, chat_id, message_id, handlers[action](), _back_keyboard(premium))


async def handle_text_message(token: str, message: dict):
    chat = message.get("chat") or {}
    user = message.get("from") or {}
    chat_id = chat.get("id")
    text = (message.get("text") or "").strip()
    message_id = message.get("message_id")
    if not chat_id or chat.get("type") != "private" or not telegram_allowed_chat(chat_id):
        return

    security_step = _PENDING_SECURITY.get(chat_id)
    if security_step and str(chat_id) == telegram_owner_id() and text and not text.startswith("/"):
        await delete_message_async(token, chat_id, message_id)
        if security_step == "username":
            if not 3 <= len(text) <= 32:
                await telegram_send_async("Username must be between 3 and 32 characters.", _back_keyboard(is_premium_user(user)), chat_id)
            else:
                set_setting("username", text)
                _PENDING_SECURITY.pop(chat_id, None)
                await telegram_send_async("Username changed successfully.", security_keyboard(is_premium_user(user)), chat_id)
                await security_alert(token, "Username changed", chat_id)
            return
        if security_step.startswith("2fa_enable:"):
            secret = security_step.split(":", 1)[1]
            if not verify_totp(secret, text):
                await telegram_send_async("Invalid authentication code. Send the current 6-digit code.", _back_keyboard(is_premium_user(user)), chat_id)
                return
            set_setting("totp_secret", secret)
            set_setting("totp_enabled", "1")
            _PENDING_SECURITY.pop(chat_id, None)
            await telegram_send_async("2FA enabled successfully.", security_keyboard(is_premium_user(user)), chat_id)
            await security_alert(token, "2FA enabled", chat_id)
            return

        if security_step == "2fa_disable_password":
            if not verify_password(text, get_setting("password")):
                await telegram_send_async("Current password is incorrect.", _back_keyboard(is_premium_user(user)), chat_id)
                await security_alert(token, "Failed password verification", chat_id)
                return
            _PENDING_SECURITY[chat_id] = "2fa_disable_code"
            await telegram_send_async("Password accepted. Send the current 6-digit authenticator code.", _back_keyboard(is_premium_user(user)), chat_id)
            return

        if security_step == "2fa_disable_code":
            if not verify_totp(get_setting("totp_secret", ""), text):
                await telegram_send_async("Invalid authentication code.", _back_keyboard(is_premium_user(user)), chat_id)
                return
            set_setting("totp_enabled", "0")
            set_setting("totp_secret", "")
            _PENDING_SECURITY.pop(chat_id, None)
            await telegram_send_async("2FA disabled successfully.", security_keyboard(is_premium_user(user)), chat_id)
            await security_alert(token, "2FA disabled", chat_id)
            return

        if security_step == "password_current":
            if not verify_password(text, get_setting("password")):
                await telegram_send_async("Current password is incorrect.", _back_keyboard(is_premium_user(user)), chat_id)
                return
            _PENDING_SECURITY[chat_id] = "password_new"
            await telegram_send_async("Current password accepted. Send the new password (minimum 8 characters).", _back_keyboard(is_premium_user(user)), chat_id)
            return
        if security_step == "password_new":
            if len(text) < 8:
                await telegram_send_async("New password must contain at least 8 characters.", _back_keyboard(is_premium_user(user)), chat_id)
                return
            _PENDING_SECURITY[chat_id] = "password_confirm_hash:" + hash_password(text)
            await telegram_send_async("Send the new password again to confirm it.", _back_keyboard(is_premium_user(user)), chat_id)
            return
        if security_step.startswith("password_confirm_hash:"):
            new_password_hash = security_step.split(":", 1)[1]
            _PENDING_SECURITY.pop(chat_id, None)
            if not verify_password(text, new_password_hash):
                await telegram_send_async("Password confirmation failed. Start again from Account Security.", security_keyboard(is_premium_user(user)), chat_id)
                return
            set_setting("password", new_password_hash)
            with db() as con:
                con.execute("DELETE FROM sessions")
            await telegram_send_async("Password changed successfully. All web sessions were revoked.", security_keyboard(is_premium_user(user)), chat_id)
            await security_alert(token, "Password changed", chat_id)
            return

    if text and any(text.lower().startswith(prefix) for prefix in SMART_CONFIG_SCHEMES):
        try:
            await telegram_send_async(f"{ui_emoji('📶', is_premium_user(user))} <b>Smart Testing...</b>\n\nDetecting protocols and measuring services + Iran nodes.", _back_keyboard(is_premium_user(user)), chat_id)
            result_text = await run_smart_testing(text, is_premium_user(user))
            await telegram_send_async(result_text, _back_keyboard(is_premium_user(user)), chat_id)
        except Exception as exc:
            await telegram_send_async(f"{ui_emoji('🔴', is_premium_user(user))} <b>Smart Testing failed</b>\n\n<code>{html.escape(str(exc)[:220])}</code>", _back_keyboard(is_premium_user(user)), chat_id)
        return

    pending = _PENDING_CHECKS.pop(chat_id, None)
    if pending and text and not text.startswith("/"):
        try:
            await run_check_host_flow(
                token,
                chat_id,
                user,
                pending["type"],
                text,
                pending["group"],
            )
        except Exception as exc:
            await telegram_send_async(
                f"{ui_emoji('🔴', is_premium_user(user))} <b>Check Host failed</b>\n\n<code>{html.escape(str(exc)[:180])}</code>",
                _back_keyboard(is_premium_user(user)),
                chat_id,
            )
        return

    if text in ("/start", "/menu"):
        await send_dashboard_async(token, chat_id, user)
    elif text == "/scan":
        scan = await run_scan()
        await send_scan_result_async(token, chat_id, scan, is_premium_user(user), False, _back_keyboard(is_premium_user(user)))
    elif text == "/status":
        await telegram_send_async(format_status(is_premium_user(user)), _back_keyboard(is_premium_user(user)), chat_id)
    elif text == "/smart":
        await telegram_send_async(
            f"{ui_emoji('📶', is_premium_user(user))} <b>Smart Testing</b>\n\nSend one or more supported configs. The bot will automatically test the endpoint, Instagram, Telegram, YouTube, six Iran nodes and VPS network quality.",
            _back_keyboard(is_premium_user(user)),
            chat_id,
        )
    elif text.startswith("/checkhost "):
        target = text.split(" ", 1)[1].strip()
        try:
            await run_check_host_flow(token, chat_id, user, "ping", target, "global")
        except Exception as exc:
            await telegram_send_async(f"<b>Check Host failed</b>\n<code>{html.escape(str(exc)[:180])}</code>", chat_id=chat_id)
    elif text.startswith("/ping "):
        target = text.split(" ", 1)[1].strip()
        try:
            await run_check_host_flow(token, chat_id, user, "ping", target, "global")
        except Exception as exc:
            await telegram_send_async(f"<b>Ping failed</b>\n<code>{html.escape(str(exc)[:180])}</code>", chat_id=chat_id)


async def telegram_loop():
    """Poll Telegram and handle authorized private-chat interactions."""
    offset = 0
    while True:
        token = get_setting("telegram_token")
        if not token:
            await asyncio.sleep(10)
            continue

        try:
            data = await asyncio.to_thread(
                telegram_request,
                token,
                "getUpdates",
                {"timeout": 25, "offset": offset},
            )
            for update in data.get("result", []):
                offset = update["update_id"] + 1
                callback = update.get("callback_query")
                if callback:
                    asyncio.create_task(_handle_callback_safe(token, callback))
                    continue
                message = update.get("message") or {}
                asyncio.create_task(handle_text_message(token, message))
        except Exception:
            await asyncio.sleep(5)
