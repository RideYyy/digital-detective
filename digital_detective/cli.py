"""Argument parsing and orchestration."""

from __future__ import annotations

import argparse
import ipaddress
import os
import re
from pathlib import Path
from typing import Sequence

from .http_client import DataSourceError, HttpClient
from .reports import render_report, report_stem, save_report
from .search import SearchService


def full_name_argument(value: str) -> str:
    value = " ".join(value.split())
    if len(value.split()) < 2 or not re.fullmatch(r"[^\d<>]{3,100}", value):
        raise argparse.ArgumentTypeError("full name must contain at least two words and no digits")
    return value


def ip_argument(value: str) -> str:
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid IP address: {value}") from exc


def username_argument(value: str) -> str:
    normalized = value.strip().lstrip("@")
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,50}", normalized):
        raise argparse.ArgumentTypeError("username may contain only letters, digits, dot, underscore and hyphen")
    return normalized


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="data_digger.py",
        description="Gather and cross-reference public OSINT data.",
        epilog=(
            "Educational use only. Use public information lawfully and verify results. "
            "At least one of -n, -ip or -un is required; options may be combined."
        ),
    )
    parser.add_argument("-n", "--name", type=full_name_argument, metavar="FULL_NAME", help="search a full name for publicly listed address and phone")
    parser.add_argument("-ip", "--ip", type=ip_argument, metavar="IP_ADDRESS", help="search an IPv4 or IPv6 address for location and ISP")
    parser.add_argument("-un", "--username", type=username_argument, metavar="USERNAME", help="check a username on ten popular platforms")
    parser.add_argument("--output-dir", type=Path, default=Path("reports"), help="report directory (default: reports)")
    parser.add_argument("--json", action="store_true", help="also save a structured JSON report")
    parser.add_argument("--version", action="version", version="Digital Detective 1.0.0")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not any((args.name, args.ip, args.username)):
        parser.error("at least one search option is required; use --help for usage")

    user_agent = os.getenv("DIGITAL_DETECTIVE_USER_AGENT", "DigitalDetective/1.0 (educational OSINT; contact: local-user)")
    service = SearchService(HttpClient(user_agent=user_agent))
    results = []
    failed = 0
    searches = (
        (args.name, service.search_name),
        (args.ip, service.search_ip),
        (args.username, service.search_username),
    )
    for value, search in searches:
        if value is None:
            continue
        try:
            results.append(search(value))
        except (ValueError, DataSourceError) as exc:
            failed += 1
            if search.__name__ == "search_name":
                result = {"type": "Full Name", "query": value, "matched_entity": "Not found", "address": "Not found", "phone_number": "Not found", "confidence": "none", "sources": []}
            elif search.__name__ == "search_ip":
                result = {"type": "IP", "query": value, "location": "Not found", "coordinates": "Not found", "isp": "Not found", "cross_reference": "unavailable", "confidence": "none", "providers": []}
            else:
                result = {"type": "Username", "query": value, "platforms": [], "confidence": "none"}
            result["errors"] = [str(exc)]
            results.append(result)

    rendered = render_report(results)
    print(rendered, end="")
    stem = report_stem(args.name, args.ip, args.username)
    text_path, json_path = save_report(args.output_dir, stem, results, args.json)
    print(f"Result written to file: {text_path}")
    if json_path:
        print(f"JSON written to file: {json_path}")
    return 1 if failed == len(results) else 0
