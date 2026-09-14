"""FastAPI application and HTTP routes for idontScanner."""

from __future__ import annotations

import asyncio
import hmac
import ipaddress
import json
import os
import shutil
import socket
import statistics
import sqlite3
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app.auth import hash_password, verify_password
from app.config import (
    APP_VERSION,
    BASE,
    BASE_PATH,
    SECRET,
    TIMEOUT,
    UPDATE_VERSION_URL,
    TARGET_BENCHMARK_COUNT,
    TARGET_CUSTOM_LIMIT,
    TARGET_BENCHMARK_SECONDS,
    TARGET_PROBE_CONCURRENCY,
    TARGET_CATALOG_PATH,
)
from app.check_host import (
    IRAN_NODES,
    fetch_result as fetch_check_host_result,
    local_info as check_host_info,
    normalize_results as normalize_check_host_results,
    start_check as start_check_host,
)
from app.connection import (
    diagnose_config,
    parse_config,
    probe_services,
)
from app.network import measure_network_quality, measure_target_path, resolve_public_ipv4
from app.database import (
    db,
    get_setting,
    init_db,
    set_setting,
    telegram_admin_ids,
    telegram_configured_ids,
    telegram_owner_id,
)
from app.scanner import certificate_sni_candidates, peer_certificate_details, probe_sni, run_scan, tls_probe
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
        "app_version": APP_VERSION,
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
            "app_version": APP_VERSION,
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


@app.get("/api/update-check")
async def update_check(request: Request):
    if not require_auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    def fetch_remote_version():
        request_obj = urllib.request.Request(
            UPDATE_VERSION_URL,
            headers={"User-Agent": "idontScanner-UpdateCheck/3.0"},
        )
        with urllib.request.urlopen(request_obj, timeout=4) as response:
            return response.read(128).decode("utf-8").strip()

    try:
        latest = await asyncio.to_thread(fetch_remote_version)
    except Exception:
        return {"current_version": APP_VERSION, "latest_version": None, "update_available": False}

    version_pattern = r"^v\d+\.\d+\.\d+$"
    if not __import__("re").fullmatch(version_pattern, latest):
        return {"current_version": APP_VERSION, "latest_version": None, "update_available": False}

    def newer(remote: str, local: str) -> bool:
        return tuple(map(int, remote[1:].split("."))) > tuple(map(int, local[1:].split(".")))

    return {
        "current_version": APP_VERSION,
        "latest_version": latest,
        "update_available": newer(latest, APP_VERSION),
    }


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


@app.get("/check-host/", response_class=HTMLResponse)
async def check_host_page(request: Request):
    if not require_auth(request):
        return _redirect_to_login()

    return templates.TemplateResponse(
        "check_host.html",
        _page_context(request, active="check_host"),
    )


@app.get("/speed-test/", response_class=HTMLResponse)
async def speed_test_page(request: Request):
    if not require_auth(request):
        return _redirect_to_login()
    return templates.TemplateResponse(
        "speed_test.html",
        _page_context(request, active="speed_test"),
    )


async def _ensure_target_catalog_runtime():
    """Read the prepared benchmark catalog without blocking normal requests.

    Installation/update prepare the catalog using multiple public sources.
    Runtime intentionally does not perform long external downloads: a missing
    catalog should surface as a clear UI state instead of making Find Target
    hang on a ranking-provider timeout.
    """
    catalog_path = Path(os.getenv("IDONTSCANNER_TARGET_CATALOG", str(TARGET_CATALOG_PATH)))
    if not catalog_path.exists():
        return [], "unavailable"
    try:
        current = [
            x.strip().lower().rstrip(".")
            for x in catalog_path.read_text(encoding="utf-8", errors="ignore").splitlines()
            if valid_domain(x.strip())
        ]
        if len(current) >= TARGET_BENCHMARK_COUNT:
            return current[:TARGET_BENCHMARK_COUNT], "local"
        return current, "incomplete"
    except Exception:
        return [], "unavailable"

@app.get("/api/benchmark-targets")
async def benchmark_targets_catalog(request: Request):
    if not require_auth(request):
        return JSONResponse({"error": "Authentication required."}, status_code=401)
    base, source = await _ensure_target_catalog_runtime()
    with db() as con:
        rows = con.execute("SELECT id, domain FROM benchmark_custom_targets ORDER BY id ASC LIMIT ?", (TARGET_CUSTOM_LIMIT,)).fetchall()
    custom=[{"id":int(r[0]),"domain":r[1]} for r in rows]
    return {"base": [{"domain":d,"endpoint":f"{d}:443"} for d in base], "base_count":len(base), "required":TARGET_BENCHMARK_COUNT, "source":source, "custom":custom, "custom_count":len(custom)}

@app.get("/targets/", response_class=HTMLResponse)
async def targets_page(request: Request):
    if not require_auth(request):
        return _redirect_to_login()
    with db() as con:
        custom = con.execute("SELECT id, domain FROM benchmark_custom_targets ORDER BY id ASC LIMIT ?", (TARGET_CUSTOM_LIMIT,)).fetchall()
    return templates.TemplateResponse("targets.html", _page_context(request, active="scanner", target_count=0, base_targets=[], custom_targets=custom))


def _target_catalog():
    catalog_path = Path(os.getenv("IDONTSCANNER_TARGET_CATALOG", str(TARGET_CATALOG_PATH)))
    if not catalog_path.exists():
        return []
    return [x.strip().lower().rstrip(".") for x in catalog_path.read_text(encoding="utf-8", errors="ignore").splitlines() if valid_domain(x.strip())][:TARGET_BENCHMARK_COUNT]


async def _target_probe(domain: str):
    result = await tls_probe(domain)
    result = dict(result)
    result["domain"] = domain
    result["endpoint"] = f"{domain}:443"
    result["host_ok"] = result.get("status") == "ok" and result.get("tcp_ms") is not None
    result["sni_ok"] = result.get("status") == "ok" and bool(result.get("tls_version"))
    return result


def _benchmark_score(item, ranking):
    if item.get("status") != "ok":
        return -1.0
    latency = float(item.get("latency_ms") or 9999)
    tls = item.get("tls_version") or ""
    alpn = item.get("alpn") or ""
    host = 1 if item.get("host_ok") else 0
    sni = 1 if item.get("sni_ok") else 0
    tls_quality = 1.0 if tls == "TLSv1.3" else 0.85 if tls == "TLSv1.2" else 0.35
    alpn_quality = 1.0 if alpn == "h2" else 0.7 if alpn == "http/1.1" else 0.3
    latency_quality = max(0.0, min(1.0, 1.0 - latency / 500.0))
    if ranking == "latency":
        return latency_quality * 100
    if ranking == "tls":
        return (tls_quality * .55 + alpn_quality * .2 + latency_quality * .15 + host * .05 + sni * .05) * 100
    if ranking == "stability":
        return (host * .3 + sni * .3 + tls_quality * .2 + alpn_quality * .1 + latency_quality * .1) * 100
    return (latency_quality * .35 + tls_quality * .25 + alpn_quality * .15 + host * .125 + sni * .125) * 100


async def _best_effort_isp(ip: str):
    if not ip:
        return None
    def fetch():
        try:
            req=urllib.request.Request(f"https://ipwho.is/{ip}", headers={"User-Agent":"idontScanner/3.5.8"})
            with urllib.request.urlopen(req, timeout=1.5) as r:
                data=json.loads(r.read(12000).decode("utf-8","replace"))
            conn=data.get("connection") or {}
            return conn.get("isp") or conn.get("org") or conn.get("asn")
        except Exception:
            return None
    return await asyncio.to_thread(fetch)



async def _iran_target_diagnostics(domain: str) -> dict:
    """Run bounded Iran-side ICMP and HTTP diagnostics in parallel.

    Check-Host exposes node-side reachability and HTTP response timing. It does
    not expose arbitrary-target upload/download throughput, so those values are
    never inferred from response time.
    """
    async def run_one(check_type: str, target: str):
        try:
            started = await start_check_host(check_type, target, nodes=list(IRAN_NODES))
            deadline = time.perf_counter() + 6.0
            raw = {}
            while time.perf_counter() < deadline:
                raw = await fetch_check_host_result(started["request_id"])
                normalized = normalize_check_host_results(check_type, raw, started["nodes"])
                if normalized.get("complete"):
                    break
                await asyncio.sleep(0.3)
            return normalize_check_host_results(check_type, raw, started["nodes"])
        except Exception as exc:
            return {"results": [], "complete": False, "error": str(exc)[:180]}

    ping, http = await asyncio.gather(
        run_one("ping", f"{domain}:443"),
        run_one("http", f"https://{domain}/"),
    )
    ping_results = ping.get("results", [])
    values = [
        x.get("avg_ms") for x in ping_results
        if x.get("status") == "online" and x.get("avg_ms") is not None
    ]
    loss_values = [x.get("loss_percent") for x in ping_results if x.get("loss_percent") is not None]
    http_results = http.get("results", [])
    http_values = [x.get("latency_ms") for x in http_results if x.get("status") == "online" and x.get("latency_ms") is not None]
    return {
        "ping": ping_results,
        "http": http_results,
        "average_ping_ms": round(statistics.mean(values), 1) if values else None,
        "jitter_ms": round(statistics.pstdev(values), 1) if len(values) > 1 else 0.0 if values else None,
        "average_loss_percent": round(statistics.mean(loss_values), 1) if loss_values else None,
        "http_average_ms": round(statistics.mean(http_values), 1) if http_values else None,
        "online_nodes": len(values),
        "total_nodes": len(IRAN_NODES),
        "errors": [x for x in (ping.get("error"), http.get("error")) if x],
    }


def _deep_quality_score(vps: dict, iran: dict, target: dict, sni: dict | None) -> float | None:
    """Conservative quality score from measurements that were actually observed."""
    components: list[tuple[float, float]] = []

    latency = vps.get("tcp_latency_ms")
    if latency is not None:
        components.append((max(0.0, min(1.0, 1.0 - float(latency) / 300.0)), 0.22))
    jitter = vps.get("jitter_ms")
    if jitter is not None:
        components.append((max(0.0, min(1.0, 1.0 - float(jitter) / 100.0)), 0.14))
    loss = vps.get("tcp_loss_percent")
    if loss is not None:
        components.append((max(0.0, 1.0 - float(loss) / 100.0), 0.12))
    download = vps.get("download_mbps")
    if download is not None:
        # Log-like normalization avoids making very high bandwidth dominate the score.
        import math
        components.append((max(0.0, min(1.0, math.log1p(float(download)) / math.log1p(500.0))), 0.18))

    iran_latency = iran.get("average_ping_ms")
    if iran_latency is not None:
        components.append((max(0.0, min(1.0, 1.0 - float(iran_latency) / 400.0)), 0.14))
    iran_loss = iran.get("average_loss_percent")
    if iran_loss is not None:
        components.append((max(0.0, 1.0 - float(iran_loss) / 100.0), 0.08))

    tls = target.get("tls_version")
    alpn = target.get("alpn")
    if tls:
        components.append((1.0 if tls == "TLSv1.3" else 0.85 if tls == "TLSv1.2" else 0.45, 0.04))
    if alpn:
        components.append((1.0 if alpn == "h2" else 0.75 if alpn == "http/1.1" else 0.4, 0.04))
    if sni:
        components.append((1.0 if sni.get("sni_verified") else 0.0, 0.04))

    if not components:
        return None
    total_weight = sum(weight for _, weight in components)
    return round(sum(value * weight for value, weight in components) / total_weight * 100.0, 1)


@app.post("/api/target-details")
async def target_details(request: Request):
    body, error = await _authorized_json(request)
    if error:
        return error
    raw = str(body.get("domain", "")).strip().lower().removesuffix(":443")
    domain = valid_domain(raw)
    if not domain:
        return JSONResponse({"error": "Invalid target domain."}, status_code=400)
    requested_sni = str(body.get("sni", "")).strip().lower().rstrip(".")
    if requested_sni and not valid_domain(requested_sni):
        requested_sni = ""

    try:
        await asyncio.to_thread(resolve_public_ipv4, domain)
    except Exception as exc:
        return JSONResponse({"error": f"Target is not a public IPv4 destination: {str(exc)[:160]}"}, status_code=400)

    started = time.perf_counter()
    try:
        async with asyncio.timeout(16.0):
            probe = await asyncio.wait_for(tls_probe(domain), timeout=4.5)
            if probe.get("status") != "ok" or not probe.get("ip"):
                return JSONResponse({"error": probe.get("error") or "Target is not TLS reachable."}, status_code=502)

            best_sni = requested_sni if requested_sni else domain
            sni_probe = None
            candidates = certificate_sni_candidates(probe.get("cert_san", ""), domain)
            if requested_sni and requested_sni != domain:
                candidates = [requested_sni] + [x for x in candidates if x != requested_sni]
            else:
                candidates = candidates[:4]
            if candidates:
                completed = await asyncio.gather(*(probe_sni(probe["ip"], c) for c in candidates), return_exceptions=True)
                good = [x for x in completed if isinstance(x, dict) and x.get("status") == "ok" and x.get("sni_verified")]
                if good:
                    sni_probe = min(good, key=lambda x: float(x.get("sni_latency_ms") or 99999))
                    best_sni = sni_probe.get("sni") or best_sni

            vps_task = asyncio.to_thread(measure_target_path, domain, best_sni)
            iran_task = _iran_target_diagnostics(domain)
            vps, iran = await asyncio.gather(vps_task, iran_task, return_exceptions=True)
            if isinstance(vps, Exception):
                vps = {"error": str(vps)[:180], "download_mbps": None, "upload_mbps": None}
            if isinstance(iran, Exception):
                iran = {"ping": [], "http": [], "errors": [str(iran)[:180]]}
    except TimeoutError:
        return JSONResponse({"error": "Deep diagnostics timed out. Try the target again."}, status_code=504)

    deep_score = _deep_quality_score(vps, iran, probe, sni_probe)
    duration_ms = round((time.perf_counter() - started) * 1000, 1)
    return {
        "domain": domain,
        "endpoint": f"{domain}:443",
        "score": body.get("score"),
        "deep_score": deep_score,
        "isp": body.get("isp"),
        "target": probe,
        "best_sni": best_sni,
        "sni": sni_probe,
        "vps": vps,
        "iran": iran,
        "upload_note": "Upload to an arbitrary target is not reported unless that target exposes a documented, safe upload endpoint. The number is never fabricated.",
        "speed_reference": "Use the separate VPS Speed Test for VPS-to-internet upload/download; it is not presented as target throughput.",
        "duration_ms": duration_ms,
    }

@app.post("/api/target-benchmark")
async def target_benchmark(request: Request):
    body, error = await _authorized_json(request)
    if error:
        return error
    ranking = str(body.get("ranking", "balanced")).lower()
    if ranking not in {"balanced", "latency", "tls", "stability"}:
        ranking = "balanced"
    limit = max(1, min(30, int(body.get("limit", 15))))
    custom_input = body.get("targets")
    catalog = _target_catalog()
    if len(catalog) < TARGET_BENCHMARK_COUNT:
        return JSONResponse({"error": f"Target catalog is incomplete ({len(catalog)}/{TARGET_BENCHMARK_COUNT}). Run the target catalog sync first."}, status_code=503)
    with db() as con:
        rows = con.execute("SELECT domain FROM benchmark_custom_targets ORDER BY id ASC LIMIT ?", (TARGET_CUSTOM_LIMIT,)).fetchall()
    custom = [r[0] for r in rows]
    # Explicit editor input is limited to custom entries plus catalog entries; it cannot erase the base catalog.
    if isinstance(custom_input, list) and custom_input:
        requested=[]; seen=set(catalog)
        for raw in custom_input:
            d=valid_domain(str(raw).strip().lower().removesuffix(":443"))
            if d and d not in seen and len(requested)<TARGET_CUSTOM_LIMIT:
                requested.append(d); seen.add(d)
        if requested:
            with db() as con:
                for d in requested:
                    con.execute("INSERT OR IGNORE INTO benchmark_custom_targets(domain,created_at) VALUES (?,?)", (d,int(time.time())))
            custom = list(dict.fromkeys(custom + requested))[-TARGET_CUSTOM_LIMIT:]
    targets = list(dict.fromkeys(catalog + custom))
    started=time.perf_counter(); deadline=started + TARGET_BENCHMARK_SECONDS
    sem=asyncio.Semaphore(TARGET_PROBE_CONCURRENCY)
    results=[]
    async def worker(d):
        if time.perf_counter() >= deadline: return None
        async with sem:
            if time.perf_counter() >= deadline: return None
            try:
                return await asyncio.wait_for(_target_probe(d), timeout=min(3.5, max(.25, deadline-time.perf_counter())))
            except Exception:
                return {"domain":d,"endpoint":f"{d}:443","status":"timeout","host_ok":False,"sni_ok":False,"latency_ms":None}
    tasks=[asyncio.create_task(worker(d)) for d in targets]
    try:
        done,pending=await asyncio.wait(tasks, timeout=TARGET_BENCHMARK_SECONDS)
        for task in done:
            item=task.result()
            if item: results.append(item)
        for task in pending: task.cancel()
    except Exception:
        for task in tasks: task.cancel()
    for item in results:
        item["score"] = round(_benchmark_score(item, ranking), 1)
    # First-pass ranking identifies a bounded candidate set. Alternate SNI
    # checks are derived only from certificate SANs returned by the target,
    # which keeps the 30-second benchmark bounded even with 3,000 targets.
    results.sort(key=lambda x:(-x["score"], float(x.get("latency_ms") or 99999)))
    candidate_pool = results[:min(80, len(results))]
    sni_jobs = []
    for item in candidate_pool:
        if time.perf_counter() >= deadline:
            break
        ip = item.get("ip")
        if not ip:
            continue
        candidates = certificate_sni_candidates(item.get("cert_san", ""), item.get("domain", ""))
        for candidate in candidates:
            sni_jobs.append((item, ip, candidate))
    sni_sem = asyncio.Semaphore(24)

    async def sni_worker(item, ip, candidate):
        if time.perf_counter() >= deadline:
            return None
        async with sni_sem:
            if time.perf_counter() >= deadline:
                return None
            remaining = max(0.25, deadline - time.perf_counter())
            try:
                return item, await asyncio.wait_for(probe_sni(ip, candidate), timeout=min(2.25, remaining))
            except Exception as exc:
                return item, {"status":"failed","sni":candidate,"sni_verified":False,"sni_latency_ms":None,"error":str(exc)[:180]}

    if sni_jobs:
        tasks=[asyncio.create_task(sni_worker(*job)) for job in sni_jobs]
        done, pending = await asyncio.wait(tasks, timeout=max(0.1, deadline-time.perf_counter()))
        for task in done:
            try:
                item, probe = task.result()
            except Exception:
                continue
            if not probe or probe.get("status") != "ok" or not probe.get("sni_verified"):
                continue
            current = item.get("best_sni")
            if current is None or float(probe.get("sni_latency_ms") or 99999) < float(current.get("sni_latency_ms") or 99999):
                item["best_sni"] = probe
        for task in pending:
            task.cancel()

    # A successful alternate SNI is a quality signal, not a guarantee of
    # compatibility with every client/network. Fold it into the final score.
    for item in results:
        best_sni = item.get("best_sni")
        sni_bonus = 0.0
        if best_sni:
            sni_latency = float(best_sni.get("sni_latency_ms") or 9999)
            sni_bonus = max(0.0, min(1.0, 1.0 - sni_latency / 500.0)) * 12.0
            item["sni"] = best_sni.get("sni")
            item["sni_ok"] = True
            item["sni_latency_ms"] = best_sni.get("sni_latency_ms")
            item["sni_tls_version"] = best_sni.get("sni_tls_version")
            item["sni_alpn"] = best_sni.get("sni_alpn")
            item["sni_source"] = "certificate SAN"
        else:
            item["sni"] = item.get("domain")
            item["sni_ok"] = item.get("status") == "ok"
            item["sni_latency_ms"] = item.get("tls_ms")
            item["sni_tls_version"] = item.get("tls_version")
            item["sni_alpn"] = item.get("alpn")
            item["sni_source"] = "direct host"
        item["score"] = round(min(100.0, float(item.get("score") or 0) + sni_bonus), 1)

    results.sort(key=lambda x:(-x["score"], float(x.get("latency_ms") or 99999)))
    top=results[:limit]
    # ISP enrichment is best-effort and is strictly bounded by the same
    # benchmark deadline; it can never extend Find Target past 30 seconds.
    remaining = deadline - time.perf_counter()
    if top and remaining > 0.15:
        async def isp_worker(item):
            try:
                value = await asyncio.wait_for(
                    _best_effort_isp(item.get("ip")),
                    timeout=min(0.8, max(0.15, deadline - time.perf_counter())),
                )
                return item, value
            except Exception:
                return item, None
        isp_tasks=[asyncio.create_task(isp_worker(item)) for item in top]
        done, pending = await asyncio.wait(isp_tasks, timeout=max(0.05, deadline-time.perf_counter()))
        for task in done:
            try:
                item, isp = task.result()
            except Exception:
                continue
            item["isp"] = isp
        for task in pending:
            task.cancel()
    duration_ms=round(min(TARGET_BENCHMARK_SECONDS, time.perf_counter()-started)*1000,1)
    return {"total":len(results),"tested":len(results),"ok":sum(x.get("status")=="ok" for x in results),"duration_ms":duration_ms,"deadline_seconds":TARGET_BENCHMARK_SECONDS,"results":top,"catalog_size":len(catalog),"custom_size":len(custom)}

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


def _measure_speed_test():
    return measure_network_quality()


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


@app.delete("/api/sessions/{session_id}")
async def revoke_session(request: Request, session_id: int):
    if not require_auth(request): return JSONResponse({"error":"unauthorized"}, status_code=401)
    if not hmac.compare_digest(csrf(request), request.headers.get("x-csrf-token", "")):
        return JSONResponse({"error":"csrf"}, status_code=403)
    with db() as con:
        con.execute("DELETE FROM sessions WHERE id=?", (session_id,))
    return {"ok": True}

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
    try:
        result["connection_quality"] = await asyncio.to_thread(measure_network_quality)
    except Exception as exc:
        result["connection_quality"] = {
            "status": "unavailable",
            "error": str(exc)[:180],
        }
    return result


@app.post("/api/check-host/start")
async def check_host_start(request: Request):
    body, error = await _authorized_json(request)
    if error:
        return error

    check_type = str(body.get("type", "ping")).strip().lower()
    target = str(body.get("target", "")).strip()
    node_group = str(body.get("node_group", "global")).strip().lower()
    nodes = None
    if node_group == "iran":
        nodes = [
            "ir1.node.check-host.net",
            "ir2.node.check-host.net",
            "ir3.node.check-host.net",
            "ir4.node.check-host.net",
            "ir5.node.check-host.net",
            "ir7.node.check-host.net",
        ]
    try:
        return await start_check_host(check_type, target, nodes=nodes)
    except (ValueError, RuntimeError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        return JSONResponse({"error": f"Check-Host request failed: {str(exc)[:160]}"}, status_code=502)


@app.get("/api/check-host/result/{request_id}")
async def check_host_result(request: Request, request_id: str):
    if not require_auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    try:
        raw = await fetch_check_host_result(request_id)
        nodes = request.query_params.get("nodes", "")
        if not nodes:
            return JSONResponse({"error": "node metadata is required"}, status_code=400)
        node_map = json.loads(nodes)
        if not isinstance(node_map, dict):
            raise ValueError("invalid node metadata")
        check_type = request.query_params.get("type", "ping")
        return normalize_check_host_results(check_type, raw, node_map)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        return JSONResponse({"error": f"Unable to read Check-Host result: {str(exc)[:160]}"}, status_code=502)


@app.post("/api/check-host/info")
async def check_host_info_route(request: Request):
    body, error = await _authorized_json(request)
    if error:
        return error

    try:
        return await asyncio.to_thread(check_host_info, str(body.get("target", "")))
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        return JSONResponse({"error": f"Info lookup failed: {str(exc)[:160]}"}, status_code=502)


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
