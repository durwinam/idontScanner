## v4.0.4

- Fixed duplicate select controls on Settings and dashboard pages.
- Centralized native `<select>` enhancement in `static/app.js` to prevent conflicting UI wrappers.
- Preserved custom Find Target selectors and existing selection/change behavior.
- Improved mobile selector rendering and removed the duplicate browser-style control shown under the custom selector.

# Changelog

## v4.0.4

- Fixed Telegram Account Security navigation and callback handling.
- Added native Telegram button colors and Premium custom-emoji icons.
- Added a legacy fallback for clients/bots that cannot use native button styling.
- Improved Telegram callback error isolation so one failed callback cannot stop other bot interactions.
- Preserved legacy `telegram_chat_id` as an owner fallback for existing installations.

# v4.0.4

- Fixed the mobile boot loading screen animations.
- Boot orbit, logo pulse, and progress bar now animate reliably even when interface animations are disabled.
- Progress bar now visibly fills during startup.
- Increased the mobile boot screen minimum display time for smoother rendering.
- Fixed `update.sh` catalog validation so the Python `tools` package is resolved correctly.
- Bumped installer/runtime identifiers to v4.0.4.
- Reworked Telegram inline keyboards to use stable Bot API fields, removing slow compatibility fallbacks.
- Fixed Account Security navigation and added Change Username, Change Password, Reset Password, Logout All Sessions, and Enable/Disable 2FA.
- Added TOTP-based 2FA verification for web panel login.
- Added per-IP login throttling: 3 failures → 5 minutes, 4 failures → 20 minutes, 5 failures → permanent IP block.
- Added Telegram security alerts for successful/failed logins and sensitive security actions without exposing passwords or OTP secrets.

# v4.0.1

- Fixed the Telegram Account Security menu so its actions render reliably.
- Added compatibility fallback for Telegram button styles and Premium custom emoji.
- Enabled the supplied Premium custom emoji IDs across supported Telegram buttons.
- Kept colored `primary`, `success`, and `danger` button styles for supported clients.
- Added Account Security actions for Change Username, Change Password, Reset Password, and Logout All Sessions.

# v4.0.0

- Split interface Settings and Telegram integration into separate sections.
- Added nine coordinated UI themes and persistent resource visualization preferences.
- Added Hybrid CPU/Memory/Disk gauge + live graph visualization.
- Added dedicated System Health page with bounded, on-demand checks.
- Added 15 MB single-file log rotation.
- Added Owner-only Telegram Account Security actions for username/password changes, password reset, and session revocation using the configured Premium Custom Emoji IDs.
- Preserved the existing main boot loading screen.
- Kept resource polling and diagnostics bounded to avoid unnecessary background CPU/RAM/Disk pressure.

## v3.6.2 — Release
- Ranked up to 10 certificate-backed SNI candidates in Target details.
- Based on the v3.6.1 source with the existing UI, loader, update flow, and 3,000-target catalog behavior retained.

# Changelog

## v3.6.1 — Release

- Version bumped to `v3.6.1`; v3.5.8 update hotfix behavior is retained.
- In-place update and 3,000-target catalog repair remain available without reinstalling the panel.

## v3.5.8 — In-place update + 3,000 target catalog

- Upgrading from an existing idontScanner installation now refreshes the Find Target catalog to 3,000 domains without reinstalling the panel.
- Persistent data, `.env`, database, port and virtual environment are preserved during update.
- `sudo idontScanner update` refreshes the updater script before running the upgrade, so older installations can receive the new update logic directly.
- `sudo bash /opt/idontScanner/update.sh` keeps the direct update path.
- Target catalog sync runs after source replacement and before database migration/service restart.
- Version bumped to `v3.5.8`.

## v3.5.8 — Check Host final polish

- Check Host → Info now enriches resolved domain/IP addresses with country, region, city, ISP, ASN, provider/datacenter and network type when available.
- Global Check-Host nodes now render reliable SVG country flags instead of depending on platform emoji fonts.
- Preserved the existing GitHub install/update flow and `idontScanner update` / `/opt/idontScanner/update.sh` behavior.

# v3.5.8

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

### v3.5.8 — Update hotfix
- `sudo idontScanner update` and `/opt/idontScanner/update.sh` no longer exit early when the app version is already current; they also repair a missing/incomplete 3,000-domain target catalog.
- Added a GitHub Tranco cache fallback for VPS networks where the official ranking endpoint is unreachable.
