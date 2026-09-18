"""Background scheduler for recurring domain scans."""

from __future__ import annotations

import asyncio
import time

from app.database import db, get_setting, telegram_configured_ids
from app.scanner import run_scan
from app.telegram import send_scan_result_async


async def scheduler_loop():
    """Run due scans and deliver configured Telegram notifications."""
    while True:
        try:
            with db() as con:
                row = con.execute(
                    "SELECT * FROM scheduler WHERE id = 1"
                ).fetchone()

            now = int(time.time())
            due = (
                row is not None
                and row["enabled"]
                and row["next_run"]
                and now >= row["next_run"]
            )

            if due:
                scan = await run_scan()
                next_run = now + int(row["interval_minutes"]) * 60

                with db() as con:
                    con.execute(
                        """
                        UPDATE scheduler
                        SET last_run = ?, next_run = ?
                        WHERE id = 1
                        """,
                        (now, next_run),
                    )

                if row["notify_mode"] == "all":
                    token = get_setting("telegram_token")
                    for chat_id in telegram_configured_ids():
                        await send_scan_result_async(token, chat_id, scan, True, True)
                elif row["notify_mode"] == "changes":
                    failed = [
                        result
                        for result in scan["results"]
                        if result.get("status") != "ok"
                    ]
                    if failed:
                        token = get_setting("telegram_token")
                        for chat_id in telegram_configured_ids():
                            await send_scan_result_async(token, chat_id, scan, True, True)
        except Exception:
            await asyncio.sleep(5)

        await asyncio.sleep(30)
