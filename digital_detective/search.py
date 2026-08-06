"""Public-source search providers and conservative validation logic."""

from __future__ import annotations

import ipaddress
import json
import os
import re
from typing import Any
from urllib.parse import quote, urljoin, urlsplit

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


def _claim_entity_ids(entity: dict[str, Any], property_id: str) -> set[str]:
    values: set[str] = set()
    for claim in entity.get("claims", {}).get(property_id, []):
        value = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
        if isinstance(value, dict) and value.get("id"):
            values.add(str(value["id"]))
    return values


class SearchService:
    """Search public sources without treating ambiguous responses as proof."""

    PLATFORMS: dict[str, dict[str, Any]] = {
        "GitHub": {
            "profile": "https://github.com/{username}",
            "probe": "https://api.github.com/users/{username}",
            "mode": "json-object",
        },
        "GitLab": {
            "profile": "https://gitlab.com/{username}",
            "probe": "https://gitlab.com/api/v4/users?username={username}",
            "mode": "json-list",
        },
        "Reddit": {
            "profile": "https://www.reddit.com/user/{username}/",
            "probe": "https://www.reddit.com/user/{username}/about.json",
            "mode": "reddit-json",
        },
        "Instagram": {
            "profile": "https://www.instagram.com/{username}/",
            "missing": ("page isn't available", "page is not available"),
            "blocked": ("challenge_required", "login • instagram", "log in to instagram"),
        },
        "X": {
            "profile": "https://x.com/{username}",
            "missing": ("this account doesn’t exist", "this account doesn't exist"),
            "blocked": ("javascript is not available", "log in to x", "sign up for x"),
        },
        "TikTok": {
            "profile": "https://www.tiktok.com/@{username}",
            "missing": ("couldn't find this account", "couldn’t find this account"),
            "blocked": ("verify to continue", "captcha", "access denied"),
        },
        "Facebook": {
            "profile": "https://www.facebook.com/{username}",
            "missing": ("this content isn't available", "page not found"),
            "blocked": ("log into facebook", "log in to facebook", "checkpoint"),
        },
        "Twitch": {
            "profile": "https://www.twitch.tv/{username}",
            "missing": ("unless you've got a time machine", "content is unavailable"),
            "blocked": ("access denied", "captcha"),
        },
        "Pinterest": {
            "profile": "https://www.pinterest.com/{username}/",
            "missing": ("profile not found", "couldn't find that page"),
            "blocked": ("log in to pinterest", "create an account"),
        },
        "Steam": {
            "profile": "https://steamcommunity.com/id/{username}",
            "probe": "https://steamcommunity.com/id/{username}?xml=1",
            "mode": "steam-xml",
        },
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

    def search_name(self, name: str, hint: str | None = None) -> dict[str, Any]:
        name = " ".join(name.split())
        hint = " ".join(hint.split()) if hint else None
        if len(name.split()) < 2 or not re.fullmatch(r"[^\d<>]{3,100}", name):
            raise ValueError("Full name must contain at least two words and no digits")

        api_url = os.getenv("WIKIDATA_API_URL", "https://www.wikidata.org/w/api.php")
        search_data = self.client.get_json(api_url, params={
            "action": "wbsearchentities",
            "search": name,
            "language": "en",
            "uselang": "en",
            "type": "item",
            "limit": 10,
            "format": "json",
        })
        matches = search_data.get("search") or []
        if not matches:
            return self._empty_name_result(name, ["Wikidata returned no matching entity"])

        search_candidates = [
            {
                "id": str(item.get("id", "")),
                "label": str(item.get("label", "")),
                "description": str(item.get("description", "")),
            }
            for item in matches
        ]
        exact = [item for item in matches if str(item.get("label", "")).casefold() == name.casefold()]
        if not exact:
            return self._ambiguous_name_result(name, search_candidates, "No exact identity match was found")

        exact_ids = "|".join(str(item.get("id", "")) for item in exact)
        entity_data = self.client.get_json(api_url, params={
            "action": "wbgetentities",
            "ids": exact_ids,
            "props": "claims|labels|descriptions|sitelinks",
            "languages": "en",
            "format": "json",
        })
        entities = entity_data.get("entities") or {}
        human_exact = [item for item in exact if "Q5" in _claim_entity_ids(entities.get(str(item.get("id", "")), {}), "P31")]
        candidates = [
            {
                "id": str(item.get("id", "")),
                "label": str(item.get("label", "")),
                "description": str(item.get("description", "")),
            }
            for item in human_exact
        ]
        best = self._select_name_candidate(human_exact, hint)
        if best is None:
            reason = "Multiple people share this name; use --name-hint to identify the intended person" if len(human_exact) > 1 else "No exact human identity match was found"
            return self._ambiguous_name_result(name, candidates, reason)

        entity_id = str(best.get("id", ""))
        entity = entities.get(entity_id, {})

        wikidata_phones = _claim_values(entity, "P1329")
        wikidata_addresses = _claim_values(entity, "P6375")
        websites = _claim_values(entity, "P856")
        website_addresses: list[str] = []
        website_phones: list[str] = []
        scraped_from: list[str] = []
        scrape_errors: list[str] = []

        if websites:
            addresses, phones, pages, errors = self._scrape_official_site(websites[0])
            website_addresses.extend(addresses)
            website_phones.extend(phones)
            scraped_from.extend(pages)
            scrape_errors.extend(errors)

        addresses = list(dict.fromkeys([*wikidata_addresses, *website_addresses]))
        phones = list(dict.fromkeys([*wikidata_phones, *website_phones]))
        address_verified = self._values_overlap(wikidata_addresses, website_addresses, kind="address")
        phone_verified = self._values_overlap(wikidata_phones, website_phones, kind="phone")
        label = entity.get("labels", {}).get("en", {}).get("value") or best.get("label") or name
        description = entity.get("descriptions", {}).get("en", {}).get("value") or best.get("description") or ""
        contact_sources = int(bool(wikidata_addresses or wikidata_phones)) + int(bool(website_addresses or website_phones))
        confidence = "high" if (address_verified or phone_verified) else "medium" if contact_sources else "identity-only"
        verification = f"address={'confirmed by two sources' if address_verified else 'single-source or unavailable'}, phone={'confirmed by two sources' if phone_verified else 'single-source or unavailable'}"
        return {
            "type": "Full Name",
            "query": name,
            "matched_entity": f"{label} ({entity_id})",
            "identity_description": description or NOT_FOUND,
            "identity_status": "exact human match",
            "address": "; ".join(addresses) if addresses else NOT_FOUND,
            "address_type": "Public official/business contact" if website_addresses else "Public structured-data contact" if wikidata_addresses else NOT_FOUND,
            "phone_number": "; ".join(phones) if phones else NOT_FOUND,
            "phone_type": "Public official/business contact" if website_phones else "Public structured-data contact" if wikidata_phones else NOT_FOUND,
            "contact_verification": verification,
            "confidence": confidence,
            "candidates": candidates,
            "sources": [f"https://www.wikidata.org/wiki/{entity_id}", *scraped_from],
            "errors": scrape_errors,
        }

    @staticmethod
    def _select_name_candidate(exact: list[dict[str, Any]], hint: str | None) -> dict[str, Any] | None:
        if len(exact) == 1:
            return exact[0]
        if not exact or not hint:
            return None
        tokens = set(re.findall(r"[a-z0-9]+", hint.casefold()))
        scored: list[tuple[int, dict[str, Any]]] = []
        for item in exact:
            haystack = f"{item.get('label', '')} {item.get('description', '')}".casefold()
            scored.append((sum(token in haystack for token in tokens), item))
        highest = max(score for score, _ in scored)
        winners = [item for score, item in scored if score == highest and score > 0]
        return winners[0] if len(winners) == 1 else None

    @staticmethod
    def _empty_name_result(name: str, errors: list[str]) -> dict[str, Any]:
        return {
            "type": "Full Name",
            "query": name,
            "matched_entity": NOT_FOUND,
            "identity_description": NOT_FOUND,
            "identity_status": "not found",
            "address": NOT_FOUND,
            "address_type": NOT_FOUND,
            "phone_number": NOT_FOUND,
            "phone_type": NOT_FOUND,
            "contact_verification": "unavailable",
            "confidence": "none",
            "candidates": [],
            "sources": [],
            "errors": errors,
        }

    @classmethod
    def _ambiguous_name_result(cls, name: str, candidates: list[dict[str, str]], reason: str) -> dict[str, Any]:
        result = cls._empty_name_result(name, [reason])
        result["matched_entity"] = "Ambiguous"
        result["identity_status"] = "ambiguous"
        result["candidates"] = candidates
        return result

    def _scrape_official_site(self, website: str) -> tuple[list[str], list[str], list[str], list[str]]:
        addresses: list[str] = []
        phones: list[str] = []
        pages: list[str] = []
        errors: list[str] = []
        queue = [website]
        visited: set[str] = set()
        allowed_host = urlsplit(website).netloc.casefold().removeprefix("www.")

        while queue and len(visited) < 3:
            page_url = queue.pop(0)
            if page_url in visited:
                continue
            visited.add(page_url)
            try:
                response = self.client.get(page_url, allow_redirects=True)
                found_addresses, found_phones, contact_links = self._scrape_contact_details(response.text, response.url)
                addresses.extend(found_addresses)
                phones.extend(found_phones)
                pages.append(response.url)
                for link in contact_links:
                    link_host = urlsplit(link).netloc.casefold().removeprefix("www.")
                    if link_host == allowed_host and link not in visited and link not in queue:
                        queue.append(link)
            except DataSourceError as exc:
                errors.append(str(exc))

        return list(dict.fromkeys(addresses)), list(dict.fromkeys(phones)), pages, errors

    @staticmethod
    def _scrape_contact_details(html: str, base_url: str) -> tuple[list[str], list[str], list[str]]:
        """Extract explicitly published contacts and same-site contact links."""
        soup = BeautifulSoup(html, "html.parser")
        addresses: list[str] = []
        phones: list[str] = []
        contact_links: list[str] = []
        for node in soup.select("address, [itemprop='address']"):
            text = " ".join(node.get_text(" ", strip=True).split())
            if 5 <= len(text) <= 300:
                addresses.append(text)
        for link in soup.select("a[href^='tel:']"):
            value = link.get("href", "")[4:].strip()
            if value:
                phones.append(value)
        for script in soup.select("script[type='application/ld+json']"):
            try:
                SearchService._collect_json_contacts(json.loads(script.string or ""), addresses, phones)
            except (TypeError, ValueError):
                continue
        for link in soup.select("a[href]"):
            href = str(link.get("href", ""))
            label = f"{link.get_text(' ', strip=True)} {href}".casefold()
            if any(word in label for word in ("contact", "contacts", "about", "impressum")):
                absolute = urljoin(base_url, href)
                if urlsplit(absolute).scheme in {"http", "https"}:
                    contact_links.append(absolute.split("#", 1)[0])
        return list(dict.fromkeys(addresses)), list(dict.fromkeys(phones)), list(dict.fromkeys(contact_links))

    @staticmethod
    def _collect_json_contacts(value: Any, addresses: list[str], phones: list[str]) -> None:
        if isinstance(value, list):
            for item in value:
                SearchService._collect_json_contacts(item, addresses, phones)
        elif isinstance(value, dict):
            telephone = value.get("telephone")
            if isinstance(telephone, str) and telephone.strip():
                phones.append(telephone.strip())
            address = value.get("address")
            if isinstance(address, str) and address.strip():
                addresses.append(address.strip())
            elif isinstance(address, dict):
                parts = [str(address.get(key, "")).strip() for key in ("streetAddress", "addressLocality", "addressRegion", "postalCode", "addressCountry")]
                combined = ", ".join(part for part in parts if part)
                if combined:
                    addresses.append(combined)
            for nested in value.values():
                if nested is not telephone and nested is not address:
                    SearchService._collect_json_contacts(nested, addresses, phones)

    @staticmethod
    def _values_overlap(first: list[str], second: list[str], kind: str) -> bool:
        def normalize(value: str) -> str:
            if kind == "phone":
                return "".join(re.findall(r"\d", value))
            return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))

        left = [normalize(value) for value in first]
        right = [normalize(value) for value in second]
        return any(a and b and (a == b or (kind == "address" and (a in b or b in a))) for a in left for b in right)

    def search_username(self, username: str) -> dict[str, Any]:
        username = username.strip().lstrip("@")
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,50}", username):
            raise ValueError("Username may contain only letters, digits, dot, underscore and hyphen")

        platforms: list[dict[str, str]] = []
        errors: list[str] = []
        encoded = quote(username, safe="._-")
        for platform, settings in self.PLATFORMS.items():
            profile_url = settings["profile"].format(username=encoded)
            probe_url = settings.get("probe", settings["profile"]).format(username=encoded)
            try:
                response = self.client.get(probe_url, allow_redirects=True)
                status, method = self._classify_profile_response(response, profile_url, username, settings)
                platforms.append({"platform": platform, "exists": status, "url": profile_url, "method": method})
            except DataSourceError as exc:
                if exc.status_code == 404:
                    platforms.append({"platform": platform, "exists": "no", "url": profile_url, "method": "HTTP 404"})
                else:
                    platforms.append({"platform": platform, "exists": "unknown", "url": profile_url, "method": "request blocked or unavailable"})
                    errors.append(f"{platform}: {exc}")
            except (TypeError, ValueError):
                platforms.append({"platform": platform, "exists": "unknown", "url": profile_url, "method": "invalid provider response"})
                errors.append(f"{platform}: invalid provider response")
        return {"type": "Username", "query": f"@{username}", "platforms": platforms, "confidence": "conservative platform validation", "errors": errors}

    @classmethod
    def _classify_profile_response(
        cls,
        response: Any,
        profile_url: str,
        username: str,
        settings: dict[str, Any],
    ) -> tuple[str, str]:
        mode = settings.get("mode", "html")
        if mode == "json-object":
            payload = response.json()
            exists = isinstance(payload, dict) and str(payload.get("login", "")).casefold() == username.casefold()
            return ("yes", "public API exact username match") if exists else ("unknown", "API response did not confirm exact username")
        if mode == "json-list":
            payload = response.json()
            exists = isinstance(payload, list) and any(
                str(item.get("username", "")).casefold() == username.casefold()
                for item in payload
                if isinstance(item, dict)
            )
            return ("yes", "public API exact username match") if exists else ("no", "public API returned no exact username")
        if mode == "reddit-json":
            payload = response.json()
            found = payload.get("data", {}).get("name") if isinstance(payload, dict) else None
            exists = isinstance(found, str) and found.casefold() == username.casefold()
            return ("yes", "public API exact username match") if exists else ("unknown", "API response did not confirm exact username")
        if mode == "steam-xml":
            text = response.text[:500_000]
            if "The specified profile could not be found" in text:
                return "no", "public XML response reports missing profile"
            if re.search(r"<steamID64>\d+</steamID64>", text):
                return "yes", "public XML response contains Steam profile ID"
            return "unknown", "XML response did not confirm a profile"
        return cls._classify_html_profile(response, profile_url, username, settings)

    @classmethod
    def _classify_html_profile(
        cls,
        response: Any,
        profile_url: str,
        username: str,
        settings: dict[str, Any],
    ) -> tuple[str, str]:
        html = response.text[:500_000]
        text = html.casefold()
        if any(marker.casefold() in text for marker in settings.get("missing", ())):
            return "no", "platform-specific missing-profile marker"
        if any(marker.casefold() in text for marker in settings.get("blocked", ())):
            return "unknown", "login wall, CAPTCHA or access-control marker"
        if cls._normalized_url(response.url) != cls._normalized_url(profile_url):
            return "unknown", "redirected away from requested profile"

        soup = BeautifulSoup(html, "html.parser")
        metadata: list[str] = []
        if soup.title and soup.title.string:
            metadata.append(soup.title.string)
        for node in soup.select("meta[property^='og:'], meta[name^='twitter:'], meta[itemprop]"):
            content = node.get("content")
            if content:
                metadata.append(str(content))
        canonical_urls = [str(node.get("href")) for node in soup.select("link[rel='canonical'][href]")]
        canonical_urls.extend(str(node.get("content")) for node in soup.select("meta[property='og:url'][content]"))
        url_confirmed = any(cls._normalized_url(value) == cls._normalized_url(profile_url) for value in canonical_urls)
        username_pattern = re.compile(rf"(?<![a-z0-9._-])@?{re.escape(username)}(?![a-z0-9._-])", re.IGNORECASE)
        identity_confirmed = any(username_pattern.search(value) for value in metadata)
        if url_confirmed and identity_confirmed:
            return "yes", "canonical profile URL + username metadata"
        return "unknown", "no unambiguous profile metadata"

    @staticmethod
    def _normalized_url(value: str) -> str:
        parsed = urlsplit(value)
        host = parsed.netloc.casefold().removeprefix("www.")
        path = re.sub(r"/+", "/", parsed.path).rstrip("/").casefold()
        return f"{host}{path}"
