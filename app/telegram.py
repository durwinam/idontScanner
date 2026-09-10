"""Telegram integration, polling and scheduled notifications."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from urllib.request import Request as URLRequest, urlopen

from app.database import (
    db,
    get_setting,
    telegram_allowed_chat,
    telegram_configured_ids,
    telegram_owner_id,
)
from app.scanner import run_scan

def telegram_request(token, method, payload=None):
    data = json.dumps(payload or {}).encode()
    request = URLRequest(
        f"https://api.telegram.org/bot{token}/{method}",
        data=data,
        headers={"Content-Type": "application/json"},
    )

    with urlopen(request, timeout=35) as response:
        return json.loads(response.read().decode())


def telegram_send(text, reply_markup=None, chat_id=None):
    token = get_setting("telegram_token")
    recipients = (
        [str(chat_id)]
        if chat_id is not None
        else telegram_configured_ids()
    )
    recipients = [
        item for item in recipients
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
            telegram_request(token, "sendMessage", payload)
            sent = True
        except Exception:
            continue

    return sent


def format_scan_message(scan):
    fastest = next(
        (
            result
            for result in scan["results"]
            if result.get("status") == "ok"
        ),
        None,
    )

    fastest_line = (
        f"🏆 Fastest: <b>{fastest['domain']}</b> · "
        f"{fastest['latency_ms']} ms"
        if fastest
        else "🏆 Fastest: <b>N/A</b>"
    )

    lines = [
        "<b>🛰 idontScanner</b>",
        "━━━━━━━━━━━━━━━━━━",
        "🔄 <b>Scheduled Scan Complete</b>",
        "",
        f"🌐 Targets: <b>{scan['total']}</b>",
        f"🟢 Online: <b>{scan['ok']}</b>",
        f"🟡 Slow: <b>{scan['slow']}</b>",
        f"🔴 Failed: <b>{scan['failed']}</b>",
        f"⚡ Average: <b>{scan['average_ms'] if scan['average_ms'] is not None else 'N/A'} ms</b>",
        f"⏱ Duration: <b>{scan['duration_ms']} ms</b>",
        "",
        fastest_line,
    ]
    return "\n".join(lines)



async def telegram_loop():
    """Poll Telegram and handle authorized owner/admin commands."""
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
                    chat_id = (
                        callback.get("message") or {}
                    ).get("chat", {}).get("id")
                    action = callback.get("data", "")

                    if chat_id and telegram_allowed_chat(chat_id):
                        if action == "scan":
                            scan = await run_scan()
                            telegram_send(
                                format_scan_message(scan),
                                chat_id=chat_id,
                            )
                        elif action == "status":
                            with db() as con:
                                row = con.execute(
                                    "SELECT * FROM scheduler WHERE id=1"
                                ).fetchone()
                            status = "ON" if row["enabled"] else "OFF"
                            telegram_send(
                                "<b>🛰 idontScanner Status</b>\n\n"
                                f"Scheduler: <b>{status}</b>\n"
                                f"Interval: <b>{row['interval_minutes']} min</b>",
                                chat_id=chat_id,
                            )
                        elif action == "scheduler":
                            with db() as con:
                                row = con.execute(
                                    "SELECT * FROM scheduler WHERE id=1"
                                ).fetchone()
                            status = "ON" if row["enabled"] else "OFF"
                            next_run = (
                                datetime.fromtimestamp(
                                    row["next_run"],
                                    timezone.utc,
                                ).isoformat()
                                if row["next_run"]
                                else "N/A"
                            )
                            telegram_send(
                                "<b>⏱ Scheduler</b>\n\n"
                                f"Status: <b>{status}</b>\n"
                                f"Next run: <b>{next_run}</b>",
                                chat_id=chat_id,
                            )
                    continue

                message = update.get("message") or {}
                chat = message.get("chat", {})
                chat_id = chat.get("id")
                chat_type = chat.get("type")
                text = (message.get("text") or "").strip()

                if not chat_id or chat_type != "private":
                    continue
                if not telegram_allowed_chat(chat_id):
                    continue

                if text in ("/start", "/menu"):
                    keyboard = {
                        "inline_keyboard": [
                            [
                                {"text": "🔍 Scan", "callback_data": "scan"},
                                {"text": "📊 Status", "callback_data": "status"},
                            ],
                            [
                                {"text": "⏱ Scheduler", "callback_data": "scheduler"},
                            ],
                        ]
                    }
                    telegram_request(
                        token,
                        "sendMessage",
                        {
                            "chat_id": chat_id,
                            "text": "<b>🛰 idontScanner</b>\n\nChoose an action:",
                            "parse_mode": "HTML",
                            "reply_markup": keyboard,
                        },
                    )
                elif text == "/scan":
                    scan = await run_scan()
                    telegram_send(
                        format_scan_message(scan),
                        chat_id=chat_id,
                    )
                elif text == "/status":
                    with db() as con:
                        row = con.execute(
                            "SELECT * FROM scheduler WHERE id=1"
                        ).fetchone()
                    status = "ON" if row["enabled"] else "OFF"
                    telegram_request(
                        token,
                        "sendMessage",
                        {
                            "chat_id": chat_id,
                            "text": (
                                "<b>🛰 idontScanner Status</b>\n\n"
                                f"Scheduler: <b>{status}</b>\n"
                                f"Interval: <b>{row['interval_minutes']} min</b>\n"
                                "Authorized: <b>YES</b>"
                            ),
                            "parse_mode": "HTML",
                        },
                    )
        except Exception:
            await asyncio.sleep(5)

