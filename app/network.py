"""Bounded network measurements used by idontScanner diagnostics."""

from __future__ import annotations

import ipaddress
import socket
import ssl
import statistics
import time
import urllib.request

SPEED_ENDPOINT = "https://speed.cloudflare.com"
USER_AGENT = "idontScanner-NetworkDiagnostics/3.5.0"


def _request(url: str, method: str = "GET", data: bytes | None = None, timeout: float = 12.0):
    request = urllib.request.Request(
        url,
        method=method,
        data=data,
        headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"},
    )
    return urllib.request.urlopen(request, timeout=timeout)


def measure_network_quality() -> dict:
    """Measure the scanner VPS's own internet path using Cloudflare's test endpoint."""
    download_samples: list[float] = []
    upload_samples: list[float] = []
    latency_samples: list[float] = []
    started_total = time.perf_counter()

    for _ in range(3):
        started = time.perf_counter()
        with _request(f"{SPEED_ENDPOINT}/__down?bytes=1000000", timeout=8) as response:
            response.read(128)
        latency_samples.append((time.perf_counter() - started) * 1000)

    for size in (2_000_000, 4_000_000, 8_000_000):
        started = time.perf_counter()
        received = 0
        with _request(f"{SPEED_ENDPOINT}/__down?bytes={size}", timeout=15) as response:
            while True:
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                received += len(chunk)
        elapsed = max(0.001, time.perf_counter() - started)
        if received:
            download_samples.append(received * 8 / elapsed / 1_000_000)

    for size in (1_000_000, 2_000_000):
        payload = b"0" * size
        started = time.perf_counter()
        with _request(f"{SPEED_ENDPOINT}/__up", method="POST", data=payload, timeout=15) as response:
            response.read(64)
        elapsed = max(0.001, time.perf_counter() - started)
        upload_samples.append(size * 8 / elapsed / 1_000_000)

    return {
        "download_mbps": round(statistics.mean(download_samples), 2) if download_samples else None,
        "upload_mbps": round(statistics.mean(upload_samples), 2) if upload_samples else None,
        "latency_ms": round(statistics.mean(latency_samples), 1) if latency_samples else None,
        "jitter_ms": round(statistics.pstdev(latency_samples), 1) if len(latency_samples) > 1 else 0.0,
        "samples": len(download_samples) + len(upload_samples) + len(latency_samples),
        "provider": "Cloudflare performance endpoint",
        "duration_ms": round((time.perf_counter() - started_total) * 1000, 1),
    }


def _public_ip(value: str) -> bool:
    try:
        addr = ipaddress.ip_address(value)
        return not (
            addr.is_private or addr.is_loopback or addr.is_link_local
            or addr.is_multicast or addr.is_reserved or addr.is_unspecified
        )
    except ValueError:
        return False


def resolve_public_ipv4(host: str) -> list[str]:
    infos = socket.getaddrinfo(host, 443, family=socket.AF_INET, type=socket.SOCK_STREAM)
    ips: list[str] = []
    for item in infos:
        ip = item[4][0]
        if _public_ip(ip) and ip not in ips:
            ips.append(ip)
    if not ips:
        raise OSError("Target did not resolve to a public IPv4 address")
    return ips


def _connect_samples(ip: str, count: int = 5) -> tuple[list[float], int]:
    samples: list[float] = []
    failures = 0
    for _ in range(count):
        started = time.perf_counter()
        sock = None
        try:
            sock = socket.create_connection((ip, 443), timeout=2.5)
            samples.append((time.perf_counter() - started) * 1000)
        except OSError:
            failures += 1
        finally:
            if sock:
                sock.close()
    return samples, failures


def measure_target_path(host: str, sni: str | None = None, max_bytes: int = 4 * 1024 * 1024) -> dict:
    """Measure VPS -> target TCP/TLS quality and real HTTPS response throughput.

    Download is reported only when the target actually transfers enough bytes to
    make a meaningful throughput sample. Upload is intentionally not fabricated:
    an arbitrary public website does not provide a safe generic upload endpoint.
    """
    host = host.strip().lower().rstrip(".")
    sni_host = (sni or host).strip().lower().rstrip(".")
    ip = resolve_public_ipv4(host)[0]

    tcp_samples, failures = _connect_samples(ip, 5)
    if not tcp_samples:
        raise OSError("Target did not accept TCP connections on port 443")

    sock = None
    tls = None
    try:
        started = time.perf_counter()
        sock = socket.create_connection((ip, 443), timeout=3.5)
        context = ssl.create_default_context()
        context.set_alpn_protocols(["h2", "http/1.1"])
        tls = context.wrap_socket(sock, server_hostname=sni_host)
        tls.settimeout(4.0)

        # A bounded GET is used only as a read test. Range is a hint; servers may
        # ignore it. We never claim a speed value unless enough bytes arrive.
        request = (
            "GET / HTTP/1.1\r\n"
            f"Host: {sni_host}\r\n"
            f"User-Agent: {USER_AGENT}\r\n"
            "Accept: */*\r\n"
            "Accept-Encoding: identity\r\n"
            f"Range: bytes=0-{max_bytes - 1}\r\n"
            "Connection: close\r\n\r\n"
        ).encode("ascii", "ignore")
        tls.sendall(request)

        header = b""
        while b"\r\n\r\n" not in header and len(header) < 65536:
            chunk = tls.recv(4096)
            if not chunk:
                break
            header += chunk
        sep = header.find(b"\r\n\r\n")
        body = header[sep + 4:] if sep >= 0 else b""
        status_line = header.split(b"\r\n", 1)[0].decode("latin1", "replace") if header else ""
        received = min(len(body), max_bytes)
        while received < max_bytes:
            chunk = tls.recv(min(256 * 1024, max_bytes - received))
            if not chunk:
                break
            received += len(chunk)
        elapsed = max(0.001, time.perf_counter() - started)
        throughput = received * 8 / elapsed / 1_000_000
        tls_version = tls.version()
        alpn = tls.selected_alpn_protocol()
    finally:
        for candidate in (tls, sock):
            if candidate:
                try:
                    candidate.close()
                except OSError:
                    pass

    return {
        "ip": ip,
        "sni": sni_host,
        "tcp_latency_ms": round(statistics.mean(tcp_samples), 1),
        "jitter_ms": round(statistics.pstdev(tcp_samples), 1) if len(tcp_samples) > 1 else 0.0,
        "tcp_loss_percent": round((failures / 5) * 100, 1),
        "download_mbps": round(throughput, 2) if received >= 262_144 else None,
        "download_bytes": received,
        "download_confidence": "good" if received >= 1_048_576 else "limited" if received >= 262_144 else "insufficient",
        "upload_mbps": None,
        "upload_status": "not_measurable_without_target_upload_endpoint",
        "http_status": status_line,
        "tls_version": tls_version,
        "alpn": alpn,
    }
