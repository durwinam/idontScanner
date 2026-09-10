"""SQLite persistence and application settings for idontScanner."""

from __future__ import annotations

import os
import time
import sqlite3

from app.config import DATA_DIR, DB_PATH, DEFAULT_DOMAINS

def db():
    """Open a configured SQLite connection with foreign keys enabled."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=20)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def init_db():
    schema = """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS domains (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            label TEXT NOT NULL,
            domain TEXT UNIQUE NOT NULL,
            category TEXT NOT NULL DEFAULT 'Custom',
            enabled INTEGER NOT NULL DEFAULT 1,
            is_default INTEGER NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS scans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at INTEGER NOT NULL,
            duration_ms REAL NOT NULL,
            total INTEGER NOT NULL,
            ok INTEGER NOT NULL,
            slow INTEGER NOT NULL DEFAULT 0,
            failed INTEGER NOT NULL DEFAULT 0,
            average_ms REAL
        );

        CREATE TABLE IF NOT EXISTS results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_id INTEGER NOT NULL,
            domain_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            latency_ms REAL,
            dns_ms REAL,
            tcp_ms REAL,
            tls_ms REAL,
            tls_version TEXT,
            alpn TEXT,
            cipher TEXT,
            ip TEXT,
            cert_subject TEXT,
            cert_issuer TEXT,
            cert_expires TEXT,
            cert_san TEXT,
            error TEXT,
            FOREIGN KEY(scan_id) REFERENCES scans(id) ON DELETE CASCADE,
            FOREIGN KEY(domain_id) REFERENCES domains(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip TEXT NOT NULL,
            user_agent TEXT NOT NULL,
            device TEXT NOT NULL,
            last_seen INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS scheduler (
            id INTEGER PRIMARY KEY CHECK(id = 1),
            enabled INTEGER NOT NULL DEFAULT 0,
            interval_minutes INTEGER NOT NULL DEFAULT 60,
            next_run INTEGER,
            notify_mode TEXT NOT NULL DEFAULT 'all',
            last_run INTEGER
        );

        INSERT OR IGNORE INTO scheduler(id) VALUES(1);
    """

    with db() as con:
        con.executescript(schema)

        domain_columns = {
            row[1] for row in con.execute("PRAGMA table_info(domains)")
        }
        if "category" not in domain_columns:
            con.execute(
                "ALTER TABLE domains ADD COLUMN category TEXT NOT NULL DEFAULT 'Custom'"
            )

        scan_columns = {
            row[1] for row in con.execute("PRAGMA table_info(scans)")
        }
        scan_migrations = {
            "slow": "ALTER TABLE scans ADD COLUMN slow INTEGER NOT NULL DEFAULT 0",
            "failed": "ALTER TABLE scans ADD COLUMN failed INTEGER NOT NULL DEFAULT 0",
            "average_ms": "ALTER TABLE scans ADD COLUMN average_ms REAL",
        }
        for name, statement in scan_migrations.items():
            if name not in scan_columns:
                con.execute(statement)

        result_columns = {
            row[1] for row in con.execute("PRAGMA table_info(results)")
        }
        result_migrations = {
            "dns_ms": "ALTER TABLE results ADD COLUMN dns_ms REAL",
            "tcp_ms": "ALTER TABLE results ADD COLUMN tcp_ms REAL",
            "tls_ms": "ALTER TABLE results ADD COLUMN tls_ms REAL",
            "alpn": "ALTER TABLE results ADD COLUMN alpn TEXT",
            "cipher": "ALTER TABLE results ADD COLUMN cipher TEXT",
            "ip": "ALTER TABLE results ADD COLUMN ip TEXT",
            "cert_issuer": "ALTER TABLE results ADD COLUMN cert_issuer TEXT",
            "cert_expires": "ALTER TABLE results ADD COLUMN cert_expires TEXT",
            "cert_san": "ALTER TABLE results ADD COLUMN cert_san TEXT",
        }
        for name, statement in result_migrations.items():
            if name not in result_columns:
                con.execute(statement)

        now = int(time.time())
        domain_rows = [
            (label, domain, category, 1, 1, now)
            for label, domain, category in DEFAULT_DOMAINS
        ]
        con.executemany(
            """
            INSERT OR IGNORE INTO domains(
                label, domain, category, enabled, is_default, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            domain_rows,
        )

        legacy_row = con.execute(
            "SELECT value FROM settings WHERE key='telegram_chat_id'"
        ).fetchone()
        owner_row = con.execute(
            "SELECT value FROM settings WHERE key='telegram_owner_id'"
        ).fetchone()

        legacy_chat = legacy_row[0] if legacy_row else ""
        owner_id = owner_row[0] if owner_row else ""
        if legacy_chat and not owner_id:
            con.execute(
                """
                INSERT INTO settings(key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                ("telegram_owner_id", legacy_chat),
            )


def get_setting(key, default=''):
    with db() as con:
        row = con.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
    return row[0] if row else default


def set_setting(key, value):
    """Create or replace one application setting."""
    with db() as con:
        con.execute(
            """
            INSERT INTO settings(key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )


def current_username():
    return get_setting('username', os.getenv('IDONTSCANNER_ADMIN_USERNAME', 'admin'))


def telegram_admin_ids():
    raw = get_setting('telegram_admin_ids', '')
    return {item.strip() for item in raw.split(',') if item.strip().lstrip('-').isdigit()}


def telegram_owner_id():
    return get_setting('telegram_owner_id', '').strip()


def telegram_allowed_chat(chat_id):
    value = str(chat_id)
    owner = telegram_owner_id()
    admins = telegram_admin_ids()
    return bool(value and (owner and value == owner or value in admins))


def telegram_configured_ids():
    ids = []
    owner = telegram_owner_id()
    if owner:
        ids.append(owner)
    ids.extend(sorted(telegram_admin_ids()))
    return ids

