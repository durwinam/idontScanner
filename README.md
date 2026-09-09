# idontScanner v2.0.0

A lightweight, self-hosted SNI / TLS connectivity diagnostic panel for controlled targets.

> **Scope:** idontScanner performs normal DNS, TCP and TLS diagnostics from the VPS. It is designed for domains and endpoints you are authorized to test. It does not configure Xray, generate bypass configurations, or perform Internet-wide IP-range scanning.

## Highlights

- Dark glass / neon responsive dashboard with SVG icons
- Mobile sidebar navigation
- Username + password authentication
- Scrypt password hashing with low-memory fallback
- Recent login devices: last 3 IP / browser / platform sessions
- Password and username management
- Domain library with categories and enable/disable controls
- Real TLS details: IP, DNS timing, TCP timing, TLS version, ALPN, cipher and certificate metadata when available
- Per-target `⋮` details modal
- Scan history and detailed historical results
- SNI behavior check for controlled target/SNI comparisons
- CDN / Akamai endpoint diagnostics for a specific domain
- Optional Telegram Bot integration using polling (no HTTPS webhook required)
- Optional Scheduler: 30 minutes to 24 hours, 30-minute steps
- Telegram scheduled reports and failure/attention mode
- HTTP-only operation on a VPS IP; SSL is not required
- Professional `install.sh` with `--fresh`, automatic venv setup, port selection and health checks

## Install

```bash
unzip idontScanner-v2.0.0.zip
cd idontScanner-2.0.0
sudo bash install.sh --fresh
```

The installer asks for the admin username and password and starts the panel on HTTP. The preferred port is `8088`; if it is busy, the installer selects the next available TCP port.

After installation:

```text
http://SERVER_IP:8088/
```

The exact URL and selected port are printed at the end of installation.

## Management

```bash
sudo systemctl status idontscanner
sudo systemctl restart idontscanner
sudo journalctl -u idontscanner -f
```

Fresh reinstall:

```bash
sudo bash install.sh --fresh
```

Disable automatic UFW changes:

```bash
sudo bash install.sh --fresh --no-ufw
```

## Telegram

Telegram is optional. Add a BotFather token under **Settings → Telegram bot**, save it, then open the bot and send `/start` from the intended private chat. Polling is used so the panel can remain HTTP-only.

The bot supports a compact inline menu, manual scan, status and scheduler information. Scheduled notifications can be configured as every-result or attention-only.

## Scheduler

The scheduler is **off by default**. When enabled, it stores its state in SQLite and resumes after a service restart.

Supported intervals:

- 30 minutes
- 1 hour
- 1.5 hours
- 2 hours
- 3 hours
- 6 hours
- 12 hours
- 24 hours

## Security notes

- Passwords are never stored in plaintext.
- Password hashing uses salted scrypt with a memory-aware fallback.
- Login and mutating API routes use a session-bound CSRF token.
- Systemd runs the application under a dedicated unprivileged user.
- Scanner inputs are validated as hostnames; arbitrary shell commands are never built from target input.
- The app intentionally disables HTTPS redirects because this release is designed for direct HTTP access on a VPS IP.

## Version

`v2.0.0`

## License

MIT — Copyright (c) 2026 Darwin.
