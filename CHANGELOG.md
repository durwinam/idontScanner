# v3.5.7

- Completed Persian/English UI coverage across the main dashboard, scanner, connection, settings, account, domains, Check Host, Speed Test and Find Target surfaces.
- Fixed custom dropdown layering by rendering opened native-select menus in a viewport-level portal so they no longer disappear behind cards or panels.
- Added a polished boot/loading screen for panel entry and a dedicated animated Deep Diagnostics loading state.
- Refined Find Target rows to show only the useful at-a-glance signals: target, score, Host/SNI status, SNI and latency. Verbose TLS/ALPN/ISP data remains inside the three-dot details view.
- Improved light-theme contrast for cards, menus, controls, diagnostics and Find Target results.
- Preserved existing scanner, benchmark, SNI validation, catalog and Deep Diagnostics logic.

## v3.5.2

- Fixed Find Target presentation: the 3,000-domain benchmark catalog is loaded automatically and remains hidden from the main UI.
- Replaced browser-native-looking controls with consistent glass dropdowns and compact responsive toolbar controls.
- Added an authenticated benchmark-catalog API and runtime catalog recovery.
- Added a Tranco snapshot fallback for installations where the official catalog endpoint is temporarily unreachable.
- Kept the 30-second benchmark, ranking logic, SNI validation and Deep Diagnostics architecture unchanged.
- Added on-demand Target Details via the three-dot action on Find Target results.
- Added VPS-to-target TCP latency/jitter and bounded target HTTPS download measurement.
- Added Iranian Check-Host node diagnostics for ping and HTTP response timing.
- Upload throughput is reported only when a safe target-side upload endpoint exists; arbitrary site upload is never fabricated.
- Hardened target throughput resolution to public IPv4 addresses to reduce SSRF risk.

## v3.4.9

- Added the 3,000-target Find Target benchmark with a hard 30-second deadline.
- Added certificate-backed SNI candidate validation and ranking.
- Added up to 20 persistent custom benchmark targets.
- Improved ranking, host/TLS/SNI health signals, ISP enrichment for top results, and Top 15/30 output.
- Restored and retained Host Check and VPS Speed Test.
- Increased Domain Scanner to 100 configured targets.
- Added session revoke controls and creator footer links.

## v3.0.4

- Fixed Custom IP behavior and retained the 100-domain scanner path.
- Added TCP/443 reachability fallback for raw Custom IP diagnostics.
- Added the Iran node marker for Check Host.

## v3.0.1

- Added Check Host with global and Iran nodes.
- Added Download, Upload, Latency, and Jitter to Smart Connection.
- Added non-blocking web update notifications.
- Hardened the terminal updater and CLI.

## v2.1.0

- Added curated domain targets while preserving the original scanner behavior.
- Added Custom Ping Target and scan score.
- Added dedicated VPS Speed Test and responsive glass UI.

## v2.0.0

- Added realtime server resource monitoring.
- Modularized persistence, scanning, security, scheduler, Telegram and connection diagnostics.
- Added a standalone update workflow that preserves `.env` and SQLite data.
