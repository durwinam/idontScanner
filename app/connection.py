"""Connection parsing and endpoint diagnostics for idontScanner."""
from __future__ import annotations

import asyncio
import base64
import binascii
import ipaddress
import json
import socket
import ssl
import time
import uuid
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

SUPPORTED_SCHEMES = {"vless", "vmess", "trojan", "ss", "hysteria2"}
SUPPORTED_NETWORKS = {
    "tcp", "raw", "http", "h2", "ws", "httpupgrade", "grpc", "gun",
    "xhttp", "splithttp", "quic", "kcp",
}
SUPPORTED_SECURITY = {"", "none", "tls", "reality"}
SOCKET_TIMEOUT = 4.0
SERVICE_ATTEMPTS = 3
DEFAULT_HTTPS_PORT = 443
SERVICE_ENDPOINTS = {
    "instagram": ("www.instagram.com", "/robots.txt"),
    "youtube": ("www.youtube.com", "/generate_204"),
    "telegram": ("telegram.org", "/"),
}


def _validate_hostname(value: str) -> str:
    value = value.strip()
    if not value or len(value) > 253:
        raise ValueError("invalid host")
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        pass
    value = value.rstrip(".")
    labels = value.split(".")
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")
    if any(
        not label or len(label) > 63 or label.startswith("-")
        or label.endswith("-") or any(c not in allowed for c in label)
        for label in labels
    ):
        raise ValueError("invalid host")
    return value


def _q(query: dict[str, list[str]], key: str, default: str = "") -> str:
    return query.get(key, [default])[0]


def _port(value: str | int | None) -> int:
    try:
        port = int(value or 0)
    except (TypeError, ValueError):
        raise ValueError("invalid port") from None
    if not 1 <= port <= 65535:
        raise ValueError("invalid port")
    return port


def _decode_base64(value: str) -> bytes:
    value = "".join(value.split())
    value += "=" * (-len(value) % 4)
    try:
        return base64.b64decode(value, validate=False)
    except (binascii.Error, ValueError):
        try:
            return base64.urlsafe_b64decode(value)
        except (binascii.Error, ValueError):
            raise ValueError("invalid base64 configuration") from None


def _transport(query: dict[str, list[str]]) -> dict[str, Any]:
    network = _q(query, "type", "tcp").lower()
    if network not in SUPPORTED_NETWORKS:
        raise ValueError(f"unsupported transport: {network}")
    return {
        "network": network,
        "path": _q(query, "path"),
        "service_name": _q(query, "serviceName"),
        "host_header": _q(query, "host"),
        "authority": _q(query, "authority"),
        "header_type": _q(query, "headerType", "none"),
        "mode": _q(query, "mode"),
    }


def _tls(query: dict[str, list[str]]) -> dict[str, Any]:
    security = _q(query, "security").lower()
    if security not in SUPPORTED_SECURITY:
        raise ValueError(f"unsupported security mode: {security}")
    sni = _q(query, "sni").strip()
    if sni:
        sni = _validate_hostname(sni)
    return {
        "security": security or "none",
        "sni": sni,
        "alpn": unquote(_q(query, "alpn")),
        "fingerprint": _q(query, "fp"),
        "flow": _q(query, "flow"),
        "reality_public_key": _q(query, "pbk"),
        "reality_short_id": _q(query, "sid"),
    }


def _parse_vless(parsed) -> dict[str, Any]:
    if not parsed.hostname or not parsed.port:
        raise ValueError("VLESS link must include host and port")
    try:
        user_id = uuid.UUID(unquote(parsed.username or ""))
    except (AttributeError, ValueError):
        raise ValueError("invalid VLESS UUID") from None
    query = parse_qs(parsed.query, keep_blank_values=True)
    return {
        "scheme": "vless", "protocol": "VLESS", "uuid": str(user_id),
        "host": _validate_hostname(parsed.hostname), "port": parsed.port,
        **_transport(query), **_tls(query),
        "encryption": _q(query, "encryption", "none"),
    }


def _parse_vmess(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(_decode_base64(raw[len("vmess://"):]).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("invalid VMess payload") from None
    host = str(payload.get("add", "")).strip()
    if not host:
        raise ValueError("VMess link must include an address")
    network = str(payload.get("net", "tcp") or "tcp").lower()
    if network not in SUPPORTED_NETWORKS:
        raise ValueError(f"unsupported VMess transport: {network}")
    try:
        vmess_id = uuid.UUID(str(payload.get("id", "")))
    except (ValueError, AttributeError):
        raise ValueError("invalid VMess UUID") from None
    security = str(payload.get("tls", "") or "").lower()
    security = security if security in SUPPORTED_SECURITY else "none"
    sni = str(payload.get("sni", "") or "").strip()
    if sni:
        sni = _validate_hostname(sni)
    alpn = payload.get("alpn", "")
    if isinstance(alpn, list):
        alpn = ",".join(str(x) for x in alpn)
    return {
        "scheme": "vmess", "protocol": "VMess", "uuid": str(vmess_id),
        "host": _validate_hostname(host), "port": _port(payload.get("port")),
        "network": network, "security": security, "sni": sni,
        "alpn": str(alpn or ""), "path": str(payload.get("path", "") or ""),
        "service_name": str(payload.get("serviceName", "") or ""),
        "host_header": str(payload.get("host", "") or ""),
        "header_type": str(payload.get("type", "none") or "none"),
        "fingerprint": str(payload.get("fp", "") or ""),
        "cipher": str(payload.get("scy", "") or ""),
        "remark": str(payload.get("ps", "") or ""),
    }


def _parse_trojan(parsed) -> dict[str, Any]:
    if not parsed.hostname or not parsed.port:
        raise ValueError("Trojan link must include host and port")
    if not parsed.username:
        raise ValueError("Trojan link must include a password")
    query = parse_qs(parsed.query, keep_blank_values=True)
    return {
        "scheme": "trojan", "protocol": "Trojan",
        "host": _validate_hostname(parsed.hostname), "port": parsed.port,
        **_transport(query), **_tls(query), "credential_present": True,
    }


def _parse_shadowsocks(parsed) -> dict[str, Any]:
    if not parsed.hostname or not parsed.port:
        raise ValueError("Shadowsocks link must include host and port")
    if not parsed.username:
        raise ValueError("Shadowsocks link must include credentials")
    try:
        credentials = _decode_base64(unquote(parsed.username)).decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("invalid Shadowsocks credentials") from None
    if ":" not in credentials:
        raise ValueError("invalid Shadowsocks credentials")
    method, password = credentials.split(":", 1)
    return {
        "scheme": "ss", "protocol": "Shadowsocks",
        "host": _validate_hostname(parsed.hostname), "port": parsed.port,
        "network": "tcp/udp", "security": "none", "method": method,
        "credential_present": bool(password), "remark": unquote(parsed.fragment or ""),
    }


def _parse_hysteria2(parsed) -> dict[str, Any]:
    if not parsed.hostname or not parsed.port:
        raise ValueError("Hysteria2 link must include host and port")
    query = parse_qs(parsed.query, keep_blank_values=True)
    sni = _q(query, "sni").strip()
    if sni:
        sni = _validate_hostname(sni)
    return {
        "scheme": "hysteria2", "protocol": "Hysteria2",
        "host": _validate_hostname(parsed.hostname), "port": parsed.port,
        "network": "quic", "security": "tls", "sni": sni,
        "alpn": unquote(_q(query, "alpn")), "obfs": _q(query, "obfs"),
        "fingerprint": _q(query, "fp"),
        "credential_present": bool(unquote(parsed.username or "")),
        "remark": unquote(parsed.fragment or ""),
    }


def parse_wireguard_config(text: str) -> dict[str, Any]:
    sections: dict[str, dict[str, str]] = {}
    current: dict[str, str] | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = sections.setdefault(line[1:-1].strip().lower(), {})
            continue
        if current is not None and "=" in line:
            key, value = line.split("=", 1)
            current[key.strip().lower()] = value.strip()
    interface = sections.get("interface")
    peer = sections.get("peer")
    if not interface or not peer:
        raise ValueError("invalid WireGuard configuration")
    endpoint = peer.get("endpoint", "")
    parsed = urlparse(f"wg://{endpoint}")
    if not parsed.hostname or not parsed.port:
        raise ValueError("invalid WireGuard peer endpoint")
    return {
        "scheme": "wireguard", "protocol": "WireGuard",
        "host": _validate_hostname(parsed.hostname), "port": parsed.port,
        "network": "udp", "security": "none",
        "address": interface.get("address", ""),
        "allowed_ips": peer.get("allowedips", ""),
        "credential_present": bool(interface.get("privatekey")),
        "public_key_present": bool(peer.get("publickey")),
    }


def parse_config(raw: str) -> dict[str, Any]:
    """Auto-detect VLESS, VMess, Trojan, Shadowsocks, Hysteria2 or WireGuard."""
    value = raw.strip()
    if not value:
        raise ValueError("configuration is empty")
    if value.startswith("[") and "[interface]" in value.lower():
        return parse_wireguard_config(value)
    parsed = urlparse(value)
    scheme = parsed.scheme.lower()
    if scheme not in SUPPORTED_SCHEMES:
        raise ValueError(
            "unsupported configuration; use VLESS, VMess, Trojan, "
            "Shadowsocks, Hysteria2, or WireGuard"
        )
    if scheme == "vless":
        return _parse_vless(parsed)
    if scheme == "vmess":
        return _parse_vmess(value)
    if scheme == "trojan":
        return _parse_trojan(parsed)
    if scheme == "ss":
        return _parse_shadowsocks(parsed)
    return _parse_hysteria2(parsed)


def _safe_config(config: dict[str, Any]) -> dict[str, Any]:
    hidden = {"uuid", "credential_present", "private_key_present", "public_key_present"}
    return {key: value for key, value in config.items() if key not in hidden}


def _requested_alpn(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _tcp_probe(
    host: str,
    port: int,
    use_tls: bool,
    sni: str | None,
    alpn_protocols: list[str] | None = None,
) -> dict[str, Any]:
    total_started = time.perf_counter()
    dns_started = time.perf_counter()
    addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    dns_ms = (time.perf_counter() - dns_started) * 1000
    if not addresses:
        raise OSError("DNS returned no addresses")
    last_error: Exception | None = None
    for family, socktype, proto, _, sockaddr in addresses:
        sock = socket.socket(family, socktype, proto)
        sock.settimeout(SOCKET_TIMEOUT)
        try:
            started = time.perf_counter()
            sock.connect(sockaddr)
            tcp_ms = (time.perf_counter() - started) * 1000
            tls_ms = None
            tls_version = alpn = cipher = None
            if use_tls:
                context = ssl.create_default_context()
                if alpn_protocols:
                    context.set_alpn_protocols(alpn_protocols)
                started = time.perf_counter()
                tls_sock = context.wrap_socket(sock, server_hostname=sni or host)
                tls_ms = (time.perf_counter() - started) * 1000
                sock = tls_sock
                tls_version = tls_sock.version()
                alpn = tls_sock.selected_alpn_protocol()
                cipher_info = tls_sock.cipher()
                cipher = cipher_info[0] if cipher_info else None
            return {
                "status": "ok",
                "ip": sockaddr[0],
                "dns_ms": round(dns_ms, 1),
                "tcp_ms": round(tcp_ms, 1),
                "tls_ms": round(tls_ms, 1) if tls_ms is not None else None,
                "latency_ms": round(
                    (time.perf_counter() - total_started) * 1000, 1
                ),
                "tls_version": tls_version,
                "alpn": alpn,
                "cipher": cipher,
            }
        except Exception as exc:
            last_error = exc
        finally:
            try:
                sock.close()
            except OSError:
                pass
    raise last_error or OSError("connection failed")


async def diagnose_config(config: dict[str, Any]) -> dict[str, Any]:
    """Measure the supplied endpoint without establishing a proxy session."""
    network = config.get("network", "tcp")
    use_tls = config.get("security") in {"tls", "reality"}
    requested_alpn = _requested_alpn(config.get("alpn", ""))
    sni = config.get("sni") or config.get("host")
    if network in {"quic", "udp", "tcp/udp"}:
        try:
            started = time.perf_counter()
            addresses = await asyncio.to_thread(
                socket.getaddrinfo,
                config["host"],
                config["port"],
                type=socket.SOCK_DGRAM,
            )
            dns_ms = (time.perf_counter() - started) * 1000
            if not addresses:
                raise OSError("DNS returned no addresses")
            return {
                "config": _safe_config(config),
                "status": "resolved",
                "ip": addresses[0][4][0],
                "dns_ms": round(dns_ms, 1),
                "tcp_ms": None,
                "tls_ms": None,
                "latency_ms": round(dns_ms, 1),
                "tls_version": None,
                "alpn": None,
                "cipher": None,
                "transport_note": (
                    f"{config['protocol']} uses UDP/QUIC; TCP/TLS timing "
                    "is not a protocol success signal."
                ),
            }
        except Exception as exc:
            return {"config": _safe_config(config), "status": "failed", "error": str(exc)[:220]}
    try:
        result = await asyncio.to_thread(
            _tcp_probe,
            config["host"],
            config["port"],
            use_tls,
            sni,
            requested_alpn,
        )
        result["transport_note"] = (
            "Endpoint-level TCP/TLS diagnostic; "
            "no proxy session is established."
        )
        return {"config": _safe_config(config), **result}
    except Exception as exc:
        return {"config": _safe_config(config), "status": "failed", "error": str(exc)[:220]}


def parse_vless(uri: str) -> dict[str, Any]:
    config = parse_config(uri)
    if config["scheme"] != "vless":
        raise ValueError("configuration is not a VLESS link")
    return config


async def diagnose_vless(config: dict[str, Any]) -> dict[str, Any]:
    return await diagnose_config(config)

def _service_probe_sync(host: str, path: str) -> dict[str, Any]:
    """Measure one HTTPS endpoint from the scanner VPS."""
    total_started = time.perf_counter()

    dns_started = time.perf_counter()
    addresses = socket.getaddrinfo(
        host,
        DEFAULT_HTTPS_PORT,
        type=socket.SOCK_STREAM,
    )
    dns_ms = (time.perf_counter() - dns_started) * 1000

    if not addresses:
        raise OSError("DNS returned no addresses")

    last_error: Exception | None = None

    for family, socktype, proto, _, sockaddr in addresses:
        sock = socket.socket(family, socktype, proto)
        sock.settimeout(SOCKET_TIMEOUT)

        try:
            connect_started = time.perf_counter()
            sock.connect(sockaddr)
            tcp_ms = (time.perf_counter() - connect_started) * 1000

            context = ssl.create_default_context()
            context.set_alpn_protocols(["http/1.1"])

            tls_started = time.perf_counter()
            tls_sock = context.wrap_socket(sock, server_hostname=host)
            tls_ms = (time.perf_counter() - tls_started) * 1000
            sock = tls_sock

            request = (
                f"GET {path} HTTP/1.1\r\n"
                f"Host: {host}\r\n"
                "User-Agent: idontScanner/2.0\r\n"
                "Accept: */*\r\n"
                "Connection: close\r\n"
                "\r\n"
            ).encode("ascii")

            request_started = time.perf_counter()
            tls_sock.sendall(request)
            first_byte = tls_sock.recv(1)
            response_ms = (time.perf_counter() - request_started) * 1000

            if not first_byte:
                raise OSError("remote endpoint closed without a response")

            response_head = first_byte + tls_sock.recv(4095)
            first_line = response_head.split(b"\r\n", 1)[0].decode(
                "latin1",
                "replace",
            )
            parts = first_line.split()
            status_code = (
                int(parts[1])
                if len(parts) >= 2 and parts[1].isdigit()
                else None
            )

            cipher_info = tls_sock.cipher()
            return {
                "status": "ok",
                "ip": sockaddr[0],
                "dns_ms": round(dns_ms, 1),
                "tcp_ms": round(tcp_ms, 1),
                "tls_ms": round(tls_ms, 1),
                "response_ms": round(response_ms, 1),
                "latency_ms": round(
                    (time.perf_counter() - total_started) * 1000,
                    1,
                ),
                "http_status": status_code,
                "tls_version": tls_sock.version(),
                "alpn": tls_sock.selected_alpn_protocol(),
                "cipher": cipher_info[0] if cipher_info else None,
            }
        except Exception as exc:
            last_error = exc
        finally:
            try:
                sock.close()
            except OSError:
                pass

    raise last_error or OSError("service connection failed")


async def _probe_service_repeated(
    host: str,
    path: str,
    attempts: int = SERVICE_ATTEMPTS,
) -> dict[str, Any]:
    """Run repeated endpoint probes and summarize their timing."""
    results = await asyncio.gather(
        *(
            asyncio.to_thread(_service_probe_sync, host, path)
            for _ in range(attempts)
        ),
        return_exceptions=True,
    )

    successful = [
        item
        for item in results
        if isinstance(item, dict) and item.get("status") == "ok"
    ]

    if not successful:
        errors = [
            str(item)
            for item in results
            if isinstance(item, Exception)
        ]
        return {
            "status": "failed",
            "latency_ms": None,
            "error": errors[0][:220] if errors else "service probe failed",
        }

    latencies = [float(item["latency_ms"]) for item in successful]
    response_times = [float(item["response_ms"]) for item in successful]
    minimum = min(latencies)
    maximum = max(latencies)
    average = sum(latencies) / len(latencies)

    deltas = [
        abs(current - previous)
        for previous, current in zip(latencies, latencies[1:])
    ]
    jitter = sum(deltas) / len(deltas) if deltas else 0.0

    selected = successful[0]
    return {
        "status": "ok",
        "ip": selected.get("ip"),
        "dns_ms": selected.get("dns_ms"),
        "tcp_ms": selected.get("tcp_ms"),
        "tls_ms": selected.get("tls_ms"),
        "latency_ms": round(average, 1),
        "min_ms": round(minimum, 1),
        "max_ms": round(maximum, 1),
        "jitter_ms": round(jitter, 1),
        "response_ms": round(
            sum(response_times) / len(response_times),
            1,
        ),
        "http_status": selected.get("http_status"),
        "tls_version": selected.get("tls_version"),
        "alpn": selected.get("alpn"),
        "cipher": selected.get("cipher"),
        "attempts": len(successful),
    }


async def probe_services() -> dict[str, dict[str, Any]]:
    """Probe all configured service endpoints concurrently."""
    endpoints = list(SERVICE_ENDPOINTS.items())
    results = await asyncio.gather(
        *(
            _probe_service_repeated(host, path)
            for _, (host, path) in endpoints
        )
    )
    return {
        name: result
        for (name, _), result in zip(endpoints, results)
    }
