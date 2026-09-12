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
