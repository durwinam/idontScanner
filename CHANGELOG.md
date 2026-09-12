# v3.0.5

## Telegram UX & diagnostics
- Added a richer Telegram dashboard for Domain Scanner, Check Host, Smart Connection, VPS Speed, Server Status, History, Network Diagnostics, Scheduler, and Settings.
- Added Premium custom emoji mappings supplied by the project owner, including the Lion and Sun Iran marker with a 🦁 fallback.
- Added colored Telegram inline buttons throughout the bot.
- Added Telegram Check Host flow with Global and six Iran nodes.
- Added Smart Connection metrics for Download, Upload, Latency, and Jitter.
- Added Telegram VPS network-quality testing with bounded measurements.
- Added per-user target input flow for Check Host without exposing credentials.

## Web panel
- Preserved the existing 65-domain scanner behavior.
- Custom IP remains an independent raw target and does not override domain resolution, TLS, or SNI scanning.
- Versioning and installer paths are aligned on v3.0.5.

# v3.0.4

- Fixed Custom IP behavior: the 65 domain targets always use their normal VPS-resolved DNS/TLS scan path.
- Custom IP is now an additional raw IP target and never overrides the 65 domain targets.
- Custom IP results use ICMP with the existing TCP/443 reachability fallback and do not perform TLS or certificate inspection.
- Scanner UI clearly separates the optional Custom IP result from the domain results.

# Changelog

## v3.0.3

- Added a TCP/443 reachability fallback for Custom IP diagnostics when ICMP receives no reply.
- Custom IP remains a raw target; no TLS handshake or certificate inspection is performed in this mode.
- Added the Lion and Sun flag asset for Iran node selection and Iran result rows in Check Host.

## v3.0.3

- Fixed Check Host mobile layout overflow so all diagnostic controls remain inside the viewport.
- Improved responsive sizing for node-group and check-mode controls.
- Kept Custom IP scanner mode strictly ICMP/raw-ping based; DNS, TCP, TLS, SNI, and certificate checks remain disabled in this mode.
- Clarified raw-ping behavior when the target does not return ICMP replies.


## v3.0.1

- Added an internal Check Host workspace with Info, Ping, HTTP, TCP Port, UDP Port, and DNS checks through Check-Host global nodes.
- Added global node result cards with status, latency, packet loss, DNS records, HTTP status, and permanent reports.
- Added Download, Upload, Latency, and Jitter to Smart Connection without changing the standalone VPS Speed Test naming.
- Preserved Custom IP as a destination override across all enabled Domain Scanner targets while keeping each scanned domain as SNI.
- Added non-blocking web update notifications with current and latest versions.
- Hardened the terminal updater and CLI with updater self-recovery and safe version comparison.
- Version is now consistently reported as v3.0.1 in the web panel, installer, and CLI.

# Changelog

## v2.1.0

- Added 65 curated domain targets while preserving the original 41.
- Added Custom Ping Target for domain diagnostics with SNI preserved.
- Added scan score and lightweight scan intelligence.
- Added dedicated VPS Speed Test with animated progress UI.
- Added VPS Speed Test to navigation and dashboard.
- Added responsive glass UI for the new diagnostics.

# Changelog

## v2.0.0

### Dashboard enhancement
- Added a realtime server resource monitor for CPU, memory and disk usage with circular gauges and rolling performance charts.
- Added live uptime, load average, process count, network throughput and temperature observation when available.
- Resource metrics are read directly from the VPS and refreshed without reloading the dashboard.


- Modularized the application into configuration, persistence, scanning, security, scheduler, Telegram, and connection-diagnostic modules.
- Added a standalone update workflow that preserves `.env` and local SQLite data.
- Added `idontScanner update` to the management CLI.
- Added direct `update.sh` execution for maintenance without reinstalling.
- Added a one-command GitHub installation path through `install.sh`.
- Kept the existing Web Panel, Scanner APIs, Telegram configuration, Scheduler, and 41 default TLS targets intact.
- Standardized source formatting and shell scripting conventions.
