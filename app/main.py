"""FastAPI application and HTTP routes for idontScanner."""

from __future__ import annotations

import asyncio
import hmac
import os
import shutil
import ipaddress
import urllib.request
import urllib.error
import socket
import sqlite3
import ssl
import time
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app.auth import hash_password, verify_password
from app.config import BASE, BASE_PATH, SECRET, TIMEOUT
from app.connection import diagnose_config, parse_config, probe_services
from app.database import (
    db,
    get_setting,
    init_db,
    set_setting,
    telegram_admin_ids,
    telegram_configured_ids,
    telegram_owner_id,
)
from app.scanner import peer_certificate_details, run_scan, tls_probe
from app.security import (
    csrf,
    require_auth,
    remember_session,
    server_ip,
    valid_domain,
)
from app.telegram import telegram_request


app = FastAPI(
    title="idontScanner",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.mount(
    "/static",
    StaticFiles(directory=str(BASE / "static")),
    name="static",
)
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET,
    session_cookie="idontscanner_session",
    https_only=False,
    same_site="lax",
    max_age=3600,
)

templates = Jinja2Templates(directory=str(BASE / "templates"))
scheduler_task: asyncio.Task | None = None
telegram_task: asyncio.Task | None = None


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Apply conservative browser security and cache headers."""
    response = await call_next(request)

    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=()"
    )

    if request.url.path.startswith("/api/") or request.url.path in {
        "/login/",
        "/logout/",
    }:
        response.headers["Cache-Control"] = "no-store"
    else:
        response.headers["Cache-Control"] = "private, max-age=60"

    return response


async def _authorized_json(request: Request):
    """Return the parsed JSON body after authentication and CSRF checks."""
    if not require_auth(request):
        return None, JSONResponse({"error": "unauthorized"}, status_code=401)

    body = await request.json()
    if not hmac.compare_digest(csrf(request), str(body.get("csrf", ""))):
        return None, JSONResponse({"error": "csrf"}, status_code=403)

    return body, None


def _redirect_to_login():
    return RedirectResponse("/login/", status_code=303)


def _page_context(request: Request, **extra):
    with db() as con:
        scheduler = con.execute(
            "SELECT * FROM scheduler WHERE id = 1"
        ).fetchone()
        sessions = con.execute(
            """
            SELECT *
            FROM sessions
            ORDER BY id DESC
            LIMIT 3
            """
        ).fetchall()

    return {
        "request": request,
        "base": BASE_PATH,
        "csrf": csrf(request),
        "username": get_setting("username", "admin"),
        "server_ip": server_ip(),
        "scheduler": scheduler,
        "sessions": sessions,
        **extra,
    }


@app.on_event("startup")
async def startup():
    """Initialize persistence and start background workers."""
    global scheduler_task, telegram_task

    init_db()

    from app.scheduler import scheduler_loop
    from app.telegram import telegram_loop

    scheduler_task = asyncio.create_task(scheduler_loop())
    telegram_task = asyncio.create_task(telegram_loop())


@app.on_event("shutdown")
async def shutdown():
    """Stop background workers during application shutdown."""
    for task in (scheduler_task, telegram_task):
        if task:
            task.cancel()


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    destination = "/dashboard/" if require_auth(request) else "/login/"
    return RedirectResponse(destination, status_code=303)


@app.get("/login/", response_class=HTMLResponse)
async def login_page(request: Request):
    with db() as con:
        password_row = con.execute(
            "SELECT value FROM settings WHERE key = 'password'"
        ).fetchone()

    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "base": BASE_PATH,
            "setup": password_row is None,
            "csrf": csrf(request),
        },
    )


@app.post("/login/")
async def login(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
    csrf_token: str = Form(""),
):
    if not hmac.compare_digest(csrf(request), csrf_token):
        return RedirectResponse("/login/?error=csrf", status_code=303)

    with db() as con:
        user_row = con.execute(
            "SELECT value FROM settings WHERE key = 'username'"
        ).fetchone()
        password_row = con.execute(
            "SELECT value FROM settings WHERE key = 'password'"
        ).fetchone()

        if password_row is None:
            if not 3 <= len(username) <= 32 or len(password) < 8:
                return RedirectResponse("/login/?error=weak", status_code=303)

            con.execute(
                "INSERT OR REPLACE INTO settings(key, value) VALUES('username', ?)",
                (username,),
            )
            con.execute(
                "INSERT OR REPLACE INTO settings(key, value) VALUES('password', ?)",
                (hash_password(password),),
            )
        else:
            stored_username = user_row[0] if user_row else "admin"
            if username != stored_username or not verify_password(
                password,
                password_row[0],
            ):
                return RedirectResponse("/login/?error=invalid", status_code=303)

    request.session.clear()
    request.session["auth"] = True
    request.session["csrf"] = csrf(request)
    remember_session(request)

    return RedirectResponse("/dashboard/", status_code=303)


@app.get("/logout/")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login/", status_code=303)



_cpu_sample: tuple[int, int] | None = None
_network_sample: tuple[int, int, float] | None = None


def _read_cpu_times() -> tuple[int, int]:
    with open("/proc/stat", "r", encoding="utf-8") as handle:
        fields = handle.readline().split()

    values = [int(value) for value in fields[1:]]
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    return sum(values), idle


async def _cpu_percent() -> float:
    global _cpu_sample

    first = await asyncio.to_thread(_read_cpu_times)
    await asyncio.sleep(0.12)
    second = await asyncio.to_thread(_read_cpu_times)

    if _cpu_sample is not None:
        first = _cpu_sample
    _cpu_sample = second

    total_delta = second[0] - first[0]
    idle_delta = second[1] - first[1]
    if total_delta <= 0:
        return 0.0

    return round(max(0.0, min(100.0, (1 - idle_delta / total_delta) * 100)), 1)


def _memory_stats() -> tuple[float, float, float]:
    values: dict[str, int] = {}
    with open("/proc/meminfo", "r", encoding="utf-8") as handle:
        for line in handle:
            key, raw = line.split(":", 1)
            values[key] = int(raw.strip().split()[0]) * 1024

    total = values.get("MemTotal", 0)
    available = values.get("MemAvailable", values.get("MemFree", 0))
    used = max(0, total - available)
    percent = (used / total * 100) if total else 0
    return round(percent, 1), used / 1024**3, total / 1024**3


def _disk_stats() -> tuple[float, float, float]:
    usage = shutil.disk_usage(BASE)
    percent = usage.used / usage.total * 100 if usage.total else 0
    return round(percent, 1), usage.used / 1024**3, usage.total / 1024**3


def _process_count() -> int:
    try:
        return sum(name.isdigit() for name in os.listdir("/proc"))
    except OSError:
        return 0


def _uptime() -> str:
    try:
        seconds = int(float(Path("/proc/uptime").read_text().split()[0]))
    except (OSError, ValueError, IndexError):
        return "—"

    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return " ".join(parts)


def _network_bytes() -> tuple[int, int]:
    received = sent = 0
    try:
        lines = Path("/proc/net/dev").read_text().splitlines()[2:]
        for line in lines:
            interface, data = line.split(":", 1)
            if interface.strip() == "lo":
                continue
            fields = data.split()
            if len(fields) >= 9:
                received += int(fields[0])
                sent += int(fields[8])
    except (OSError, ValueError, IndexError):
        pass
    return received, sent


def _network_rate() -> tuple[float, float]:
    global _network_sample

    received, sent = _network_bytes()
    now = time.monotonic()
    if _network_sample is None:
        _network_sample = (received, sent, now)
        return 0.0, 0.0

    old_received, old_sent, old_time = _network_sample
    _network_sample = (received, sent, now)
    elapsed = max(0.1, now - old_time)
    down = max(0, received - old_received) / elapsed / 1024**2
    up = max(0, sent - old_sent) / elapsed / 1024**2
    return round(down, 1), round(up, 1)


def _temperature() -> float | None:
    thermal_root = Path("/sys/class/thermal")
    try:
        for path in sorted(thermal_root.glob("thermal_zone*/temp")):
            raw = path.read_text().strip()
            value = float(raw)
            if value > 1000:
                value /= 1000
            if 0 < value < 120:
                return round(value, 1)
    except (OSError, ValueError):
        pass
    return None


@app.get("/api/system/stats")
async def system_stats(request: Request):
    if not require_auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    cpu, memory, disk = await asyncio.gather(
        _cpu_percent(),
        asyncio.to_thread(_memory_stats),
        asyncio.to_thread(_disk_stats),
    )
    memory_percent, memory_used, memory_total = memory
    disk_percent, disk_used, disk_total = disk
    load = os.getloadavg() if hasattr(os, "getloadavg") else (0.0, 0.0, 0.0)
    down, up = _network_rate()

    return {
        "cpu": {"percent": cpu, "cores": os.cpu_count() or 1},
        "memory": {
            "percent": memory_percent,
            "used_gb": round(memory_used, 2),
            "total_gb": round(memory_total, 2),
        },
        "disk": {
            "percent": disk_percent,
            "used_gb": round(disk_used, 2),
            "total_gb": round(disk_total, 2),
        },
        "load": round(load[0], 2),
        "processes": _process_count(),
        "uptime": _uptime(),
        "network": {"down_mbps": down, "up_mbps": up},
        "temperature": _temperature(),
        "timestamp": int(time.time()),
    }


@app.get("/dashboard/", response_class=HTMLResponse)
async def dashboard(request: Request):
    if not require_auth(request):
        return _redirect_to_login()

    with db() as con:
        domains = con.execute(
            """
            SELECT *
            FROM domains
            ORDER BY is_default DESC, label COLLATE NOCASE
            """
        ).fetchall()
        latest = con.execute(
            "SELECT * FROM scans ORDER BY id DESC LIMIT 1"
        ).fetchone()

    return templates.TemplateResponse(
        "dashboard.html",
        _page_context(
            request,
            domains=domains,
            latest=latest,
            active="dashboard",
        ),
    )


@app.get("/scanner/", response_class=HTMLResponse)
async def scanner_page(request: Request):
    if not require_auth(request):
        return _redirect_to_login()

    with db() as con:
        domains = con.execute(
            """
            SELECT *
            FROM domains
            ORDER BY is_default DESC, label COLLATE NOCASE
            """
        ).fetchall()

    return templates.TemplateResponse(
        "scanner.html",
        _page_context(request, domains=domains, active="scanner"),
    )


@app.get("/speed-test/", response_class=HTMLResponse)
async def speed_test_page(request: Request):
    if not require_auth(request):
        return _redirect_to_login()
    return templates.TemplateResponse(
        "speed_test.html",
        _page_context(request, active="speed_test"),
    )


@app.get("/connection/", response_class=HTMLResponse)
async def connection_page(request: Request):
    if not require_auth(request):
        return _redirect_to_login()

    return templates.TemplateResponse(
        "connection.html",
        _page_context(request, active="scanner"),
    )


@app.get("/domains/", response_class=HTMLResponse)
async def domains_page(request: Request):
    if not require_auth(request):
        return _redirect_to_login()

    with db() as con:
        domains = con.execute(
            """
            SELECT *
            FROM domains
            ORDER BY category, label COLLATE NOCASE
            """
        ).fetchall()

    return templates.TemplateResponse(
        "domains.html",
        _page_context(request, domains=domains, active="domains"),
    )


@app.get("/history/", response_class=HTMLResponse)
async def history_page(request: Request):
    if not require_auth(request):
        return _redirect_to_login()

    return templates.TemplateResponse(
        "history.html",
        _page_context(request, active="history"),
    )


@app.get("/settings/", response_class=HTMLResponse)
async def settings_page(request: Request):
    if not require_auth(request):
        return _redirect_to_login()

    return templates.TemplateResponse(
        "settings.html",
        _page_context(
            request,
            active="settings",
            telegram_configured=bool(get_setting("telegram_token")),
            telegram_owner_id=telegram_owner_id(),
            telegram_admin_ids=", ".join(sorted(telegram_admin_ids())),
        ),
    )


@app.get("/account/", response_class=HTMLResponse)
async def account_page(request: Request):
    if not require_auth(request):
        return _redirect_to_login()

    return templates.TemplateResponse(
        "account.html",
        _page_context(request, active="account"),
    )


@app.post("/api/scan")
async def scan(request: Request):
    body, error = await _authorized_json(request)
    if error:
        return error
    raw_target = str(body.get("connect_target", "")).strip()
    connect_target = None
    if raw_target:
        try:
            connect_target = str(ipaddress.ip_address(raw_target))
        except ValueError:
            return JSONResponse(
                {"error": "Custom ping target must be a valid IP address."},
                status_code=400,
            )
    return await run_scan(connect_target)


def _speed_request(url: str, method: str = "GET", data: bytes | None = None, timeout: float = 12.0):
    request = urllib.request.Request(
        url,
        method=method,
        data=data,
        headers={"User-Agent": "idontScanner-SpeedTest/2.1"},
    )
    return urllib.request.urlopen(request, timeout=timeout)


def _measure_speed_test():
    import statistics
    download_samples = []
    upload_samples = []
    latency_samples = []
    for _ in range(3):
        started = time.perf_counter()
        with _speed_request(
            "https://speed.cloudflare.com/__down?bytes=1000000",
            timeout=10,
        ) as response:
            response.read(128)
        latency_samples.append((time.perf_counter() - started) * 1000)
    for size in (2_000_000, 4_000_000, 8_000_000):
        started = time.perf_counter()
        received = 0
        with _speed_request(
            f"https://speed.cloudflare.com/__down?bytes={size}",
            timeout=20,
        ) as response:
            while True:
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                received += len(chunk)
        elapsed = max(0.001, time.perf_counter() - started)
        download_samples.append(received * 8 / elapsed / 1_000_000)
    payload = b"0" * 2_000_000
    for size in (1_000_000, 2_000_000):
        body = payload[:size]
        started = time.perf_counter()
        with _speed_request(
            "https://speed.cloudflare.com/__up",
            method="POST",
            data=body,
            timeout=20,
        ) as response:
            response.read(64)
        elapsed = max(0.001, time.perf_counter() - started)
        upload_samples.append(len(body) * 8 / elapsed / 1_000_000)
    average_latency = statistics.mean(latency_samples)
    jitter = (
        statistics.mean(
            abs(a - b)
            for a, b in zip(latency_samples, latency_samples[1:])
        )
        if len(latency_samples) > 1
        else 0.0
    )
    return {
        "download_mbps": round(statistics.mean(download_samples), 1),
        "upload_mbps": round(statistics.mean(upload_samples), 1),
        "latency_ms": round(average_latency, 1),
        "jitter_ms": round(jitter, 1),
        "samples": 3,
        "provider": "Cloudflare Speed Test endpoint",
    }


@app.post("/api/vps-speed-test")
async def vps_speed_test(request: Request):
    body, error = await _authorized_json(request)
    if error:
        return error
    started = time.perf_counter()
    try:
        result = await asyncio.to_thread(_measure_speed_test)
        result["duration_ms"] = round((time.perf_counter() - started) * 1000, 1)
        return result
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return JSONResponse({"error": f"Speed test failed: {str(exc)[:180]}"}, status_code=502)


@app.get("/api/history")
async def history(request: Request):
    if not require_auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    with db() as con:
        rows = con.execute(
            """
            SELECT id, started_at, duration_ms, total, ok, slow, failed, average_ms
            FROM scans
            ORDER BY id DESC
            LIMIT 20
            """
        ).fetchall()

    return [dict(row) for row in rows]


@app.get("/api/history/{scan_id}")
async def history_detail(request: Request, scan_id: int):
    if not require_auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    with db() as con:
        rows = con.execute(
            """
            SELECT r.*, d.domain, d.label, d.category
            FROM results AS r
            JOIN domains AS d ON d.id = r.domain_id
            WHERE r.scan_id = ?
            ORDER BY r.id
            """,
            (scan_id,),
        ).fetchall()

    return [dict(row) for row in rows]


@app.post("/api/domains")
async def add_domain(request: Request):
    body, error = await _authorized_json(request)
    if error:
        return error

    domain = valid_domain(str(body.get("domain", "")))
    label = str(body.get("label", domain or "Custom"))[:60].strip() or "Custom"
    category = str(body.get("category", "Custom"))[:30].strip() or "Custom"

    if not domain:
        return JSONResponse({"error": "invalid domain"}, status_code=400)

    try:
        with db() as con:
            con.execute(
                """
                INSERT INTO domains(
                    label, domain, category, enabled, is_default, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (label, domain, category, 1, 0, int(time.time())),
            )
    except sqlite3.IntegrityError:
        return JSONResponse(
            {"error": "domain already exists"},
            status_code=409,
        )

    return {"ok": True}


@app.post("/api/domains/{domain_id}/toggle")
async def toggle_domain(request: Request, domain_id: int):
    body, error = await _authorized_json(request)
    if error:
        return error

    with db() as con:
        con.execute(
            """
            UPDATE domains
            SET enabled = CASE enabled WHEN 1 THEN 0 ELSE 1 END
            WHERE id = ?
            """,
            (domain_id,),
        )

    return {"ok": True}


@app.delete("/api/domains/{domain_id}")
async def delete_domain(request: Request, domain_id: int):
    if not require_auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    if not hmac.compare_digest(
        csrf(request),
        request.headers.get("x-csrf-token", ""),
    ):
        return JSONResponse({"error": "csrf"}, status_code=403)

    with db() as con:
        row = con.execute(
            "SELECT is_default FROM domains WHERE id = ?",
            (domain_id,),
        ).fetchone()

        if not row:
            return JSONResponse({"error": "not found"}, status_code=404)

        if row[0]:
            return JSONResponse(
                {"error": "default domain cannot be deleted; disable it instead"},
                status_code=400,
            )

        con.execute("DELETE FROM domains WHERE id = ?", (domain_id,))

    return {"ok": True}


@app.get("/api/sessions")
async def sessions_api(request: Request):
    if not require_auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    with db() as con:
        rows = con.execute(
            """
            SELECT id, ip, device, last_seen
            FROM sessions
            ORDER BY id DESC
            LIMIT 3
            """
        ).fetchall()

    return [dict(row) for row in rows]


@app.post("/api/account/password")
async def change_password(request: Request):
    body, error = await _authorized_json(request)
    if error:
        return error

    current = str(body.get("current", ""))
    new = str(body.get("new", ""))
    confirm = str(body.get("confirm", ""))
    stored = get_setting("password")

    if not verify_password(current, stored):
        return JSONResponse(
            {"error": "current password is incorrect"},
            status_code=400,
        )

    if len(new) < 8 or new != confirm:
        return JSONResponse(
            {"error": "password confirmation failed or password is too short"},
            status_code=400,
        )

    set_setting("password", hash_password(new))
    request.session.clear()

    return {"ok": True, "redirect": "/login/"}


@app.post("/api/account/username")
async def change_username(request: Request):
    body, error = await _authorized_json(request)
    if error:
        return error

    username = str(body.get("username", "")).strip()
    if not 3 <= len(username) <= 32:
        return JSONResponse({"error": "invalid username"}, status_code=400)

    set_setting("username", username)
    return {"ok": True}


@app.post("/api/scheduler")
async def scheduler_update(request: Request):
    body, error = await _authorized_json(request)
    if error:
        return error

    enabled = bool(body.get("enabled"))
    interval = int(body.get("interval_minutes", 60))

    if interval < 30 or interval > 1440 or interval % 30 != 0:
        return JSONResponse(
            {"error": "interval must be 30–1440 minutes in 30-minute steps"},
            status_code=400,
        )

    mode = str(body.get("notify_mode", "all"))
    if mode not in {"all", "changes"}:
        mode = "all"

    next_run = int(time.time()) + interval * 60 if enabled else None

    with db() as con:
        con.execute(
            """
            UPDATE scheduler
            SET enabled = ?, interval_minutes = ?, next_run = ?, notify_mode = ?
            WHERE id = 1
            """,
            (1 if enabled else 0, interval, next_run, mode),
        )

    return {"ok": True}


@app.get("/api/telegram/status")
async def telegram_status(request: Request):
    if not require_auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    token = get_setting("telegram_token")
    owner_id = telegram_owner_id()
    admin_ids = sorted(telegram_admin_ids())

    if not token:
        return {
            "configured": False,
            "authorized": False,
            "owner_id": owner_id,
            "admin_ids": admin_ids,
        }

    try:
        result = await asyncio.to_thread(telegram_request, token, "getMe", {})
        if not result.get("ok"):
            return {
                "configured": False,
                "authorized": bool(owner_id or admin_ids),
                "owner_id": owner_id,
                "admin_ids": admin_ids,
            }

        bot = result.get("result", {})
        username = bot.get("username", "")
        return {
            "configured": True,
            "authorized": bool(owner_id or admin_ids),
            "owner_id": owner_id,
            "admin_ids": admin_ids,
            "username": username,
            "name": bot.get("first_name", ""),
            "url": f"https://t.me/{username}" if username else "",
        }
    except Exception:
        return {
            "configured": False,
            "authorized": bool(owner_id or admin_ids),
            "owner_id": owner_id,
            "admin_ids": admin_ids,
        }


@app.post("/api/telegram")
async def telegram_settings(request: Request):
    body, error = await _authorized_json(request)
    if error:
        return error

    token = str(body.get("token", "")).strip()
    owner_id = str(body.get("owner_id", "")).strip()
    admin_ids_raw = str(body.get("admin_ids", "")).strip()
    admin_ids = [
        item.strip()
        for item in admin_ids_raw.replace("\n", ",").split(",")
        if item.strip()
    ]

    if owner_id and not owner_id.lstrip("-").isdigit():
        return JSONResponse(
            {"error": "Owner Telegram ID must be numeric."},
            status_code=400,
        )

    if any(not item.lstrip("-").isdigit() for item in admin_ids):
        return JSONResponse(
            {"error": "Admin Telegram IDs must be numeric and comma-separated."},
            status_code=400,
        )

    admin_ids = [item for item in admin_ids if item != owner_id]

    if token:
        try:
            result = await asyncio.to_thread(
                telegram_request,
                token,
                "getMe",
                {},
            )
            if not result.get("ok"):
                raise ValueError("Telegram rejected the token")

            commands = {
                "commands": [
                    {
                        "command": "start",
                        "description": "Open idontScanner menu",
                    },
                    {
                        "command": "menu",
                        "description": "Show control menu",
                    },
                    {
                        "command": "scan",
                        "description": "Run a scan",
                    },
                    {
                        "command": "status",
                        "description": "Show scanner status",
                    },
                ]
            }
            await asyncio.to_thread(
                telegram_request,
                token,
                "setMyCommands",
                commands,
            )
        except Exception as exc:
            return JSONResponse(
                {"error": f"Telegram token check failed: {exc}"},
                status_code=400,
            )

        set_setting("telegram_token", token)
        username = result.get("result", {}).get("username", "")
        set_setting("telegram_owner_id", owner_id)
        set_setting("telegram_admin_ids", ",".join(admin_ids))
        set_setting("telegram_chat_id", owner_id)

        return {
            "ok": True,
            "configured": True,
            "username": username,
            "name": result.get("result", {}).get("first_name", ""),
            "url": f"https://t.me/{username}" if username else "",
            "authorized": bool(owner_id or admin_ids),
            "owner_id": owner_id,
            "admin_ids": admin_ids,
        }

    for key in (
        "telegram_token",
        "telegram_chat_id",
        "telegram_owner_id",
        "telegram_admin_ids",
    ):
        set_setting(key, "")

    return {
        "ok": True,
        "configured": False,
        "authorized": False,
        "owner_id": "",
        "admin_ids": [],
    }


@app.post("/api/sni-check")
async def sni_check(request: Request):
    body, error = await _authorized_json(request)
    if error:
        return error

    target = valid_domain(str(body.get("target", "")))
    test_sni = valid_domain(str(body.get("sni", "")))

    if not target or not test_sni:
        return JSONResponse(
            {"error": "valid target and SNI domains are required"},
            status_code=400,
        )

    try:
        target_ip = await asyncio.to_thread(socket.gethostbyname, target)
        context = ssl.create_default_context()
        context.set_alpn_protocols(["h2", "http/1.1"])
        started = time.perf_counter()

        _, writer = await asyncio.wait_for(
            asyncio.open_connection(
                target_ip,
                443,
                ssl=context,
                server_hostname=test_sni,
            ),
            timeout=TIMEOUT,
        )

        ssl_obj = writer.get_extra_info("ssl_object")
        details = peer_certificate_details(ssl_obj)
        writer.close()

        try:
            await writer.wait_closed()
        except Exception:
            pass

        return {
            "target": target,
            "target_ip": target_ip,
            "test_sni": test_sni,
            "status": "ok",
            "latency_ms": round(
                (time.perf_counter() - started) * 1000,
                1,
            ),
            "tls_version": ssl_obj.version() if ssl_obj else None,
            "alpn": ssl_obj.selected_alpn_protocol() if ssl_obj else None,
            "cipher": (
                ssl_obj.cipher()[0]
                if ssl_obj and ssl_obj.cipher()
                else None
            ),
            **details,
        }
    except Exception as exc:
        return {
            "target": target,
            "test_sni": test_sni,
            "status": "failed",
            "error": str(exc)[:220],
        }


@app.post("/api/connection-check")
async def connection_check(request: Request):
    body, error = await _authorized_json(request)
    if error:
        return error

    raw_config = str(body.get("config", "")).strip()
    if len(raw_config) > 4096:
        return JSONResponse(
            {"error": "configuration is too large"},
            status_code=400,
        )

    try:
        config = parse_config(raw_config)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    result = await diagnose_config(config)
    result["service_tests"] = await probe_services()
    return result


@app.post("/api/cdn-check")
async def cdn_check(request: Request):
    body, error = await _authorized_json(request)
    if error:
        return error

    domain = valid_domain(str(body.get("domain", "")))
    if not domain:
        return JSONResponse({"error": "valid domain required"}, status_code=400)

    try:
        cname = await asyncio.to_thread(socket.getfqdn, domain)
        probe = await tls_probe(domain)
        return {
            "domain": domain,
            "observed_hostname": cname,
            "provider_hint": (
                "Akamai/CDN"
                if "akamai" in cname.lower() or "akamai" in domain.lower()
                else "Not identified as Akamai"
            ),
            **probe,
        }
    except Exception as exc:
        return {
            "domain": domain,
            "status": "failed",
            "error": str(exc)[:220],
        }
