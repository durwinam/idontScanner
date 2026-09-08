import asyncio
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import socket
import sqlite3
import ssl
import time
from urllib.parse import urlparse
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware


BASE = Path(__file__).resolve().parent.parent
DB_PATH = Path(
    os.getenv(
        "IDONTSCANNER_DB_PATH",
        str(BASE / "data" / "idontscanner.db"),
    )
)
BASE_PATH = ""
TIMEOUT = float(os.getenv("IDONTSCANNER_TIMEOUT", "4.0"))
SECRET = os.getenv("IDONTSCANNER_SECRET", "")

if len(SECRET) < 32:
    SECRET = secrets.token_urlsafe(48)


DEFAULT_DOMAINS = [
    ("Cloudflare", "cloudflare.com"),
    ("Google", "google.com"),
    ("Bing", "bing.com"),
    ("Yahoo", "yahoo.com"),
    ("Apple", "apple.com"),
    ("App Store", "apps.apple.com"),
    ("iCloud", "icloud.com"),
    ("Google Play", "play.google.com"),
    ("GitHub", "github.com"),
    ("GitLab", "gitlab.com"),
    ("Microsoft", "microsoft.com"),
    ("Microsoft Live", "live.com"),
    ("Office", "office.com"),
    ("Azure", "azure.com"),
    ("Amazon", "amazon.com"),
    ("Netflix", "netflix.com"),
    ("Spotify", "spotify.com"),
    ("Discord", "discord.com"),
    ("Telegram", "telegram.org"),
    ("WhatsApp", "whatsapp.com"),
    ("Reddit", "reddit.com"),
    ("Wikipedia", "wikipedia.org"),
    ("Archive", "archive.org"),
    ("Fastly", "fastly.com"),
    ("Akamai", "akamai.com"),
    ("Google APIs", "googleapis.com"),
    ("Gstatic", "gstatic.com"),
    ("Googleusercontent", "googleusercontent.com"),
    ("Aparat", "aparat.com"),
    ("Digikala", "digikala.com"),
    ("Divar", "divar.ir"),
    ("Snapp", "snapp.ir"),
    ("Irancell", "irancell.ir"),
    ("MCI", "mci.ir"),
]


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


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)

    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=()"
    )

    return response


def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    with db() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS domains (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                label TEXT NOT NULL,
                domain TEXT UNIQUE NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                is_default INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS scans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at INTEGER NOT NULL,
                duration_ms REAL NOT NULL,
                total INTEGER NOT NULL,
                ok INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_id INTEGER NOT NULL,
                domain_id INTEGER NOT NULL,
                status TEXT NOT NULL,
                latency_ms REAL,
                tls_version TEXT,
                cert_subject TEXT,
                error TEXT,
                FOREIGN KEY(scan_id) REFERENCES scans(id),
                FOREIGN KEY(domain_id) REFERENCES domains(id)
            );
            """
        )

        count = con.execute("SELECT COUNT(*) FROM domains").fetchone()[0]

        if count == 0:
            now = int(time.time())
            con.executemany(
                """
                INSERT OR IGNORE INTO domains(
                    label,
                    domain,
                    enabled,
                    is_default,
                    created_at
                )
                VALUES(?,?,?,?,?)
                """,
                [
                    (label, domain, 1, 1, now)
                    for label, domain in DEFAULT_DOMAINS
                ],
            )


def _scrypt(password: str, salt: bytes):
    # Prefer strong parameters; gracefully fall back on small-RAM VPS/OpenSSL limits.
    for n, r, p in (
        (16384, 8, 1),
        (8192, 8, 1),
        (4096, 8, 1),
    ):
        try:
            return n, hashlib.scrypt(
                password.encode("utf-8"),
                salt=salt,
                n=n,
                r=r,
                p=p,
                dklen=64,
            )
        except ValueError as exc:
            if "memory" not in str(exc).lower():
                raise

    raise RuntimeError("Unable to allocate memory for password hashing")


def password_hash(password: str, salt: bytes | None = None):
    salt = salt or secrets.token_bytes(16)
    n, digest = _scrypt(password, salt)

    return f"scrypt${n}${salt.hex()}${digest.hex()}"


def password_verify(password: str, stored: str):
    try:
        if stored.startswith("scrypt$"):
            _, n_s, salt_hex, digest_hex = stored.split("$", 3)
            n = int(n_s)
            salt = bytes.fromhex(salt_hex)

            calc = hashlib.scrypt(
                password.encode("utf-8"),
                salt=salt,
                n=n,
                r=8,
                p=1,
                dklen=64,
            )

            return hmac.compare_digest(calc.hex(), digest_hex)

        # Backward compatibility with the previous salt:digest format.
        salt_hex, digest_hex = stored.split(":", 1)
        salt = bytes.fromhex(salt_hex)
        _, calc = _scrypt(password, salt)

        return hmac.compare_digest(calc.hex(), digest_hex)
    except Exception:
        return False


def csrf(request: Request):
    token = request.session.get("csrf")

    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf"] = token

    return token


def require_auth(request: Request):
    return bool(request.session.get("auth"))


def server_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("1.1.1.1", 53))
        ip = s.getsockname()[0]
        s.close()

        return ip
    except Exception:
        return socket.gethostbyname(socket.gethostname())


def valid_domain(value: str):
    value = value.strip().lower().rstrip(".")

    if (
        not value
        or len(value) > 253
        or "://" in value
        or "/" in value
        or "@" in value
    ):
        return None

    try:
        ipaddress.ip_address(value)
        return None
    except ValueError:
        pass

    labels = value.split(".")

    invalid_labels = any(
        not label
        or len(label) > 63
        or label[0] == "-"
        or label[-1] == "-"
        or any(
            char not in "abcdefghijklmnopqrstuvwxyz0123456789-"
            for char in label
        )
        for label in labels
    )

    if len(labels) < 2 or invalid_labels:
        return None

    return value


async def tls_probe(domain: str):
    start = time.perf_counter()
    writer = None

    try:
        ctx = ssl.create_default_context()

        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(
                domain,
                443,
                ssl=ctx,
                server_hostname=domain,
            ),
            timeout=TIMEOUT,
        )

        latency = (time.perf_counter() - start) * 1000
        ssl_obj = writer.get_extra_info("ssl_object")
        cert = ssl_obj.getpeercert() if ssl_obj else {}

        subject = ""

        if cert:
            subject = ", ".join(
                "=".join(item)
                for part in cert.get("subject", [])
                for item in part
            )

        tls_version = ssl_obj.version() if ssl_obj else None

        return {
            "status": "ok",
            "latency_ms": round(latency, 1),
            "tls_version": tls_version,
            "cert_subject": subject,
            "error": None,
        }

    except asyncio.TimeoutError:
        return {
            "status": "timeout",
            "latency_ms": None,
            "tls_version": None,
            "cert_subject": "",
            "error": "Connection timed out",
        }

    except ssl.SSLError as e:
        return {
            "status": "tls_error",
            "latency_ms": None,
            "tls_version": None,
            "cert_subject": "",
            "error": str(e)[:180],
        }

    except Exception as e:
        return {
            "status": "failed",
            "latency_ms": None,
            "tls_version": None,
            "cert_subject": "",
            "error": str(e)[:180],
        }

    finally:
        if writer:
            writer.close()

            try:
                await writer.wait_closed()
            except Exception:
                pass


@app.on_event("startup")
async def startup():
    init_db()


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    if require_auth(request):
        return RedirectResponse("/dashboard/", status_code=303)

    return RedirectResponse("/login/", status_code=303)


@app.get(BASE_PATH + "/login/", response_class=HTMLResponse)
async def login_page(request: Request):
    with db() as con:
        row = con.execute(
            "SELECT value FROM settings WHERE key='password'"
        ).fetchone()

    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "base": BASE_PATH,
            "setup": row is None,
            "csrf": csrf(request),
            "error": None,
        },
    )


@app.post(BASE_PATH + "/login/")
async def login(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
    csrf_token: str = Form(""),
):
    if not hmac.compare_digest(csrf(request), csrf_token):
        return RedirectResponse(
            BASE_PATH + "/login/?error=csrf",
            status_code=303,
        )

    username = username.strip()

    with db() as con:
        urow = con.execute(
            "SELECT value FROM settings WHERE key='username'"
        ).fetchone()
        prow = con.execute(
            "SELECT value FROM settings WHERE key='password'"
        ).fetchone()

        if urow is None or prow is None:
            # Installer normally provisions credentials; this fallback supports manual first launch.
            if (
                not re.match(r"^[A-Za-z0-9_.-]{3,32}$", username)
                or len(password) < 12
            ):
                return RedirectResponse(
                    BASE_PATH + "/login/?error=weak",
                    status_code=303,
                )

            con.execute(
                "INSERT OR REPLACE INTO settings(key,value) VALUES('username',?)",
                (username,),
            )
            con.execute(
                "INSERT OR REPLACE INTO settings(key,value) VALUES('password',?)",
                (password_hash(password),),
            )

        elif not hmac.compare_digest(
            username,
            urow[0],
        ) or not password_verify(
            password,
            prow[0],
        ):
            return RedirectResponse(
                BASE_PATH + "/login/?error=invalid",
                status_code=303,
            )

    request.session.clear()
    request.session["auth"] = True
    request.session["username"] = username
    request.session["csrf"] = secrets.token_urlsafe(32)

    return RedirectResponse(
        BASE_PATH + "/dashboard/",
        status_code=303,
    )


@app.get(BASE_PATH + "/logout/")
async def logout(request: Request):
    request.session.clear()

    return RedirectResponse(
        BASE_PATH + "/login/",
        status_code=303,
    )


@app.get(BASE_PATH + "/dashboard/", response_class=HTMLResponse)
async def dashboard(request: Request):
    if not require_auth(request):
        return RedirectResponse(
            BASE_PATH + "/login/",
            status_code=303,
        )

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
        {
            "request": request,
            "base": BASE_PATH,
            "domains": domains,
            "latest": latest,
            "server_ip": server_ip(),
            "csrf": csrf(request),
        },
    )


@app.post(BASE_PATH + "/api/scan")
async def scan(request: Request):
    if not require_auth(request):
        return JSONResponse(
            {"error": "unauthorized"},
            status_code=401,
        )

    body = await request.json()

    if not hmac.compare_digest(
        csrf(request),
        str(body.get("csrf", "")),
    ):
        return JSONResponse(
            {"error": "csrf"},
            status_code=403,
        )

    with db() as con:
        domains = con.execute(
            "SELECT * FROM domains WHERE enabled=1 ORDER BY id"
        ).fetchall()

    if len(domains) > 100:
        return JSONResponse(
            {"error": "scan limit exceeded"},
            status_code=400,
        )

    started = time.time()
    started_ms = time.perf_counter()
    sem = asyncio.Semaphore(8)

    async def one(d):
        async with sem:
            return d, await tls_probe(d["domain"])

    pairs = await asyncio.gather(
        *(one(d) for d in domains)
    )

    duration = (time.perf_counter() - started_ms) * 1000
    ok = sum(
        1
        for _, result in pairs
        if result["status"] == "ok"
    )

    with db() as con:
        cur = con.execute(
            """
            INSERT INTO scans(
                started_at,
                duration_ms,
                total,
                ok
            )
            VALUES(?,?,?,?)
            """,
            (
                int(started),
                duration,
                len(domains),
                ok,
            ),
        )
        scan_id = cur.lastrowid

        con.executemany(
            """
            INSERT INTO results(
                scan_id,
                domain_id,
                status,
                latency_ms,
                tls_version,
                cert_subject,
                error
            )
            VALUES(?,?,?,?,?,?,?)
            """,
            [
                (
                    scan_id,
                    d["id"],
                    result["status"],
                    result["latency_ms"],
                    result["tls_version"],
                    result["cert_subject"],
                    result["error"],
                )
                for d, result in pairs
            ],
        )

    results = [
        {
            "domain": d["domain"],
            "label": d["label"],
            **result,
        }
        for d, result in pairs
    ]

    results.sort(
        key=lambda x: (
            x["status"] != "ok",
            x["latency_ms"]
            if x["latency_ms"] is not None
            else 999999,
        )
    )

    return {
        "scan_id": scan_id,
        "duration_ms": round(duration, 1),
        "total": len(domains),
        "ok": ok,
        "results": results,
    }


@app.get(BASE_PATH + "/api/history")
async def history(request: Request):
    if not require_auth(request):
        return JSONResponse(
            {"error": "unauthorized"},
            status_code=401,
        )

    with db() as con:
        rows = con.execute(
            """
            SELECT id, started_at, duration_ms, total, ok
            FROM scans
            ORDER BY id DESC
            LIMIT 20
            """
        ).fetchall()

    return [dict(x) for x in rows]


@app.post(BASE_PATH + "/api/domains")
async def add_domain(request: Request):
    if not require_auth(request):
        return JSONResponse(
            {"error": "unauthorized"},
            status_code=401,
        )

    body = await request.json()

    if not hmac.compare_digest(
        csrf(request),
        str(body.get("csrf", "")),
    ):
        return JSONResponse(
            {"error": "csrf"},
            status_code=403,
        )

    domain = valid_domain(
        str(body.get("domain", ""))
    )
    label = (
        str(body.get("label", domain or "Custom"))[:60].strip()
        or "Custom"
    )

    if not domain:
        return JSONResponse(
            {"error": "invalid domain"},
            status_code=400,
        )

    try:
        with db() as con:
            con.execute(
                """
                INSERT OR IGNORE INTO domains(
                    label,
                    domain,
                    enabled,
                    is_default,
                    created_at
                )
                VALUES(?,?,?,?,?)
                """,
                (
                    label,
                    domain,
                    1,
                    0,
                    int(time.time()),
                ),
            )
    except sqlite3.IntegrityError:
        return JSONResponse(
            {"error": "domain already exists"},
            status_code=409,
        )

    return {"ok": True}


@app.delete(BASE_PATH + "/api/domains/{domain_id}")
async def delete_domain(request: Request, domain_id: int):
    if not require_auth(request):
        return JSONResponse(
            {"error": "unauthorized"},
            status_code=401,
        )

    if not hmac.compare_digest(
        csrf(request),
        request.headers.get("x-csrf-token", ""),
    ):
        return JSONResponse(
            {"error": "csrf"},
            status_code=403,
        )

    with db() as con:
        row = con.execute(
            "SELECT is_default FROM domains WHERE id=?",
            (domain_id,),
        ).fetchone()

        if not row:
            return JSONResponse(
                {"error": "not found"},
                status_code=404,
            )

        if row[0]:
            return JSONResponse(
                {
                    "error": (
                        "default domain cannot be deleted; "
                        "disable it instead"
                    )
                },
                status_code=400,
            )

        con.execute(
            "DELETE FROM domains WHERE id=?",
            (domain_id,),
        )

    return {"ok": True}
