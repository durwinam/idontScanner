#!/usr/bin/env python3
"""Build the Find Target benchmark catalog using multiple public sources.

The installer must never fail only because an external ranking service is
unreachable.  We prefer the official Tranco ranking, then use other public
million-domain rankings as fallbacks.  The resulting file is always validated
before it replaces an existing catalog.
"""
from __future__ import annotations

import argparse
import csv
import io
import gzip
import json
import re
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from pathlib import Path

COUNT_DEFAULT = 3000
USER_AGENT = "idontScanner-target-catalog/4.3.0"

SOURCES = [
    # Prefer the official ranking, then GitHub mirrors/cache endpoints that
    # are often reachable when the original provider is blocked on a VPS.
    ("tranco", "https://tranco-list.eu/top-1m.csv.zip", "zip_rank_domain"),
    ("tranco_cache", "https://raw.githubusercontent.com/wangmm001/tranco-top1m-cache/main/data/current.csv.gz", "gzip_rank_domain"),
    ("umbrella", "https://s3-us-west-1.amazonaws.com/umbrella-static/top-1m.csv.zip", "zip_rank_domain"),
    ("majestic", "https://downloads.majestic.com/majestic_million.csv", "majestic_csv"),
    ("tranco_snapshot", "https://raw.githubusercontent.com/1xyz/tranco/main/data/tranco_top_5K.txt", "lines"),
]


def valid_domain(value: str) -> bool:
    value = value.strip().lower().rstrip(".")
    if not value or len(value) > 253 or "/" in value or ":" in value or "@" in value:
        return False
    labels = value.split(".")
    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789-")
    return (
        len(labels) >= 2
        and all(
            label
            and len(label) <= 63
            and not label.startswith("-")
            and not label.endswith("-")
            and all(c in allowed for c in label)
            for label in labels
        )
    )


def _unique(domains: list[str], count: int) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in domains:
        d = raw.strip().lower().rstrip(".")
        if valid_domain(d) and d not in seen:
            seen.add(d)
            out.append(d)
            if len(out) >= count:
                break
    return out


def _download_with_urllib(url: str, timeout: int, limit: int) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise RuntimeError(f"response exceeds {limit} bytes")
    return data


def _download_with_command(command: str, url: str, timeout: int, limit: int) -> bytes:
    if not shutil.which(command):
        raise RuntimeError(f"{command} is not installed")
    if command == "curl":
        args = [command, "-fsSL", "--retry", "2", "--connect-timeout", str(min(timeout, 15)), "--max-time", str(timeout), "-A", USER_AGENT, url]
    else:
        args = [command, "-q", "-O", "-", url]
    proc = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout + 5, check=False)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", "replace")[-300:])
    if len(proc.stdout) > limit:
        raise RuntimeError(f"response exceeds {limit} bytes")
    return proc.stdout


def download(url: str, timeout: int = 30, limit: int = 90_000_000) -> tuple[bytes, str]:
    errors: list[str] = []
    for method in ("curl", "wget", "urllib"):
        try:
            if method == "urllib":
                return _download_with_urllib(url, timeout, limit), method
            return _download_with_command(method, url, timeout, limit), method
        except Exception as exc:
            errors.append(f"{method}: {exc}")
    raise RuntimeError("; ".join(errors))


def parse_zip_rank_domain(blob: bytes, count: int) -> list[str]:
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        names = [n for n in archive.namelist() if not n.endswith("/")]
        csv_name = next((n for n in names if n.lower().endswith(".csv")), None)
        if not csv_name:
            raise RuntimeError("archive has no CSV")
        text = archive.read(csv_name).decode("utf-8", "replace")
    domains: list[str] = []
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 2:
            continue
        domains.append(row[1])
    return _unique(domains, count)


def parse_gzip_rank_domain(blob: bytes, count: int) -> list[str]:
    text = gzip.decompress(blob).decode("utf-8", "replace")
    domains: list[str] = []
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 2:
            continue
        domains.append(row[1])
    return _unique(domains, count)


def parse_majestic(blob: bytes, count: int) -> list[str]:
    text = blob.decode("utf-8", "replace")
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        return []
    normalized = [h.strip().lower() for h in header]
    domain_idx = next((i for i, h in enumerate(normalized) if h == "domain"), None)
    if domain_idx is None:
        domain_idx = 2
    domains: list[str] = []
    for row in reader:
        if len(row) > domain_idx:
            domains.append(row[domain_idx])
    return _unique(domains, count)


def parse_lines(blob: bytes, count: int) -> list[str]:
    return _unique(blob.decode("utf-8", "replace").splitlines(), count)


def parse(blob: bytes, parser: str, count: int) -> list[str]:
    if parser == "zip_rank_domain":
        return parse_zip_rank_domain(blob, count)
    if parser == "gzip_rank_domain":
        return parse_gzip_rank_domain(blob, count)
    if parser == "majestic_csv":
        return parse_majestic(blob, count)
    return parse_lines(blob, count)


def atomic_write(path: Path, domains: list[str], source: str, transport: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("\n".join(domains) + "\n", encoding="utf-8")
    if len([x for x in tmp.read_text(encoding="utf-8").splitlines() if valid_domain(x)]) < len(domains):
        tmp.unlink(missing_ok=True)
        raise RuntimeError("validation failed before catalog replacement")
    tmp.replace(path)
    meta = path.with_suffix(path.suffix + ".meta.json")
    meta.write_text(json.dumps({"count": len(domains), "source": source, "transport": transport}, indent=2), encoding="utf-8")


def fetch(count: int) -> tuple[list[str], str, str, list[str]]:
    """Build one catalog from the best available sources.

    A single ranking provider does not have to be reachable. Sources are
    accumulated until the requested count is reached, while preserving the
    order in which domains were discovered. This makes upgrades much more
    reliable on VPS networks where one ranking provider may be blocked.
    """
    failures: list[str] = []
    combined: list[str] = []
    seen: set[str] = set()
    successful_sources: list[str] = []
    transports: list[str] = []

    for source, url, parser in SOURCES:
        if len(combined) >= count:
            break
        try:
            blob, transport = download(url)
            domains = parse(blob, parser, count)
            added = 0
            for domain in domains:
                if domain not in seen:
                    seen.add(domain)
                    combined.append(domain)
                    added += 1
                    if len(combined) >= count:
                        break
            successful_sources.append(source)
            transports.append(transport)
            if added == 0:
                failures.append(f"{source}: no new domains")
        except Exception as exc:
            failures.append(f"{source}: {exc}")

    if len(combined) >= count:
        return combined[:count], "+".join(successful_sources), "+".join(transports), failures

    failures.append(f"combined catalog: only {len(combined)}/{count} unique valid domains")
    return [], "unavailable", "none", failures


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", required=True)
    ap.add_argument("--count", type=int, default=COUNT_DEFAULT)
    args = ap.parse_args()
    domains, source, transport, failures = fetch(args.count)
    if domains:
        atomic_write(Path(args.output), domains, source, transport)
        print(f"wrote {len(domains)} domains to {args.output} (source={source}, transport={transport})")
        if failures:
            print("fallback attempts before success:")
            for failure in failures:
                print(f"  - {failure}")
        return 0
    print("WARNING: could not prepare the 3,000-target catalog.", flush=True)
    for failure in failures:
        print(f"  - {failure}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
