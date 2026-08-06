"""Stable terminal rendering and collision-safe report storage."""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any


def slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value.strip().lstrip("@")).casefold()
    normalized = re.sub(r"[^\w.-]+", "_", normalized, flags=re.UNICODE).strip("_.")
    return normalized or "search"


def report_stem(name: str | None, ip: str | None, username: str | None) -> str:
    prefixes = [prefix for prefix, value in (("n", name), ("ip", ip), ("un", username)) if value]
    if len(prefixes) == 1:
        value = name or ip or username or "search"
    elif name:
        value = name
    else:
        value = "_".join(value for value in (ip, username) if value)
    safe_value = slug(value)
    if ip and not name and (len(prefixes) == 1 or value.startswith(ip)):
        safe_value = safe_value.replace(".", "_")
    return f"{'_'.join(prefixes)}_{safe_value}"


def available_path(directory: Path, stem: str, suffix: str = ".txt") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    candidate = directory / f"{stem}{suffix}"
    number = 1
    while candidate.exists():
        candidate = directory / f"{stem}{number}{suffix}"
        number += 1
    return candidate


def render_report(results: list[dict[str, Any]]) -> str:
    lines = ["DIGITAL DETECTIVE REPORT", "=" * 24]
    for result in results:
        lines.extend(["", f"[{result['type']}]", f"Query: {result['query']}"])
        if result["type"] == "Full Name":
            lines.extend([
                f"Matched entity: {result['matched_entity']}",
                f"Address: {result['address']}",
                f"Phone Number: {result['phone_number']}",
                f"Confidence: {result['confidence']}",
            ])
            lines.extend(f"Source: {source}" for source in result.get("sources", []))
        elif result["type"] == "IP":
            lines.extend([
                f"Location: {result['location']}",
                f"Coordinates: {result['coordinates']}",
                f"ISP: {result['isp']}",
                f"Cross-reference: {result['cross_reference']}",
                f"Confidence: {result['confidence']}",
            ])
            for provider in result.get("providers", []):
                lines.append(f"Source {provider['source']}: {provider['city']}, {provider['country']} / {provider['isp']}")
        else:
            for platform in result.get("platforms", []):
                lines.append(f"{platform['platform']}: {platform['exists']} ({platform['url']})")
            lines.append(f"Validation: {result['confidence']}")
        lines.extend(f"Warning: {error}" for error in result.get("errors", []))
    return "\n".join(lines) + "\n"


def save_report(directory: Path, stem: str, results: list[dict[str, Any]], save_json: bool = False) -> tuple[Path, Path | None]:
    text_path = available_path(directory, stem)
    text_path.write_text(render_report(results), encoding="utf-8")
    json_path = None
    if save_json:
        json_path = text_path.with_suffix(".json")
        json_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    return text_path, json_path
