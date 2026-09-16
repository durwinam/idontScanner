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
from datetime import datetime, timezone
from urllib.request import Request as URLRequest, urlopen

from app.check_host import fetch_result, normalize_results, start_check
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
}


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
    with urlopen(request, timeout=35) as response:
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
    """Build a colored inline button using the supplied custom emoji IDs."""
    icon = BUTTON_ICONS.get(callback_data, "🔵")
    item = {
        "text": text,
        "callback_data": callback_data,
        "style": BUTTON_STYLES.get(callback_data, "primary"),
    }

    # Custom button icons are a bot capability, not a per-viewer preference.
    # Use the supplied Premium custom emoji whenever an ID is available.
    # edit_message/sendMessage below have a compatibility fallback for clients
    # or Bot API environments that reject the newer button fields.
    if icon in PREMIUM_EMOJIS:
        item["icon_custom_emoji_id"] = PREMIUM_EMOJIS[icon]
    else:
        item["text"] = f"{icon} {text}"
    return item


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
    return {
        "inline_keyboard": [
            [button("Change Username", "security_username", premium)],
            [button("Change Password", "security_password", premium)],
            [button("Reset Password", "security_reset", premium)],
            [button("Logout All Sessions", "security_logout", premium)],
            [button("Back to Menu", "menu", premium)],
        ]
    }


def security_text() -> str:
    return (
        f"<b>{ui_emoji('🔒', True)} Account Security</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Manage the panel administrator credentials and active web sessions.\n\n"
        "Only the configured Telegram Owner can use these actions.\n"
        "Passwords and session secrets are never displayed."
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
        "⚡️ Domain Scanner — scan the configured 100 domains.",
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
    """Strip Bot API 9.4 button styling/custom-icon fields for compatibility."""
    if not markup:
        return markup
    rows = []
    for row in markup.get("inline_keyboard", []):
        clean_row = []
        for item in row:
            clean = dict(item)
            clean.pop("style", None)
            clean.pop("icon_custom_emoji_id", None)
            # Preserve the visual fallback icon when custom icons are unavailable.
            if "callback_data" in clean:
                action = clean.get("callback_data", "")
                icon = BUTTON_ICONS.get(action)
                if icon and icon not in clean.get("text", ""):
                    clean["text"] = f"{icon} {clean.get('text', '')}"
            clean_row.append(clean)
        rows.append(clean_row)
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
    telegram_request(token, "sendMessage", {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "reply_markup": markup,
    })


async def handle_callback(token: str, callback: dict):
    message = callback.get("message") or {}
    chat = message.get("chat") or {}
    user = callback.get("from") or {}
    chat_id = chat.get("id")
    action = callback.get("data", "")
    message_id = message.get("message_id")
    premium = is_premium_user(user)

    callback_response(token, callback.get("id"))
    if not chat_id or chat.get("type") != "private" or not telegram_allowed_chat(chat_id):
        return

    if action == "menu":
        edit_message(token, chat_id, message_id, menu_text(premium, user.get("first_name")), main_keyboard(premium))
        return

    if action == "refresh":
        edit_message(token, chat_id, message_id, menu_text(premium, user.get("first_name")), main_keyboard(premium))
        return

    if action == "security":
        if str(chat_id) != telegram_owner_id():
            edit_message(token, chat_id, message_id, "<b>Owner access required.</b>", _back_keyboard(premium))
            return
        edit_message(token, chat_id, message_id, security_text(), security_keyboard(premium))
        return

    if action == "security_username":
        if str(chat_id) != telegram_owner_id():
            return
        _PENDING_SECURITY[chat_id] = "username"
        edit_message(token, chat_id, message_id, "<b>Change Username</b>\n\nSend the new panel username (3–32 characters).", _back_keyboard(premium))
        return

    if action == "security_password":
        if str(chat_id) != telegram_owner_id():
            return
        _PENDING_SECURITY[chat_id] = "password_current"
        edit_message(token, chat_id, message_id, "<b>Change Password</b>\n\nSend your current password. It will not be echoed back.", _back_keyboard(premium))
        return

    if action == "security_reset":
        if str(chat_id) != telegram_owner_id():
            return
        new_password = secrets.token_urlsafe(12)
        set_setting("password", hash_password(new_password))
        with db() as con:
            con.execute("DELETE FROM sessions")
        edit_message(token, chat_id, message_id, f"<b>Password reset complete.</b>\n\nYour new temporary password is:\n<code>{html.escape(new_password)}</code>\n\nAll web sessions were revoked. Save this password now; it will not be shown again.", _back_keyboard(premium))
        return

    if action == "security_logout":
        if str(chat_id) != telegram_owner_id():
            return
        with db() as con:
            con.execute("DELETE FROM sessions")
        edit_message(token, chat_id, message_id, "<b>All web sessions have been revoked.</b>", security_keyboard(premium))
        return

    if action == "scan":
        edit_message(token, chat_id, message_id, f"{ui_emoji('⚡️', premium)} <b>Scanning 100 domains...</b>", _back_keyboard(premium))
        scan = await run_scan()
        edit_message(token, chat_id, message_id, format_scan_message(scan, premium), _back_keyboard(premium))
        return

    if action == "check_host":
        edit_message(token, chat_id, message_id, format_check_host_picker(premium), check_host_keyboard(premium))
        return

    if action.startswith("check_"):
        if action in {"check_global", "check_iran"}:
            group = "iran" if action == "check_iran" else "global"
            _PENDING_CHECKS[chat_id] = {"type": "ping", "group": group}
            label = "Iran · 6 Nodes" if group == "iran" else "Global"
            edit_message(token, chat_id, message_id, f"<b>{label}</b>\n\nSend the hostname or IP to check.", _back_keyboard(premium))
            return

        check_type = action.removeprefix("check_")
        _PENDING_CHECKS[chat_id] = {"type": check_type, "group": "global"}
        edit_message(token, chat_id, message_id, f"<b>{check_type.upper()} Check</b>\n\nSend the hostname or IP to check.", _back_keyboard(premium))
        return

    if action == "smart":
        edit_message(token, chat_id, message_id, f"{ui_emoji('📶', premium)} <b>Measuring connection quality...</b>", _back_keyboard(premium))
        try:
            result = await asyncio.to_thread(measure_network_quality)
            text = format_network_quality(result, premium)
        except Exception as exc:
            text = f"{ui_emoji('🔴', premium)} <b>Connection test failed</b>\n\n<code>{html.escape(str(exc)[:180])}</code>"
        edit_message(token, chat_id, message_id, text, _back_keyboard(premium))
        return

    if action == "speed":
        edit_message(token, chat_id, message_id, f"{ui_emoji('⏲', premium)} <b>Running VPS network test...</b>", _back_keyboard(premium))
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
        edit_message(token, chat_id, message_id, text, _back_keyboard(premium))
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
        edit_message(token, chat_id, message_id, handlers[action](), _back_keyboard(premium))


async def handle_text_message(token: str, message: dict):
    chat = message.get("chat") or {}
    user = message.get("from") or {}
    chat_id = chat.get("id")
    text = (message.get("text") or "").strip()
    if not chat_id or chat.get("type") != "private" or not telegram_allowed_chat(chat_id):
        return

    security_step = _PENDING_SECURITY.get(chat_id)
    if security_step and str(chat_id) == telegram_owner_id() and text and not text.startswith("/"):
        if security_step == "username":
            if not 3 <= len(text) <= 32:
                telegram_send("Username must be between 3 and 32 characters.", _back_keyboard(is_premium_user(user)), chat_id)
            else:
                set_setting("username", text)
                _PENDING_SECURITY.pop(chat_id, None)
                telegram_send("Username changed successfully.", security_keyboard(is_premium_user(user)), chat_id)
            return
        if security_step == "password_current":
            if not verify_password(text, get_setting("password")):
                telegram_send("Current password is incorrect.", _back_keyboard(is_premium_user(user)), chat_id)
                return
            _PENDING_SECURITY[chat_id] = "password_new"
            telegram_send("Current password accepted. Send the new password (minimum 8 characters).", _back_keyboard(is_premium_user(user)), chat_id)
            return
        if security_step == "password_new":
            if len(text) < 8:
                telegram_send("New password must contain at least 8 characters.", _back_keyboard(is_premium_user(user)), chat_id)
                return
            _PENDING_SECURITY[chat_id] = "password_confirm:" + text
            telegram_send("Send the new password again to confirm it.", _back_keyboard(is_premium_user(user)), chat_id)
            return
        if security_step.startswith("password_confirm:"):
            new_password = security_step.split(":", 1)[1]
            _PENDING_SECURITY.pop(chat_id, None)
            if text != new_password:
                telegram_send("Password confirmation failed. Start again from Account Security.", security_keyboard(is_premium_user(user)), chat_id)
                return
            set_setting("password", hash_password(new_password))
            with db() as con:
                con.execute("DELETE FROM sessions")
            telegram_send("Password changed successfully. All web sessions were revoked.", security_keyboard(is_premium_user(user)), chat_id)
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
            telegram_send(
                f"{ui_emoji('🔴', is_premium_user(user))} <b>Check Host failed</b>\n\n<code>{html.escape(str(exc)[:180])}</code>",
                _back_keyboard(is_premium_user(user)),
                chat_id,
            )
        return

    if text in ("/start", "/menu"):
        send_dashboard(token, chat_id, user)
    elif text == "/scan":
        scan = await run_scan()
        telegram_send(format_scan_message(scan, is_premium_user(user)), chat_id=chat_id)
    elif text == "/status":
        telegram_send(format_status(is_premium_user(user)), _back_keyboard(is_premium_user(user)), chat_id)
    elif text.startswith("/checkhost "):
        target = text.split(" ", 1)[1].strip()
        try:
            await run_check_host_flow(token, chat_id, user, "ping", target, "global")
        except Exception as exc:
            telegram_send(f"<b>Check Host failed</b>\n<code>{html.escape(str(exc)[:180])}</code>", chat_id=chat_id)
    elif text.startswith("/ping "):
        target = text.split(" ", 1)[1].strip()
        try:
            await run_check_host_flow(token, chat_id, user, "ping", target, "global")
        except Exception as exc:
            telegram_send(f"<b>Ping failed</b>\n<code>{html.escape(str(exc)[:180])}</code>", chat_id=chat_id)


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
                    await handle_callback(token, callback)
                    continue
                message = update.get("message") or {}
                await handle_text_message(token, message)
        except Exception:
            await asyncio.sleep(5)
