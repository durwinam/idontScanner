"""Telegram integration, polling, premium-aware UI and notifications."""

from __future__ import annotations

import asyncio
import html
import json
from datetime import datetime, timezone
from urllib.request import Request as URLRequest, urlopen

from app.database import (
    db,
    get_setting,
    telegram_allowed_chat,
    telegram_configured_ids,
)
from app.scanner import run_scan


# Telegram custom emoji identifiers are intentionally kept in this module so
# the Premium UI can be changed without touching the rest of the application.
#
# This identifier is the Telegram custom emoji identifier used by the Bot API
# documentation example. Replace it with another valid custom emoji ID if you
# want a different Premium icon.
PREMIUM_EMOJI_ID = "5368324170671202286"
PREMIUM_EMOJI_FALLBACK = "👍"


MENU_ITEMS = {
    "scan": ("Scan", "🔍"),
    "status": ("Status", "📊"),
    "history": ("History", "📜"),
    "domains": ("Domains", "🌐"),
    "scheduler": ("Scheduler", "⏱️"),
    "diagnostics": ("Diagnostics", "🧪"),
    "refresh": ("Refresh", "🔄"),
    "help": ("Help", "ℹ️"),
    "telegram_settings": ("Telegram Settings", "⚙️"),
}


def telegram_request(token, method, payload=None):
    """Call one Telegram Bot API method and return its decoded response."""
    data = json.dumps(payload or {}).encode()

    request = URLRequest(
        f"https://api.telegram.org/bot{token}/{method}",
        data=data,
        headers={"Content-Type": "application/json"},
    )

    with urlopen(request, timeout=35) as response:
        return json.loads(response.read().decode())


def telegram_send(text, reply_markup=None, chat_id=None):
    """Send a message to one chat or all configured Telegram recipients."""
    token = get_setting("telegram_token")

    recipients = (
        [str(chat_id)]
        if chat_id is not None
        else telegram_configured_ids()
    )

    recipients = [
        item
        for item in recipients
        if telegram_allowed_chat(item)
    ]

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
            telegram_request(
                token,
                "sendMessage",
                payload,
            )
            sent = True
        except Exception:
            continue

    return sent


def is_premium_user(user):
    """Return Telegram's Premium status for an incoming user object."""
    return bool(
        (user or {}).get("is_premium", False)
    )


def premium_emoji():
    """
    Return a Telegram custom emoji entity.

    The fallback character keeps the message readable if Telegram cannot
    render the custom emoji entity.
    """
    return (
        f'<tg-emoji emoji-id="{PREMIUM_EMOJI_ID}">'
        f"{PREMIUM_EMOJI_FALLBACK}"
        "</tg-emoji>"
    )


def ui_emoji(emoji, premium):
    """Select a Premium custom emoji or a normal Unicode emoji."""
    if premium:
        return premium_emoji()

    return emoji


def button(text, emoji, callback_data, premium):
    """
    Build an inline keyboard button.

    Standard users receive normal Unicode icons.
    Premium users receive Telegram custom emoji button icons.
    """
    item = {
        "text": text,
        "callback_data": callback_data,
    }

    if premium:
        item["icon_custom_emoji_id"] = PREMIUM_EMOJI_ID
    else:
        item["text"] = f"{emoji} {text}"

    return item


def main_keyboard(premium):
    """Build the personalized main Telegram keyboard."""
    return {
        "inline_keyboard": [
            [
                button(
                    "Scan",
                    "🔍",
                    "scan",
                    premium,
                ),
                button(
                    "Status",
                    "📊",
                    "status",
                    premium,
                ),
            ],
            [
                button(
                    "History",
                    "📜",
                    "history",
                    premium,
                ),
                button(
                    "Domains",
                    "🌐",
                    "domains",
                    premium,
                ),
            ],
            [
                button(
                    "Scheduler",
                    "⏱️",
                    "scheduler",
                    premium,
                ),
                button(
                    "Diagnostics",
                    "🧪",
                    "diagnostics",
                    premium,
                ),
            ],
            [
                button(
                    "Refresh",
                    "🔄",
                    "refresh",
                    premium,
                ),
                button(
                    "Help",
                    "ℹ️",
                    "help",
                    premium,
                ),
            ],
            [
                button(
                    "Telegram Settings",
                    "⚙️",
                    "telegram_settings",
                    premium,
                ),
            ],
        ]
    }


def menu_text(premium, first_name=None):
    """Build the personalized dashboard header."""
    name = html.escape(
        first_name or "User"
    )

    badge = (
        f" {premium_emoji()}"
        if premium
        else ""
    )

    tier = (
        "Premium"
        if premium
        else "Standard"
    )

    return (
        f"<b>🛰 idontScanner</b>{badge}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>{name}</b> · <b>{tier}</b>\n\n"
        f"{ui_emoji('✨', premium)} "
        "<b>Choose an action:</b>"
    )


def format_scan_message(
    scan,
    premium=False,
    scheduled=False,
):
    """Format a complete scan summary with latency rankings."""
    results = scan.get(
        "results",
        [],
    )

    successful = [
        result
        for result in results
        if result.get("status") == "ok"
        and result.get("latency_ms") is not None
    ]

    fastest = (
        min(
            successful,
            key=lambda item: item["latency_ms"],
        )
        if successful
        else None
    )

    slowest = (
        max(
            successful,
            key=lambda item: item["latency_ms"],
        )
        if successful
        else None
    )

    ranked = {
        "excellent": 0,
        "good": 0,
        "normal": 0,
        "slow": 0,
        "very_slow": 0,
        "critical": 0,
    }

    for result in successful:
        latency = float(
            result["latency_ms"]
        )

        if latency < 100:
            ranked["excellent"] += 1
        elif latency < 250:
            ranked["good"] += 1
        elif latency < 500:
            ranked["normal"] += 1
        elif latency < 1000:
            ranked["slow"] += 1
        elif latency < 2000:
            ranked["very_slow"] += 1
        else:
            ranked["critical"] += 1

    if fastest:
        fastest_line = (
            "🏆 Fastest: "
            f"<b>{html.escape(fastest['domain'])}</b> · "
            f"{fastest['latency_ms']} ms"
        )
    else:
        fastest_line = (
            "🏆 Fastest: <b>N/A</b>"
        )

    if slowest:
        slowest_line = (
            "🐢 Slowest: "
            f"<b>{html.escape(slowest['domain'])}</b> · "
            f"{slowest['latency_ms']} ms"
        )
    else:
        slowest_line = (
            "🐢 Slowest: <b>N/A</b>"
        )

    title = (
        "Scheduled Scan Complete"
        if scheduled
        else "Scan Complete"
    )

    average = scan.get(
        "average_ms"
    )

    average_text = (
        f"{average} ms"
        if average is not None
        else "N/A"
    )

    duration = scan.get(
        "duration_ms",
        "N/A",
    )

    lines = [
        "<b>🛰 idontScanner</b>",
        "━━━━━━━━━━━━━━━━━━",
        (
            f"{ui_emoji('🔄', premium)} "
            f"<b>{title}</b>"
        ),
        "",
        (
            f"🌐 Targets: "
            f"<b>{scan.get('total', 0)}</b>"
        ),
        (
            f"🟢 Online: "
            f"<b>{scan.get('ok', 0)}</b>"
        ),
        (
            f"🟡 Slow: "
            f"<b>{scan.get('slow', 0)}</b>"
        ),
        (
            f"🔴 Failed: "
            f"<b>{scan.get('failed', 0)}</b>"
        ),
        "",
        (
            f"⚡ Average: "
            f"<b>{average_text}</b>"
        ),
        (
            f"⏱ Duration: "
            f"<b>{duration} ms</b>"
        ),
        "",
        "<b>🏅 Performance Ranks</b>",
        (
            f"⚡ Excellent: "
            f"<b>{ranked['excellent']}</b>"
            "  ·  "
            f"🟢 Good: "
            f"<b>{ranked['good']}</b>"
        ),
        (
            f"🔵 Normal: "
            f"<b>{ranked['normal']}</b>"
            "  ·  "
            f"🟡 Slow: "
            f"<b>{ranked['slow']}</b>"
        ),
        (
            f"🟠 Very Slow: "
            f"<b>{ranked['very_slow']}</b>"
            "  ·  "
            f"🔴 Critical: "
            f"<b>{ranked['critical']}</b>"
        ),
        "",
        fastest_line,
        slowest_line,
    ]

    return "\n".join(lines)


def scheduler_row():
    """Return the global scheduler configuration."""
    with db() as con:
        return con.execute(
            "SELECT * FROM scheduler WHERE id=1"
        ).fetchone()


def format_status(premium):
    """Format scheduler and service status."""
    row = scheduler_row()

    if not row:
        return (
            "<b>🛰 idontScanner Status</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "🔴 Scheduler configuration not found."
        )

    status = (
        "ON"
        if row["enabled"]
        else "OFF"
    )

    return (
        "<b>🛰 idontScanner Status</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"{ui_emoji('🟢', premium)} "
        f"Scheduler: <b>{status}</b>\n"
        f"⏱ Interval: "
        f"<b>{row['interval_minutes']} min</b>\n"
        "🔐 Authorized: <b>YES</b>"
    )


def format_scheduler(premium):
    """Format detailed scheduler information."""
    row = scheduler_row()

    if not row:
        return (
            "<b>⏱ Scheduler</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "🔴 Scheduler configuration not found."
        )

    status = (
        "ON"
        if row["enabled"]
        else "OFF"
    )

    next_run = (
        datetime.fromtimestamp(
            row["next_run"],
            timezone.utc,
        ).isoformat()
        if row["next_run"]
        else "N/A"
    )

    status_emoji = (
        "🟢"
        if row["enabled"]
        else "🔴"
    )

    return (
        "<b>⏱ Scheduler</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"{ui_emoji(status_emoji, premium)} "
        f"Status: <b>{status}</b>\n"
        f"🔁 Interval: "
        f"<b>{row['interval_minutes']} min</b>\n"
        f"🕒 Next run: "
        f"<b>{html.escape(next_run)}</b>"
    )


def format_history():
    """Format the five latest scan records."""
    with db() as con:
        rows = con.execute(
            """
            SELECT
                id,
                started_at,
                total,
                ok,
                slow,
                failed,
                average_ms,
                duration_ms
            FROM scans
            ORDER BY id DESC
            LIMIT 5
            """
        ).fetchall()

    if not rows:
        return (
            "<b>📜 Scan History</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "No scans recorded yet."
        )

    lines = [
        "<b>📜 Scan History</b>",
        "━━━━━━━━━━━━━━━━━━",
    ]

    for row in rows:
        stamp = datetime.fromtimestamp(
            row["started_at"],
            timezone.utc,
        ).strftime(
            "%Y-%m-%d %H:%M"
        )

        average = row["average_ms"]

        average_text = (
            f"{average} ms"
            if average is not None
            else "N/A"
        )

        lines.append(
            f"<b>#{row['id']}</b> · {stamp}\n"
            f"🌐 {row['total']} · "
            f"🟢 {row['ok']} · "
            f"🟡 {row['slow']} · "
            f"🔴 {row['failed']} · "
            f"⚡ {average_text}"
        )

    return "\n\n".join(lines)


def format_domains():
    """Format configured domain statistics."""
    with db() as con:
        total = con.execute(
            "SELECT COUNT(*) FROM domains"
        ).fetchone()[0]

        enabled = con.execute(
            "SELECT COUNT(*) FROM domains WHERE enabled=1"
        ).fetchone()[0]

        categories = con.execute(
            """
            SELECT
                category,
                COUNT(*) AS amount
            FROM domains
            WHERE enabled=1
            GROUP BY category
            ORDER BY amount DESC, category ASC
            LIMIT 8
            """
        ).fetchall()

    lines = [
        "<b>🌐 Domains</b>",
        "━━━━━━━━━━━━━━━━━━",
        f"Total: <b>{total}</b>",
        f"Enabled: <b>{enabled}</b>",
        "",
        "<b>Categories</b>",
    ]

    if categories:
        lines.extend(
            (
                f"• {html.escape(row['category'])}: "
                f"<b>{row['amount']}</b>"
            )
            for row in categories
        )
    else:
        lines.append(
            "No enabled domain categories."
        )

    return "\n".join(lines)


def format_diagnostics(premium):
    """Format basic Telegram and database diagnostics."""
    row = scheduler_row()

    token_configured = bool(
        get_setting("telegram_token")
    )

    owner_configured = bool(
        get_setting("telegram_owner_id")
    )

    admins_configured = bool(
        get_setting("telegram_admin_ids")
    )

    scheduler_enabled = bool(
        row and row["enabled"]
    )

    return "\n".join(
        [
            "<b>🧪 Diagnostics</b>",
            "━━━━━━━━━━━━━━━━━━",
            (
                f"{ui_emoji('🟢', premium)} "
                "Database: <b>OK</b>"
            ),
            (
                f"{ui_emoji("
                "'🟢' if token_configured else '🔴'",
                premium,
                )} "
                "Telegram Token: "
                f"<b>{"
                "'Configured' "
                "if token_configured "
                "else 'Missing'"
                }</b>"
            ),
            (
                f"{ui_emoji("
                "'🟢' if owner_configured else '🔴'",
                premium,
                )} "
                "Owner ID: "
                f"<b>{"
                "'Configured' "
                "if owner_configured "
                "else 'Missing'"
                }</b>"
            ),
            (
                f"{ui_emoji("
                "'🟢' if admins_configured else '🟡'",
                premium,
                )} "
                "Admin IDs: "
                f"<b>{"
                "'Configured' "
                "if admins_configured "
                "else 'Not set'"
                }</b>"
            ),
            (
                f"{ui_emoji("
                "'🟢' if scheduler_enabled else '🟡'",
                premium,
                )} "
                "Scheduler: "
                f"<b>{"
                "'Running' "
                "if scheduler_enabled "
                "else 'Disabled'"
                }</b>"
            ),
        ]
    )


def format_help():
    """Format Telegram bot help information."""
    return (
        "<b>ℹ️ idontScanner Help</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "Use the buttons for the main controls.\n\n"
        "<b>Commands</b>\n"
        "/start — Open dashboard\n"
        "/menu — Open dashboard\n"
        "/scan — Run a scan\n"
        "/status — Show scheduler status\n\n"
        "Premium users receive the Premium UI automatically."
    )


def format_telegram_settings():
    """Format Telegram configuration status without exposing secrets."""
    token_configured = bool(
        get_setting("telegram_token")
    )

    owner_configured = bool(
        get_setting("telegram_owner_id")
    )

    admins_configured = bool(
        get_setting("telegram_admin_ids")
    )

    return (
        "<b>⚙️ Telegram Settings</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "Bot Token: "
        f"<b>{"
        "'Configured' "
        "if token_configured "
        "else 'Missing'"
        }</b>\n"
        "Owner ID: "
        f"<b>{"
        "'Configured' "
        "if owner_configured "
        "else 'Missing'"
        }</b>\n"
        "Admin IDs: "
        f"<b>{"
        "'Configured' "
        "if admins_configured "
        "else 'Not set'"
        }</b>\n\n"
        "Sensitive credentials are never displayed here."
    )


def edit_menu(
    token,
    chat_id,
    message_id,
    premium,
    first_name=None,
):
    """Edit the existing dashboard message."""
    return telegram_request(
        token,
        "editMessageText",
        {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": menu_text(
                premium,
                first_name,
            ),
            "parse_mode": "HTML",
            "reply_markup": main_keyboard(
                premium
            ),
        },
    )


def callback_response(
    token,
    callback_id,
):
    """Acknowledge a callback immediately."""
    if not callback_id:
        return

    try:
        telegram_request(
            token,
            "answerCallbackQuery",
            {
                "callback_query_id": callback_id,
            },
        )
    except Exception:
        pass


def send_dashboard(
    token,
    chat_id,
    user,
):
    """Send the personalized Telegram dashboard."""
    premium = is_premium_user(user)

    return telegram_request(
        token,
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": menu_text(
                premium,
                user.get("first_name"),
            ),
            "parse_mode": "HTML",
            "reply_markup": main_keyboard(
                premium
            ),
        },
    )


def back_keyboard(premium):
    """Build a one-button navigation keyboard."""
    return {
        "inline_keyboard": [
            [
                button(
                    "Back to Menu",
                    "↩️",
                    "menu",
                    premium,
                )
            ]
        ]
    }


def send_action_result(
    token,
    chat_id,
    user,
    action,
    message_id=None,
):
    """Handle a dashboard action and keep navigation in one message."""
    premium = is_premium_user(user)

    first_name = user.get(
        "first_name"
    )

    if action == "scan":
        return None

    if action == "status":
        text = format_status(
            premium
        )

    elif action == "history":
        text = format_history()

    elif action == "domains":
        text = format_domains()

    elif action == "scheduler":
        text = format_scheduler(
            premium
        )

    elif action == "diagnostics":
        text = format_diagnostics(
            premium
        )

    elif action == "help":
        text = format_help()

    elif action == "telegram_settings":
        text = format_telegram_settings()

    elif action == "refresh":
        if message_id is None:
            return send_dashboard(
                token,
                chat_id,
                user,
            )

        return edit_menu(
            token,
            chat_id,
            message_id,
            premium,
            first_name,
        )

    else:
        return None

    markup = back_keyboard(
        premium
    )

    if message_id is not None:
        return telegram_request(
            token,
            "editMessageText",
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text,
                "parse_mode": "HTML",
                "reply_markup": markup,
            },
        )

    return telegram_request(
        token,
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "reply_markup": markup,
        },
    )


async def handle_callback(
    token,
    callback,
):
    """Process one authorized inline-keyboard callback."""
    message = (
        callback.get("message")
        or {}
    )

    chat = (
        message.get("chat")
        or {}
    )

    user = (
        callback.get("from")
        or {}
    )

    chat_id = chat.get("id")

    action = callback.get(
        "data",
        "",
    )

    message_id = message.get(
        "message_id"
    )

    callback_response(
        token,
        callback.get("id"),
    )

    if not chat_id:
        return

    if chat.get("type") != "private":
        return

    if not telegram_allowed_chat(
        chat_id
    ):
        return

    premium = is_premium_user(
        user
    )

    if action == "menu":
        if message_id is None:
            send_dashboard(
                token,
                chat_id,
                user,
            )
            return

        edit_menu(
            token,
            chat_id,
            message_id,
            premium,
            user.get("first_name"),
        )
        return

    if action == "scan":
        scan = await run_scan()

        telegram_request(
            token,
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": format_scan_message(
                    scan,
                    premium,
                ),
                "parse_mode": "HTML",
                "reply_markup": back_keyboard(
                    premium
                ),
            },
        )
        return

    send_action_result(
        token,
        chat_id,
        user,
        action,
        message_id=message_id,
    )


async def telegram_loop():
    """
    Poll Telegram continuously.

    Only private chats that pass telegram_allowed_chat() are processed.
    """
    offset = 0

    while True:
        token = get_setting(
            "telegram_token"
        )

        if not token:
            await asyncio.sleep(
                10
            )
            continue

        try:
            data = await asyncio.to_thread(
                telegram_request,
                token,
                "getUpdates",
                {
                    "timeout": 25,
                    "offset": offset,
                },
            )

            for update in data.get(
                "result",
                [],
            ):
                offset = (
                    update["update_id"]
                    + 1
                )

                callback = update.get(
                    "callback_query"
                )

                if callback:
                    await handle_callback(
                        token,
                        callback,
                    )
                    continue

                message = (
                    update.get("message")
                    or {}
                )

                chat = (
                    message.get("chat")
                    or {}
                )

                user = (
                    message.get("from")
                    or {}
                )

                chat_id = chat.get(
                    "id"
                )

                chat_type = chat.get(
                    "type"
                )

                text = (
                    message.get("text")
                    or ""
                ).strip()

                if not chat_id:
                    continue

                if chat_type != "private":
                    continue

                if not telegram_allowed_chat(
                    chat_id
                ):
                    continue

                premium = is_premium_user(
                    user
                )

                if text in (
                    "/start",
                    "/menu",
                ):
                    send_dashboard(
                        token,
                        chat_id,
                        user,
                    )

                elif text == "/scan":
                    scan = await run_scan()

                    telegram_request(
                        token,
                        "sendMessage",
                        {
                            "chat_id": chat_id,
                            "text": format_scan_message(
                                scan,
                                premium,
                            ),
                            "parse_mode": "HTML",
                            "reply_markup": back_keyboard(
                                premium
                            ),
                        },
                    )

                elif text == "/status":
                    telegram_request(
                        token,
                        "sendMessage",
                        {
                            "chat_id": chat_id,
                            "text": format_status(
                                premium
                            ),
                            "parse_mode": "HTML",
                            "reply_markup": back_keyboard(
                                premium
                            ),
                        },
                    )

        except Exception:
            await asyncio.sleep(
                5
            )
