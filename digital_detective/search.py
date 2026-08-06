"""Public-source search providers and cross-referencing logic."""

from __future__ import annotations

import ipaddress
import os
import re
from typing import Any
from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup

from .http_client import DataSourceError, HttpClient


NOT_FOUND = "Not found in public sources"


def _clean(value: Any) -> str:
    return str(value).strip() if value not in (None, "") else NOT_FOUND


def _claim_values(entity: dict[str, Any], property_id: str) -> list[str]:
    values: list[str] = []
    for claim in entity.get("claims", {}).get(property_id, []):
        value = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
        if isinstance(value, str) and value.strip():
            values.append(value.strip())
        elif isinstance(value, dict) and value.get("text"):
            values.append(str(value["text"]).strip())
    return list(dict.fromkeys(values))


class SearchService:
    PLATFORMS = {
        "GitHub": {"profile": "https://github.com/{username}", "probe": "https://api.github.com/users/{username}", "mode": "json-object"},
        "GitLab": {"profile": "https://gitlab.com/{username}", "probe": "https://gitlab.com/api/v4/users?username={username}", "mode": "json-list"},
        "Reddit": {"profile": "https://www.reddit.com/user/{username}/", "missing": ("page not found", "nobody on reddit goes by that name")},
        "Instagram": {"profile": "https://www.instagram.com/{username}/", "missing": ("page isn't available", "page is not available")},
        "X": {"profile": "https://x.com/{username}", "missing": ("this account doesn’t exist", "this account doesn't exist")},
        "TikTok": {"profile": "https://www.tiktok.com/@{username}", "missing": ("couldn't find this account", "couldn’t find this account")},
        "Facebook": {"profile": "https://www.facebook.com/{username}", "missing": ("this content isn't available", "page not found")},
        "Twitch": {"profile": "https://www.twitch.tv/{username}", "missing": ("unless you've got a time machine", "content is unavailable")},
        "Pinterest": {"profile": "https://www.pinterest.com/{username}/", "missing": ("profile not found", "couldn't find that page")},
        "Steam": {"profile": "https://steamcommunity.com/id/{username}", "missing": ("the specified profile could not be found",)},
    }

    def __init__(self, client: HttpClient) -> None:
        self.client = client

    def search_ip(self, raw_ip: str) -> dict[str, Any]:
        try:
            ip = str(ipaddress.ip_address(raw_ip.strip()))
        except ValueError as exc:
            raise ValueError(f"Invalid IP address: {raw_ip}") from exc

        first_url = os.getenv("IPWHOIS_API_URL", "https://ipwho.is/{ip}").format(ip=quote(ip, safe=""))
        second_url = os.getenv("IPAPI_API_URL", "https://ipapi.co/{ip}/json/").format(ip=quote(ip, safe=""))
        errors: list[str] = []
        providers: list[dict[str, str]] = []

        try:
            data = self.client.get_json(first_url)
            if data.get("success") is False:
                raise DataSourceError(str(data.get("message", "IPWhoIs returned no data")))
            connection = data.get("connection") or {}
            providers.append({
                "source": "IPWhoIs",
                "country_code": _clean(data.get("country_code")),
                "country": _clean(data.get("country")),
                "region": _clean(data.get("region")),
                "city": _clean(data.get("city")),
                "latitude": _clean(data.get("latitude")),
                "longitude": _clean(data.get("longitude")),
                "isp": _clean(connection.get("isp") or connection.get("org")),
            })
        except DataSourceError as exc:
            errors.append(f"IPWhoIs: {exc}")

        try:
            data = self.client.get_json(second_url)
            if data.get("error"):
                raise DataSourceError(str(data.get("message") or data.get("reason") or "ipapi returned no data"))
            providers.append({
                "source": "ipapi",
                "country_code": _clean(data.get("country_code")),
                "country": _clean(data.get("country_name")),
                "region": _clean(data.get("region")),
                "city": _clean(data.get("city")),
                "latitude": _clean(data.get("latitude")),
                "longitude": _clean(data.get("longitude")),
                "isp": _clean(data.get("org")),
            })
        except DataSourceError as exc:
            errors.append(f"ipapi: {exc}")

        if not providers:
            raise DataSourceError("; ".join(errors))

        primary = providers[0]
        country_agrees = len(providers) == 2 and providers[0]["country_code"].casefold() == providers[1]["country_code"].casefold()
        isp_agrees = len(providers) == 2 and self._organizations_match(providers[0]["isp"], providers[1]["isp"])
        confidence = "high" if country_agrees and isp_agrees else "medium" if country_agrees else "single-source"
        return {
            "type": "IP",
            "query": ip,
            "location": ", ".join(v for v in (primary["city"], primary["region"], primary["country"]) if v != NOT_FOUND),
            "coordinates": f'{primary["latitude"]}, {primary["longitude"]}',
            "isp": primary["isp"],
            "cross_reference": f"country={'match' if country_agrees else 'not confirmed'}, ISP={'match' if isp_agrees else 'not confirmed'}",
            "confidence": confidence,
            "providers": providers,
            "errors": errors,
        }

    @staticmethod
    def _organizations_match(left: str, right: str) -> bool:
        normalize = lambda value: set(re.findall(r"[a-z0-9]+", value.casefold())) - {"llc", "ltd", "inc", "corporation", "company"}
        a, b = normalize(left), normalize(right)
        return bool(a and b and (a <= b or b <= a or bool(a & b)))

    def search_name(self, name: str) -> dict[str, Any]:
        name = " ".join(name.split())
        if len(name.split()) < 2 or not re.fullmatch(r"[^\d<>]{3,100}", name):
            raise ValueError("Full name must contain at least two words and no digits")

        api_url = os.getenv("WIKIDATA_API_URL", "https://www.wikidata.org/w/api.php")
        search_data = self.client.get_json(api_url, params={
            "action": "wbsearchentities", "search": name, "language": "en", "uselang": "en", "type": "item", "limit": 5, "format": "json",
        })
        matches = search_data.get("search") or []
        if not matches:
            return self._empty_name_result(name, ["Wikidata returned no matching entity"])

        best = next((item for item in matches if str(item.get("label", "")).casefold() == name.casefold()), matches[0])
        entity_id = str(best.get("id", ""))
        entity_data = self.client.get_json(api_url, params={
            "action": "wbgetentities", "ids": entity_id, "props": "claims|labels|descriptions|sitelinks", "languages": "en", "format": "json",
        })
        entity = (entity_data.get("entities") or {}).get(entity_id, {})
        phones = _claim_values(entity, "P1329")
        addresses = _claim_values(entity, "P6375")
        websites = _claim_values(entity, "P856")
        scraped_from: list[str] = []
        scrape_errors: list[str] = []

        for website in websites[:1]:
            try:
                response = self.client.get(website, allow_redirects=True)
                found_addresses, found_phones = self._scrape_contact_details(response.text, response.url)
                addresses.extend(found_addresses)
                phones.extend(found_phones)
                scraped_from.append(response.url)
            except DataSourceError as exc:
                scrape_errors.append(str(exc))

        addresses = list(dict.fromkeys(addresses))
        phones = list(dict.fromkeys(phones))
        label = entity.get("labels", {}).get("en", {}).get("value") or best.get("label") or name
        return {
            "type": "Full Name",
            "query": name,
            "matched_entity": f"{label} ({entity_id})",
            "address": "; ".join(addresses) if addresses else NOT_FOUND,
            "phone_number": "; ".join(phones) if phones else NOT_FOUND,
            "confidence": "high" if str(label).casefold() == name.casefold() and (addresses or phones) else "low",
            "sources": [f"https://www.wikidata.org/wiki/{entity_id}", *scraped_from],
            "errors": scrape_errors,
        }

    @staticmethod
    def _empty_name_result(name: str, errors: list[str]) -> dict[str, Any]:
        return {"type": "Full Name", "query": name, "matched_entity": NOT_FOUND, "address": NOT_FOUND, "phone_number": NOT_FOUND, "confidence": "none", "sources": [], "errors": errors}

    @staticmethod
    def _scrape_contact_details(html: str, base_url: str) -> tuple[list[str], list[str]]:
        """Extract explicitly published contact details from an official page."""
        soup = BeautifulSoup(html, "html.parser")
        addresses: list[str] = []
        phones: list[str] = []
        for node in soup.select("address, [itemprop='address']"):
            text = " ".join(node.get_text(" ", strip=True).split())
            if 5 <= len(text) <= 300:
                addresses.append(text)
        for link in soup.select("a[href^='tel:']"):
            value = link.get("href", "")[4:].strip()
            if value:
                phones.append(value)
        return list(dict.fromkeys(addresses)), list(dict.fromkeys(phones))

    def search_username(self, username: str) -> dict[str, Any]:
        username = username.strip().lstrip("@")
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,50}", username):
            raise ValueError("Username may contain only letters, digits, dot, underscore and hyphen")

        platforms: list[dict[str, str]] = []
        errors: list[str] = []
        encoded = quote(username, safe="._-")
        for platform, settings in self.PLATFORMS.items():
            url = settings["profile"].format(username=encoded)
            probe = settings.get("probe", settings["profile"]).format(username=encoded)
            try:
                response = self.client.get(probe, allow_redirects=True)
                mode = settings.get("mode", "html")
                if mode == "json-object":
                    payload = response.json()
                    exists = isinstance(payload, dict) and str(payload.get("login", "")).casefold() == username.casefold()
                    method = "public API exact username match"
                elif mode == "json-list":
                    payload = response.json()
                    exists = isinstance(payload, list) and any(str(item.get("username", "")).casefold() == username.casefold() for item in payload if isinstance(item, dict))
                    method = "public API exact username match"
                else:
                    text = response.text[:500_000].casefold()
                    exists = not any(marker in text for marker in settings.get("missing", ()))
                    method = "HTTP status + public not-found marker"
                platforms.append({"platform": platform, "exists": "yes" if exists else "no", "url": url, "method": method})
            except DataSourceError as exc:
                message = str(exc)
                if "404" in message:
                    platforms.append({"platform": platform, "exists": "no", "url": url, "method": "HTTP 404"})
                else:
                    platforms.append({"platform": platform, "exists": "unknown", "url": url, "method": "request blocked or unavailable"})
                    errors.append(f"{platform}: {message}")
            except ValueError:
                platforms.append({"platform": platform, "exists": "unknown", "url": url, "method": "invalid API response"})
                errors.append(f"{platform}: invalid API response")
        return {"type": "Username", "query": f"@{username}", "platforms": platforms, "confidence": "platform-response", "errors": errors}
