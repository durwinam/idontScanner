"""Server-side Check-Host API integration for global diagnostics."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import re
import socket
import time
import urllib.parse
import urllib.request
from typing import Any

API_BASE = "https://check-host.net"
USER_AGENT = "idontScanner-CheckHost/3.0.6"
MAX_NODES = 15
IRAN_NODES = (
    "ir1.node.check-host.net",
    "ir2.node.check-host.net",
    "ir3.node.check-host.net",
    "ir4.node.check-host.net",
    "ir5.node.check-host.net",
    "ir7.node.check-host.net",
)
REQUEST_TIMEOUT = 12.0
RESULT_TIMEOUT = 30.0
REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def validate_target(value: str) -> str:
    target = value.strip()
    if not target or len(target) > 253:
        raise ValueError("Hostname or IP address is required.")

    if any(char in target for char in "\r\n"):  # prevent header/query injection
        raise ValueError("Invalid target.")

    if target.startswith(("http://", "https://")):
        parsed = urllib.parse.urlparse(target)
        if not parsed.hostname:
            raise ValueError("Invalid URL.")
        return target

    try:
        ipaddress.ip_address(target)
        return target
    except ValueError:
        pass

    labels = target.rstrip(".").split(".")
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")
    if any(
        not label
        or len(label) > 63
        or label.startswith("-")
        or label.endswith("-")
        or any(char not in allowed for char in label)
        for label in labels
    ):
        raise ValueError("Invalid hostname or IP address.")
    return target.rstrip(".")


def validate_check_host(value: str) -> str:
    value = value.strip()
    if not value or len(value) > 320 or any(char in value for char in "\r\n"):
        raise ValueError("Invalid check target.")
    return value


def _request_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        payload = response.read(1_500_000)
    data = json.loads(payload.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Check-Host returned an invalid response.")
    return data


async def start_check(
    check_type: str,
    target: str,
    max_nodes: int = MAX_NODES,
    nodes: list[str] | None = None,
) -> dict[str, Any]:
    if check_type not in {"ping", "http", "tcp", "udp", "dns"}:
        raise ValueError("Unsupported check type.")

    target = validate_check_host(target)
    max_nodes = max(1, min(int(max_nodes), MAX_NODES))
    query_items: list[tuple[str, str]] = [("host", target)]

    if nodes:
        selected = [node for node in nodes if node in IRAN_NODES]
        if not selected:
            raise ValueError("No valid Check-Host nodes were selected.")
        query_items.extend(("node", node) for node in selected[:MAX_NODES])
    else:
        query_items.append(("max_nodes", str(max_nodes)))

    query = urllib.parse.urlencode(query_items)
    data = await asyncio.to_thread(_request_json, f"{API_BASE}/check-{check_type}?{query}")

    if not data.get("ok") or not data.get("request_id"):
        raise RuntimeError("Check-Host could not start the requested check.")

    nodes = data.get("nodes") or {}
    normalized_nodes = {}
    for node_id, meta in nodes.items():
        normalized_nodes[node_id] = {
            "id": node_id,
            "country_code": meta[0] if len(meta) > 0 else "",
            "country": meta[1] if len(meta) > 1 else "",
            "city": meta[2] if len(meta) > 2 else "",
            "ip": meta[3] if len(meta) > 3 else "",
            "asn": meta[4] if len(meta) > 4 else "",
        }

    return {
        "request_id": str(data["request_id"]),
        "permanent_link": data.get("permanent_link"),
        "nodes": normalized_nodes,
        "check_type": check_type,
        "target": target,
        "node_group": "iran" if nodes else "global",
    }


async def fetch_result(request_id: str) -> dict[str, Any]:
    if not REQUEST_ID_RE.fullmatch(request_id):
        raise ValueError("Invalid request id.")
    return await asyncio.to_thread(
        _request_json,
        f"{API_BASE}/check-result/{request_id}",
    )


def _node_status(check_type: str, raw: Any) -> dict[str, Any]:
    if raw is None:
        return {"status": "pending"}

    try:
        if check_type == "ping":
            packets = raw[0] if raw and isinstance(raw[0], list) else []
            successful = [item for item in packets if isinstance(item, list) and item and item[0] == "OK"]
            times = [float(item[1]) * 1000 for item in successful if len(item) > 1]
            total = len(packets)
            return {
                "status": "online" if successful else "failed",
                "success": len(successful),
                "total": total,
                "loss_percent": round((1 - len(successful) / total) * 100, 1) if total else 100.0,
                "min_ms": round(min(times), 1) if times else None,
                "avg_ms": round(sum(times) / len(times), 1) if times else None,
                "max_ms": round(max(times), 1) if times else None,
                "ip": next((item[2] for item in successful if len(item) > 2), None),
            }

        item = raw[0] if isinstance(raw, list) and raw else raw
        if check_type == "http":
            return {
                "status": "online" if isinstance(item, list) and item and item[0] == 1 else "failed",
                "latency_ms": round(float(item[1]) * 1000, 1) if isinstance(item, list) and len(item) > 1 and item[1] is not None else None,
                "message": item[2] if isinstance(item, list) and len(item) > 2 else None,
                "http_status": item[3] if isinstance(item, list) and len(item) > 3 else None,
                "ip": item[4] if isinstance(item, list) and len(item) > 4 else None,
            }

        if check_type == "tcp":
            if isinstance(item, dict) and item.get("time") is not None:
                return {
                    "status": "online",
                    "latency_ms": round(float(item["time"]) * 1000, 1),
                    "ip": item.get("address"),
                }
            return {"status": "failed", "error": item.get("error") if isinstance(item, dict) else "Connection failed"}

        if check_type == "udp":
            if isinstance(item, dict):
                return {
                    "status": "online" if item.get("time") is not None else "unknown",
                    "latency_ms": round(float(item["time"]) * 1000, 1) if item.get("time") is not None else None,
                    "ip": item.get("address"),
                    "error": item.get("error"),
                }
            return {"status": "unknown", "error": "No UDP response"}

        if check_type == "dns":
            record = item if isinstance(item, dict) else {}
            return {
                "status": "online" if record.get("A") or record.get("AAAA") else "failed",
                "a": record.get("A") or [],
                "aaaa": record.get("AAAA") or [],
                "ttl": record.get("TTL"),
            }
    except (TypeError, ValueError, IndexError):
        return {"status": "failed", "error": "Malformed node result"}

    return {"status": "failed", "error": "Unknown result"}


def normalize_results(check_type: str, raw: dict[str, Any], nodes: dict[str, Any]) -> dict[str, Any]:
    results = []
    for node_id, meta in nodes.items():
        parsed = _node_status(check_type, raw.get(node_id))
        results.append({**meta, **parsed})

    completed = [item for item in results if item["status"] != "pending"]
    online = [item for item in completed if item["status"] == "online"]
    latency_values = [
        item.get("avg_ms", item.get("latency_ms"))
        for item in online
        if item.get("avg_ms", item.get("latency_ms")) is not None
    ]
    return {
        "results": results,
        "complete": len(completed) == len(results) if results else True,
        "completed": len(completed),
        "online": len(online),
        "total": len(results),
        "average_ms": round(sum(latency_values) / len(latency_values), 1) if latency_values else None,
    }


def local_info(target: str) -> dict[str, Any]:
    target = validate_target(target)
    hostname = target
    if target.startswith(("http://", "https://")):
        hostname = urllib.parse.urlparse(target).hostname or target

    started = time.perf_counter()
    addresses = socket.getaddrinfo(hostname, None)
    dns_ms = (time.perf_counter() - started) * 1000
    ips = sorted({item[4][0] for item in addresses})
    reverse = []
    for ip in ips[:8]:
        try:
            reverse.append({"ip": ip, "ptr": socket.gethostbyaddr(ip)[0]})
        except (OSError, socket.herror):
            reverse.append({"ip": ip, "ptr": None})

    return {
        "target": target,
        "hostname": hostname,
        "ips": ips,
        "reverse_dns": reverse,
        "dns_ms": round(dns_ms, 1),
    }
