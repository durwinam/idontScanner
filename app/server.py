"""Reliable Uvicorn launcher with automatic HTTP port selection."""

from __future__ import annotations

import os
import socket
from pathlib import Path

import uvicorn

from app.main import app

DEFAULT_PORT = 8088
MIN_PORT = 1024
MAX_PORT = 65535
RUNTIME_PORT_FILE = Path("/var/lib/idontscanner/runtime-port")
ENV_FILE = Path("/opt/idontScanner/.env")


def _valid_port(value: str | None) -> int:
    try:
        port = int(value or DEFAULT_PORT)
    except (TypeError, ValueError):
        return DEFAULT_PORT

    if not MIN_PORT <= port <= MAX_PORT:
        return DEFAULT_PORT
    return port


def _port_is_available(port: int) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("0.0.0.0", port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def _select_port(preferred: int) -> int:
    for port in range(preferred, MAX_PORT + 1):
        if _port_is_available(port):
            return port
    raise RuntimeError("No free TCP port is available between 1024 and 65535.")


def _persist_runtime_port(port: int) -> None:
    try:
        RUNTIME_PORT_FILE.parent.mkdir(parents=True, exist_ok=True)
        RUNTIME_PORT_FILE.write_text(f"{port}\n", encoding="utf-8")
    except OSError:
        pass

    # Keep the preferred port aligned with the actual runtime port so a later
    # restart/update continues using the port selected after a collision.
    try:
        if ENV_FILE.exists():
            lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
            replaced = False
            output = []
            for line in lines:
                if line.startswith("IDONTSCANNER_PORT="):
                    output.append(f"IDONTSCANNER_PORT={port}")
                    replaced = True
                else:
                    output.append(line)
            if not replaced:
                output.append(f"IDONTSCANNER_PORT={port}")
            ENV_FILE.write_text("\n".join(output) + "\n", encoding="utf-8")
        os.environ["IDONTSCANNER_PORT"] = str(port)
    except OSError:
        pass


def main() -> None:
    preferred = _valid_port(os.getenv("IDONTSCANNER_PORT"))
    port = _select_port(preferred)

    if port != preferred:
        print(
            f"[idontScanner] TCP/{preferred} is unavailable; "
            f"using TCP/{port} instead.",
            flush=True,
        )

    _persist_runtime_port(port)

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
