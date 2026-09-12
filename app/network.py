"""Bounded direct network quality measurements used by diagnostics."""

from __future__ import annotations

import statistics
import time
import urllib.request

SPEED_ENDPOINT = "https://speed.cloudflare.com"
USER_AGENT = "idontScanner-NetworkDiagnostics/3.0"


def _request(
    url: str,
    method: str = "GET",
    data: bytes | None = None,
    timeout: float = 12.0,
):
    request = urllib.request.Request(
        url,
        method=method,
        data=data,
        headers={"User-Agent": USER_AGENT},
    )
    return urllib.request.urlopen(request, timeout=timeout)


def measure_network_quality() -> dict:
    """Run a small bounded download/upload and latency/jitter measurement."""
    download_samples: list[float] = []
    upload_samples: list[float] = []
    latency_samples: list[float] = []
    started_total = time.perf_counter()

    for _ in range(3):
        started = time.perf_counter()
        with _request(
            f"{SPEED_ENDPOINT}/__down?bytes=1000000",
            timeout=10,
        ) as response:
            response.read(128)
        latency_samples.append((time.perf_counter() - started) * 1000)

    for size in (2_000_000, 4_000_000, 8_000_000):
        started = time.perf_counter()
        received = 0
        with _request(
            f"{SPEED_ENDPOINT}/__down?bytes={size}",
            timeout=15,
        ) as response:
            while True:
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                received += len(chunk)
        elapsed = max(0.001, time.perf_counter() - started)
        download_samples.append(received * 8 / elapsed / 1_000_000)

    for size in (1_000_000, 2_000_000):
        payload = b"0" * size
        started = time.perf_counter()
        with _request(
            f"{SPEED_ENDPOINT}/__up",
            method="POST",
            data=payload,
            timeout=15,
        ) as response:
            response.read(64)
        elapsed = max(0.001, time.perf_counter() - started)
        upload_samples.append(size * 8 / elapsed / 1_000_000)

    jitter = statistics.pstdev(latency_samples) if len(latency_samples) > 1 else 0.0
    return {
        "download_mbps": round(statistics.mean(download_samples), 2),
        "upload_mbps": round(statistics.mean(upload_samples), 2),
        "latency_ms": round(statistics.mean(latency_samples), 1),
        "jitter_ms": round(jitter, 1),
        "samples": len(download_samples) + len(upload_samples) + len(latency_samples),
        "provider": "Cloudflare performance endpoint",
        "duration_ms": round((time.perf_counter() - started_total) * 1000, 1),
    }
