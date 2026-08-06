"""Stable terminal rendering and collision-safe report storage."""

from __future__ import annotations

import json
import re
import unicodedata
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


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
                f"Identity: {result.get('identity_description', 'Not found')}",
                f"Identity status: {result.get('identity_status', 'unknown')}",
                f"Address: {result['address']}",
                f"Address type: {result.get('address_type', 'Not found')}",
                f"Phone Number: {result['phone_number']}",
                f"Phone type: {result.get('phone_type', 'Not found')}",
                f"Contact verification: {result.get('contact_verification', 'unavailable')}",
                f"Confidence: {result['confidence']}",
            ])
            for candidate in result.get("candidates", []):
                lines.append(f"Candidate: {candidate['label']} ({candidate['id']}) — {candidate['description']}")
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
                method = platform.get("method", "validation method unavailable")
                lines.append(f"{platform['platform']}: {platform['exists']} ({platform['url']}) — {method}")
            lines.append(f"Validation: {result['confidence']}")
        lines.extend(f"Warning: {error}" for error in result.get("errors", []))
    return "\n".join(lines) + "\n"


def _value(value: Any, fallback: str = "Not found") -> str:
    return escape(str(value if value not in (None, "") else fallback))


def _link(url: Any, label: Any | None = None) -> str:
    raw_url = str(url or "")
    parsed = urlsplit(raw_url)
    safe_label = _value(label if label is not None else raw_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return safe_label
    return f'<a href="{escape(raw_url, quote=True)}" target="_blank" rel="noopener noreferrer">{safe_label}</a>'


def _row(label: str, value: Any) -> str:
    return f"<tr><th>{escape(label)}</th><td>{_value(value)}</td></tr>"


def _name_visualization(result: dict[str, Any]) -> str:
    rows = [
        _row("Matched entity", result.get("matched_entity")),
        _row("Identity", result.get("identity_description")),
        _row("Identity status", result.get("identity_status")),
        _row("Address", result.get("address")),
        _row("Address type", result.get("address_type")),
        _row("Phone number", result.get("phone_number")),
        _row("Phone type", result.get("phone_type")),
        _row("Contact verification", result.get("contact_verification")),
    ]
    sources = "".join(f"<li>{_link(source)}</li>" for source in result.get("sources", []))
    source_block = f'<h3>Verification sources</h3><ul class="sources">{sources}</ul>' if sources else ""
    return f'<div class="table-wrap"><table>{"".join(rows)}</table></div>{source_block}'


def _ip_visualization(result: dict[str, Any]) -> str:
    summary = "".join([
        _row("Location", result.get("location")),
        _row("Coordinates", result.get("coordinates")),
        _row("ISP", result.get("isp")),
        _row("Cross-reference", result.get("cross_reference")),
    ])
    providers = result.get("providers", [])
    provider_rows = "".join(
        "<tr>"
        f"<td>{_value(provider.get('source'))}</td>"
        f"<td>{_value(provider.get('city'))}</td>"
        f"<td>{_value(provider.get('country'))}</td>"
        f"<td>{_value(provider.get('isp'))}</td>"
        "</tr>"
        for provider in providers
    )
    provider_table = ""
    if providers:
        provider_table = (
            '<h3>Provider comparison</h3><div class="table-wrap"><table>'
            '<thead><tr><th>Source</th><th>City</th><th>Country</th><th>ISP</th></tr></thead>'
            f"<tbody>{provider_rows}</tbody></table></div>"
        )
    return f'<div class="table-wrap"><table>{summary}</table></div>{provider_table}'


def _username_visualization(result: dict[str, Any]) -> str:
    platforms = result.get("platforms", [])
    counts = {status: sum(item.get("exists") == status for item in platforms) for status in ("yes", "no", "unknown")}
    total = max(len(platforms), 1)
    legend = "".join(
        f'<div class="metric {status}"><strong>{counts[status]}</strong><span>{status.title()}</span></div>'
        for status in ("yes", "no", "unknown")
    )
    bars = "".join(
        f'<span class="bar-{status}" style="width:{counts[status] / total * 100:.2f}%" title="{status}: {counts[status]}"></span>'
        for status in ("yes", "no", "unknown")
        if counts[status]
    )
    rows = "".join(
        "<tr>"
        f"<td>{_value(item.get('platform'))}</td>"
        f'<td><span class="status status-{escape(str(item.get("exists", "unknown")))}">{_value(item.get("exists", "unknown"))}</span></td>'
        f"<td>{_link(item.get('url'), 'Open profile')}</td>"
        f"<td>{_value(item.get('method'), 'Unavailable')}</td>"
        "</tr>"
        for item in platforms
    )
    return (
        f'<div class="metrics">{legend}</div><div class="status-bar" aria-label="Platform result summary">{bars}</div>'
        '<div class="table-wrap"><table><thead><tr><th>Platform</th><th>Status</th><th>Profile</th><th>Validation</th></tr></thead>'
        f"<tbody>{rows}</tbody></table></div>"
    )


def render_html_report(results: list[dict[str, Any]]) -> str:
    """Render a self-contained visual dashboard for every search type."""
    panels: list[str] = []
    errors_count = sum(len(result.get("errors", [])) for result in results)
    for result in results:
        result_type = str(result.get("type", "Search"))
        if result_type == "Full Name":
            visualization = _name_visualization(result)
        elif result_type == "IP":
            visualization = _ip_visualization(result)
        else:
            visualization = _username_visualization(result)
        errors = "".join(f"<li>{_value(error)}</li>" for error in result.get("errors", []))
        error_block = f'<div class="warnings"><strong>Warnings</strong><ul>{errors}</ul></div>' if errors else ""
        confidence = str(result.get("confidence", "unknown"))
        panels.append(
            '<section class="panel">'
            '<div class="panel-heading">'
            f'<div><span class="type">{_value(result_type)}</span><h2>{_value(result.get("query"))}</h2></div>'
            f'<span class="confidence">Confidence: {_value(confidence)}</span>'
            "</div>"
            f"{visualization}{error_block}</section>"
        )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Digital Detective Report</title>
  <style>
    :root {{ color-scheme: light; --ink:#172033; --muted:#667085; --line:#dfe4ec; --surface:#fff; --page:#f4f7fb; --accent:#4f46e5; --yes:#16845b; --no:#c2414b; --unknown:#b7791f; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:var(--page); color:var(--ink); font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif; }}
    main {{ width:min(1100px,calc(100% - 32px)); margin:40px auto; }}
    header {{ margin-bottom:24px; }}
    h1 {{ margin:0; font-size:clamp(28px,5vw,44px); }}
    h2 {{ margin:4px 0 0; font-size:22px; overflow-wrap:anywhere; }}
    h3 {{ margin:24px 0 10px; font-size:16px; }}
    .subtitle {{ color:var(--muted); margin:6px 0 18px; }}
    .overview,.metrics {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; }}
    .overview div,.metric {{ background:var(--surface); border:1px solid var(--line); border-radius:12px; padding:14px 16px; }}
    .overview strong,.metric strong {{ display:block; font-size:24px; }}
    .overview span,.metric span {{ color:var(--muted); }}
    .panel {{ background:var(--surface); border:1px solid var(--line); border-radius:16px; padding:22px; margin:18px 0; box-shadow:0 8px 24px rgba(23,32,51,.05); }}
    .panel-heading {{ display:flex; align-items:flex-start; justify-content:space-between; gap:16px; margin-bottom:18px; }}
    .type {{ color:var(--accent); font-size:12px; font-weight:700; letter-spacing:.08em; text-transform:uppercase; }}
    .confidence {{ background:#eef2ff; color:#3730a3; border-radius:999px; padding:6px 10px; white-space:nowrap; }}
    .table-wrap {{ overflow-x:auto; }}
    table {{ width:100%; border-collapse:collapse; }}
    th,td {{ border-bottom:1px solid var(--line); padding:11px 10px; text-align:left; vertical-align:top; white-space:pre-line; }}
    th {{ color:var(--muted); font-weight:600; }}
    tbody th {{ width:210px; }}
    a {{ color:#3730a3; }}
    .sources {{ padding-left:20px; overflow-wrap:anywhere; }}
    .status-bar {{ display:flex; height:12px; overflow:hidden; background:#e5e7eb; border-radius:999px; margin:14px 0 22px; }}
    .bar-yes {{ background:var(--yes); }} .bar-no {{ background:var(--no); }} .bar-unknown {{ background:var(--unknown); }}
    .metric.yes strong,.status-yes {{ color:var(--yes); }} .metric.no strong,.status-no {{ color:var(--no); }} .metric.unknown strong,.status-unknown {{ color:var(--unknown); }}
    .status {{ font-weight:700; text-transform:uppercase; }}
    .warnings {{ margin-top:18px; padding:12px 16px; background:#fff7ed; border-left:4px solid #ea580c; border-radius:8px; }}
    .warnings ul {{ margin:6px 0 0; padding-left:20px; }}
    footer {{ color:var(--muted); text-align:center; margin-top:26px; }}
    @media (max-width:650px) {{ .overview,.metrics {{ grid-template-columns:1fr; }} .panel-heading {{ display:block; }} .confidence {{ display:inline-block; margin-top:10px; }} .panel {{ padding:16px; }} }}
  </style>
</head>
<body>
  <main>
    <header>
      <h1>Digital Detective</h1>
      <p class="subtitle">Visual OSINT report generated from public sources</p>
      <div class="overview">
        <div><strong>{len(results)}</strong><span>Searches</span></div>
        <div><strong>{sum(1 for result in results if result.get('confidence') not in ('none', None))}</strong><span>Results with confidence</span></div>
        <div><strong>{errors_count}</strong><span>Warnings</span></div>
      </div>
    </header>
    {''.join(panels)}
    <footer>Educational project · Verify live data at the linked public sources</footer>
  </main>
</body>
</html>
"""


def save_report(
    directory: Path,
    stem: str,
    results: list[dict[str, Any]],
    save_json: bool = False,
    save_html: bool = False,
) -> tuple[Path, Path | None, Path | None]:
    text_path = available_path(directory, stem)
    text_path.write_text(render_report(results), encoding="utf-8")
    json_path = None
    html_path = None
    if save_json:
        json_path = text_path.with_suffix(".json")
        json_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    if save_html:
        html_path = text_path.with_suffix(".html")
        html_path.write_text(render_html_report(results), encoding="utf-8")
    return text_path, json_path, html_path
