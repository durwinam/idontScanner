"""Domain TLS scanning and result persistence."""

from __future__ import annotations

import asyncio
import socket
import ssl
import time
import ipaddress
import re
import shutil
import subprocess

from app.config import DEFAULT_PORT, MAX_SCAN_TARGETS, SCAN_CONCURRENCY, TIMEOUT
from app.database import db

def peer_certificate_details(ssl_obj):
    """Extract display-safe certificate metadata from an SSL socket."""
    details = {
        "subject": "",
        "issuer": "",
        "expires": "",
        "san": "",
    }
    if not ssl_obj:
        return details

    try:
        cert = ssl_obj.getpeercert()
        details["subject"] = ", ".join(
            "=".join(item)
            for part in cert.get("subject", [])
            for item in part
        )
        details["issuer"] = ", ".join(
            "=".join(item)
            for part in cert.get("issuer", [])
            for item in part
        )
        details["expires"] = cert.get("notAfter", "")
        details["san"] = ", ".join(
            item[1]
            for item in cert.get("subjectAltName", [])
            if len(item) > 1
        )
    except (AttributeError, TypeError, ValueError):
        pass

    return details


def _tls_probe_sync(domain: str, connect_target: str | None = None):
    total_start = time.perf_counter()
    ip = ""
    dns_ms = None
    tcp_ms = None
    tls_ms = None
    sock = None
    tls_sock = None

    try:
        dns_start = time.perf_counter()
        infos = socket.getaddrinfo(
            domain,
            DEFAULT_PORT,
            type=socket.SOCK_STREAM,
        )
        dns_ms = (time.perf_counter() - dns_start) * 1000

        if not infos:
            raise OSError("DNS returned no address")

        resolved_ip = infos[0][4][0]
        ip = connect_target or resolved_ip
        if connect_target:
            ipaddress.ip_address(connect_target)
        tcp_start = time.perf_counter()
        sock = socket.create_connection(
            (ip, DEFAULT_PORT),
            timeout=TIMEOUT,
        )
        tcp_ms = (time.perf_counter() - tcp_start) * 1000

        context = ssl.create_default_context()
        context.set_alpn_protocols(["h2", "http/1.1"])

        tls_start = time.perf_counter()
        tls_sock = context.wrap_socket(
            sock,
            server_hostname=domain,
        )
        tls_ms = (time.perf_counter() - tls_start) * 1000
        ssl_obj = tls_sock
        details = peer_certificate_details(ssl_obj)

        return {
            "status": "ok",
            "latency_ms": round(
                (time.perf_counter() - total_start) * 1000,
                1,
            ),
            "dns_ms": round(dns_ms, 1),
            "tcp_ms": round(tcp_ms, 1),
            "tls_ms": round(tls_ms, 1),
            "tls_version": ssl_obj.version(),
            "alpn": ssl_obj.selected_alpn_protocol(),
            "cipher": ssl_obj.cipher()[0] if ssl_obj.cipher() else None,
            "ip": ip,
            "cert_subject": details["subject"],
            "cert_issuer": details["issuer"],
            "cert_expires": details["expires"],
            "cert_san": details["san"],
            "error": None,
        }
    except socket.timeout:
        return {
            "status": "timeout",
            "latency_ms": None,
            "dns_ms": dns_ms,
            "tcp_ms": tcp_ms,
            "tls_ms": tls_ms,
            "error": "Connection timed out",
            "ip": ip,
        }
    except socket.gaierror as exc:
        return {
            "status": "dns_error",
            "latency_ms": None,
            "dns_ms": dns_ms,
            "tcp_ms": tcp_ms,
            "tls_ms": tls_ms,
            "error": str(exc)[:180],
            "ip": ip,
        }
    except ssl.SSLCertVerificationError as exc:
        return {
            "status": "certificate_error",
            "latency_ms": None,
            "dns_ms": dns_ms,
            "tcp_ms": tcp_ms,
            "tls_ms": tls_ms,
            "error": str(exc)[:180],
            "ip": ip,
        }
    except ssl.SSLError as exc:
        return {
            "status": "tls_error",
            "latency_ms": None,
            "dns_ms": dns_ms,
            "tcp_ms": tcp_ms,
            "tls_ms": tls_ms,
            "error": str(exc)[:180],
            "ip": ip,
        }
    except ConnectionRefusedError:
        return {
            "status": "connection_refused",
            "latency_ms": None,
            "dns_ms": dns_ms,
            "tcp_ms": tcp_ms,
            "tls_ms": tls_ms,
            "error": "Connection refused",
            "ip": ip,
        }
    except OSError as exc:
        return {
            "status": "failed",
            "latency_ms": None,
            "dns_ms": dns_ms,
            "tcp_ms": tcp_ms,
            "tls_ms": tls_ms,
            "error": str(exc)[:180],
            "ip": ip,
        }
    finally:
        for candidate in (tls_sock, sock):
            if candidate:
                try:
                    candidate.close()
                except OSError:
                    pass



def _normalize_dns_name(value: str) -> str:
    value = (value or "").strip().lower().rstrip(".")
    if not value or len(value) > 253 or "*" in value or "/" in value or ":" in value:
        return ""
    labels = value.split(".")
    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789-")
    if len(labels) < 2:
        return ""
    if any(
        not label
        or len(label) > 63
        or label.startswith("-")
        or label.endswith("-")
        or any(ch not in allowed for ch in label)
        for label in labels
    ):
        return ""
    return value


def certificate_sni_candidates(cert_san: str, original_host: str = "") -> list[str]:
    """Return concrete DNS SAN names that are valid SNI candidates.

    Candidates are derived only from the certificate presented by the target.
    Wildcard SANs are intentionally excluded because they are not concrete SNI
    hostnames. The original host is excluded so the UI can distinguish an
    alternate certificate-backed SNI from the direct host.
    """
    original = _normalize_dns_name(original_host)
    seen = set()
    candidates = []
    for raw in (cert_san or "").split(","):
        name = _normalize_dns_name(raw)
        if not name or name == original or name in seen:
            continue
        seen.add(name)
        candidates.append(name)
        if len(candidates) >= 4:
            break
    return candidates


def _probe_sni_sync(connect_ip: str, sni_host: str):
    """Validate a certificate-backed SNI against a known target IP.

    This is a normal HTTPS/TLS virtual-host diagnostic: TCP connects to the
    target IP while the requested hostname is sent through TLS SNI and the
    system trust store validates the resulting certificate/hostname.
    """
    started = time.perf_counter()
    sock = None
    tls_sock = None
    try:
        ipaddress.ip_address(connect_ip)
        host = _normalize_dns_name(sni_host)
        if not host:
            raise ValueError("Invalid SNI hostname")
        sock = socket.create_connection((connect_ip, DEFAULT_PORT), timeout=min(TIMEOUT, 2.5))
        context = ssl.create_default_context()
        context.set_alpn_protocols(["h2", "http/1.1"])
        tls_sock = context.wrap_socket(sock, server_hostname=host)
        details = peer_certificate_details(tls_sock)
        return {
            "status": "ok",
            "sni": host,
            "sni_latency_ms": round((time.perf_counter() - started) * 1000, 1),
            "sni_tls_version": tls_sock.version(),
            "sni_alpn": tls_sock.selected_alpn_protocol(),
            "sni_cipher": tls_sock.cipher()[0] if tls_sock.cipher() else None,
            "sni_cert_san": details["san"],
            "sni_verified": True,
            "error": None,
        }
    except ssl.SSLCertVerificationError as exc:
        return {"status":"certificate_error","sni":sni_host,"sni_latency_ms":None,"sni_tls_version":None,"sni_alpn":None,"sni_verified":False,"error":str(exc)[:180]}
    except (ssl.SSLError, socket.timeout, ConnectionError, OSError, ValueError) as exc:
        return {"status":"failed","sni":sni_host,"sni_latency_ms":None,"sni_tls_version":None,"sni_alpn":None,"sni_verified":False,"error":str(exc)[:180]}
    finally:
        for candidate in (tls_sock, sock):
            if candidate:
                try:
                    candidate.close()
                except OSError:
                    pass


async def probe_sni(connect_ip: str, sni_host: str):
    return await asyncio.to_thread(_probe_sni_sync, connect_ip, sni_host)

def _raw_ping_sync(target: str):
    """Ping a validated raw IP with the system ICMP utility.

    Custom-target scanner mode intentionally stops at ICMP. It does not
    resolve the domain, open TCP, perform TLS, or inspect certificates.
    """
    ipaddress.ip_address(target)
    ping_binary = shutil.which("ping")
    if not ping_binary:
        return {
            "status": "failed",
            "latency_ms": None,
            "ip": target,
            "ping_min_ms": None,
            "ping_avg_ms": None,
            "ping_max_ms": None,
            "jitter_ms": None,
            "packet_loss": 100.0,
            "error": "The system ping utility is not installed.",
        }

    command = [ping_binary, "-c", "4", "-W", "2"]
    if ipaddress.ip_address(target).version == 6:
        command.insert(1, "-6")
    command.append(target)

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "status": "timeout",
            "latency_ms": None,
            "ip": target,
            "ping_min_ms": None,
            "ping_avg_ms": None,
            "ping_max_ms": None,
            "jitter_ms": None,
            "packet_loss": 100.0,
            "error": "ICMP ping timed out." if isinstance(exc, subprocess.TimeoutExpired) else str(exc)[:180],
        }

    output = f"{completed.stdout}\n{completed.stderr}"
    loss_match = re.search(r"([0-9]+(?:\.[0-9]+)?)%\s*packet loss", output)
    rtt_match = re.search(
        r"(?:rtt|round-trip).*?=\s*([0-9.]+)/([0-9.]+)/([0-9.]+)/([0-9.]+)",
        output,
    )
    loss = float(loss_match.group(1)) if loss_match else 100.0

    if not rtt_match:
        return {
            "status": "timeout" if completed.returncode else "failed",
            "latency_ms": None,
            "ip": target,
            "ping_min_ms": None,
            "ping_avg_ms": None,
            "ping_max_ms": None,
            "jitter_ms": None,
            "packet_loss": round(loss, 1),
            "error": "No ICMP reply received." if loss >= 100 else "Could not parse ICMP timing.",
        }

    minimum, average, maximum, jitter = map(float, rtt_match.groups())
    return {
        "status": "ok" if loss < 100 else "timeout",
        "latency_ms": round(average, 1),
        "ip": target,
        "ping_min_ms": round(minimum, 1),
        "ping_avg_ms": round(average, 1),
        "ping_max_ms": round(maximum, 1),
        "jitter_ms": round(jitter, 1),
        "packet_loss": round(loss, 1),
        "error": None if loss < 100 else "All ICMP packets were lost.",
    }


def _tcp_fallback_sync(target: str, port: int = 443):
    """Check basic reachability when ICMP does not receive a reply.

    This is deliberately a single service-port probe, not a port scan. It
    answers a narrow diagnostic question: can the target accept a TCP
    connection when ICMP is unavailable or filtered?
    """
    address = ipaddress.ip_address(target)
    family = socket.AF_INET6 if address.version == 6 else socket.AF_INET
    started = time.perf_counter()
    sock = socket.socket(family, socket.SOCK_STREAM)
    sock.settimeout(3.0)

    try:
        if family == socket.AF_INET6:
            sock.connect((target, port, 0, 0))
        else:
            sock.connect((target, port))

        latency_ms = (time.perf_counter() - started) * 1000
        return {
            "status": "ok",
            "latency_ms": round(latency_ms, 1),
            "tcp_fallback_ms": round(latency_ms, 1),
            "fallback_port": port,
            "error": None,
        }
    except socket.timeout:
        return {
            "status": "timeout",
            "latency_ms": None,
            "tcp_fallback_ms": None,
            "fallback_port": port,
            "error": f"TCP port {port} timed out.",
        }
    except OSError as exc:
        return {
            "status": "failed",
            "latency_ms": None,
            "tcp_fallback_ms": None,
            "fallback_port": port,
            "error": str(exc)[:180],
        }
    finally:
        sock.close()


async def raw_ping_probe(target: str):
    result = await asyncio.to_thread(_raw_ping_sync, target)

    if result.get("status") in {"timeout", "failed"} and result.get("packet_loss", 100) >= 100:
        fallback = await asyncio.to_thread(_tcp_fallback_sync, target, 443)
        result["icmp_status"] = "unavailable"
        result["tcp_fallback"] = fallback

        if fallback.get("status") == "ok":
            result["status"] = "ok"
            result["latency_ms"] = fallback["latency_ms"]
            result["reachability"] = "tcp_fallback"
            result["error"] = None
        else:
            result["reachability"] = "unreachable"

    elif result.get("status") == "ok":
        result["icmp_status"] = "ok"
        result["reachability"] = "icmp"

    return result


async def tls_probe(domain: str, connect_target: str | None = None):
    return await asyncio.to_thread(_tls_probe_sync, domain, connect_target)


async def run_scan(connect_target: str | None = None):
    with db() as con:
        domains = con.execute(
            """
            SELECT *
            FROM domains
            WHERE enabled = 1
            ORDER BY id
            LIMIT 100
            """
        ).fetchall()

    started = int(time.time())
    start_perf = time.perf_counter()
    semaphore = asyncio.Semaphore(8)

    async def scan_domain(domain):
        async with semaphore:
            # Domain Scanner behavior is intentionally unchanged.
            # Custom IP is an independent raw target and must never replace
            # the resolved endpoint of any domain in the 65-target scan.
            result = await tls_probe(domain["domain"])
            return domain, result

    pairs = await asyncio.gather(
        *(scan_domain(domain) for domain in domains)
    )
    duration = (time.perf_counter() - start_perf) * 1000

    ok_count = sum(
        1
        for _, result in pairs
        if result.get("status") == "ok"
    )
    slow_count = sum(
        1
        for _, result in pairs
        if result.get("status") == "ok"
        and (result.get("latency_ms") or 0) >= 200
    )
    failed_count = len(pairs) - ok_count

    latencies = [
        result["latency_ms"]
        for _, result in pairs
        if result.get("latency_ms") is not None
    ]
    average = sum(latencies) / len(latencies) if latencies else None

    with db() as con:
        cursor = con.execute(
            """
            INSERT INTO scans(
                started_at,
                duration_ms,
                total,
                ok,
                slow,
                failed,
                average_ms
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                started,
                duration,
                len(pairs),
                ok_count,
                slow_count,
                failed_count,
                average,
            ),
        )
        scan_id = cursor.lastrowid

        result_rows = [
            (
                scan_id,
                domain["id"],
                result.get("status"),
                result.get("latency_ms"),
                result.get("dns_ms"),
                result.get("tcp_ms"),
                result.get("tls_ms"),
                result.get("tls_version"),
                result.get("alpn"),
                result.get("cipher"),
                result.get("ip"),
                result.get("cert_subject"),
                result.get("cert_issuer"),
                result.get("cert_expires"),
                result.get("cert_san"),
                result.get("error"),
            )
            for domain, result in pairs
        ]
        con.executemany(
            """
            INSERT INTO results(
                scan_id,
                domain_id,
                status,
                latency_ms,
                dns_ms,
                tcp_ms,
                tls_ms,
                tls_version,
                alpn,
                cipher,
                ip,
                cert_subject,
                cert_issuer,
                cert_expires,
                cert_san,
                error
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            result_rows,
        )

    results = []
    for domain, result in pairs:
        item = {
            "domain": domain["domain"],
            "label": domain["label"],
            "category": domain["category"],
            **result,
        }
        latency = float(item.get("latency_ms") or 9999)
        tls = item.get("tls_version") or ""
        alpn = item.get("alpn") or ""
        tls_score = 1.0 if tls == "TLSv1.3" else 0.85 if tls == "TLSv1.2" else 0.3
        alpn_score = 1.0 if alpn == "h2" else 0.7 if alpn == "http/1.1" else 0.25
        latency_score = max(0.0, min(1.0, 1.0 - latency / 500.0))
        healthy = 1.0 if item.get("status") == "ok" else 0.0
        item["host_ok"] = bool(item.get("tcp_ms") is not None and healthy)
        item["sni_ok"] = bool(item.get("tls_version") and healthy)
        item["score"] = round((healthy*.25 + latency_score*.35 + tls_score*.25 + alpn_score*.15) * 100, 1)
        results.append(item)
    results.sort(key=lambda item: (item.get("status") != "ok", -item.get("score", 0), item.get("latency_ms") if item.get("latency_ms") is not None else 999999))

    score = 0
    if pairs:
        health_ratio = ok_count / len(pairs)
        score = round(health_ratio * 70)
        if average is not None:
            score += 20 if average < 80 else 14 if average < 150 else 8 if average < 250 else 0
        if slow_count == 0:
            score += 10
        elif slow_count <= max(1, len(pairs) // 10):
            score += 5
        score = max(0, min(100, score))

    custom_target = None
    if connect_target:
        custom_result = await raw_ping_probe(connect_target)
        custom_target = {
            "target": connect_target,
            "mode": "raw_ping",
            **custom_result,
        }

    return {
        "scan_id": scan_id,
        "started_at": started,
        "duration_ms": round(duration, 1),
        "target": "VPS-resolved endpoints",
        "mode": "tls",
        "custom_target": custom_target,
        "score": score,
        "score_label": (
            "EXCELLENT" if score >= 90
            else "GOOD" if score >= 75
            else "FAIR" if score >= 55
            else "NEEDS ATTENTION"
        ),
        "total": len(pairs),
        "ok": ok_count,
        "slow": slow_count,
        "failed": failed_count,
        "average_ms": round(average, 1) if average is not None else None,
        "results": results,
    }

