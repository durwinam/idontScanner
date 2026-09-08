# idontScanner v1.0.0

A lightweight, self-hosted SNI/TLS connectivity diagnostic panel designed for VPS environments.

## Overview

idontScanner runs on your own server and tests a controlled list of domain targets from that server. It reports DNS/TCP/TLS connectivity, TLS version, certificate subject, and measured handshake latency.

The web interface is intentionally simple to deploy: there is no mandatory URL prefix. The panel is served directly from the root path.

## Features

- Dark, glass and neon interface
- Responsive dashboard for desktop and mobile
- Inline SVG neon icons
- Root web panel with clean routes
- First-run administrator password setup
- Scrypt password hashing
- Signed session cookies and CSRF protection
- Controlled concurrent TLS probes
- Latency and TLS diagnostics
- Searchable target list
- Custom domain management
- Scan history
- SQLite storage
- Hardened systemd service
- Automatic port availability check
- UFW integration when UFW is active
- No external database required

## Default Targets

The initial target list includes services from Cloudflare, Google, Microsoft, Apple, Amazon, GitHub, GitLab, Yahoo, Bing, Wikipedia, Fastly, Akamai, Telegram, WhatsApp, Discord, Netflix, Spotify, Reddit, Google Play, App Store and selected Iranian services such as Aparat, Digikala, Divar, Snapp, Irancell and MCI.

## Port

The default web port is **8088/tcp**. The installer checks the local machine before binding the service. If 8088 is already in use, it selects the next available TCP port automatically.

## Installation

Extract the release on the VPS and run:

```bash
cd idontScanner
chmod +x install.sh
sudo ./install.sh
```

The installer validates prerequisites, creates an isolated Python environment, installs dependencies, generates the application secret, creates a dedicated system user, installs the systemd service, starts it, optionally opens the selected port in UFW, and prints the final URL.

### First login

Open the URL printed by the installer. On first launch, choose an administrator password with at least 12 characters.

## Routes

```text
/
/login/
/logout/
/dashboard/
/api/scan
/api/history
/api/domains
/api/domains/{domain_id}
/static/
```

## Service Management

```bash
systemctl status idontscanner
systemctl restart idontscanner
systemctl stop idontscanner
journalctl -u idontscanner -f
```

## Security

The scanner only accepts domain names and does not execute shell commands. Requests are protected with authentication, CSRF validation and controlled concurrency. For public deployments, use HTTPS through a reverse proxy and restrict direct access to the application port where practical.

## Upgrade Notes

Before upgrading, back up the SQLite database and `.env`. Preserve the application secret and restart the systemd service after replacing the application files.

## Repository

`durwinam/idontScanner`

## License

MIT License. Copyright © 2026 Durwinam / idontScanner contributors.
