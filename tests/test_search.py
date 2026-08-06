import unittest

from digital_detective.http_client import DataSourceError
from digital_detective.search import NOT_FOUND, SearchService


class FakeResponse:
    def __init__(self, text="", url="https://example.test/contact", json_payload=None):
        self.text = text
        self.url = url
        self.json_payload = json_payload

    def json(self):
        if self.json_payload is not None:
            return self.json_payload
        raise ValueError("not JSON")


class FakeClient:
    def __init__(self, json_responses=None, pages=None, errors=None):
        self.json_responses = list(json_responses or [])
        self.pages = pages or {}
        self.errors = errors or {}

    def get_json(self, url, **kwargs):
        return self.json_responses.pop(0)

    def get(self, url, **kwargs):
        if url in self.errors:
            raise self.errors[url]
        if url in self.pages:
            return self.pages[url]
        if "api.github.com/users/" in url:
            username = url.rsplit("/", 1)[-1]
            return FakeResponse(url=url, json_payload={"login": username})
        if "gitlab.com/api/v4/users" in url:
            username = url.rsplit("=", 1)[-1]
            return FakeResponse(url=url, json_payload=[{"username": username}])
        if "reddit.com/user/" in url and url.endswith("about.json"):
            username = url.split("/user/", 1)[1].split("/", 1)[0]
            return FakeResponse(url=url, json_payload={"data": {"name": username}})
        if "steamcommunity.com" in url and "xml=1" in url:
            return FakeResponse("<profile><steamID64>123456789</steamID64></profile>", url)
        return FakeResponse("<html><title>Generic page</title></html>", url)


def entity_claim(value):
    return [{"mainsnak": {"datavalue": {"value": value}}}]


class SearchTests(unittest.TestCase):
    def test_ip_uses_two_sources_and_cross_references(self):
        client = FakeClient(json_responses=[
            {"success": True, "country": "United States", "country_code": "US", "region": "California", "city": "Mountain View", "latitude": 1, "longitude": 2, "connection": {"isp": "Google LLC"}},
            {"country_name": "United States", "country_code": "US", "region": "California", "city": "Mountain View", "latitude": 1, "longitude": 2, "org": "Google LLC"},
        ])
        result = SearchService(client).search_ip("8.8.8.8")
        self.assertEqual(result["isp"], "Google LLC")
        self.assertEqual(result["confidence"], "high")
        self.assertEqual(len(result["providers"]), 2)

    def test_invalid_ip_is_rejected_before_network_call(self):
        with self.assertRaisesRegex(ValueError, "Invalid IP"):
            SearchService(FakeClient()).search_ip("999.1.1.1")

    def test_full_name_cross_references_public_contacts(self):
        official = "https://example.test/contact"
        human = {"entity-type": "item", "numeric-id": 5, "id": "Q5"}
        client = FakeClient(
            json_responses=[
                {"search": [{"id": "Q1", "label": "Jane Example", "description": "example researcher"}]},
                {"entities": {"Q1": {
                    "labels": {"en": {"value": "Jane Example"}},
                    "descriptions": {"en": {"value": "example researcher"}},
                    "claims": {
                        "P31": entity_claim(human),
                        "P856": entity_claim(official),
                        "P6375": entity_claim("1 Public Square, Example City"),
                        "P1329": entity_claim("+1-555-0100"),
                    },
                }}},
            ],
            pages={official: FakeResponse('<address>1 Public Square, Example City</address><a href="tel:+1-555-0100">Call</a>', official)},
        )
        result = SearchService(client).search_name("Jane Example")
        self.assertEqual(result["address"], "1 Public Square, Example City")
        self.assertEqual(result["phone_number"], "+1-555-0100")
        self.assertEqual(result["confidence"], "high")
        self.assertIn("confirmed by two sources", result["contact_verification"])
        self.assertEqual(result["address_type"], "Public official/business contact")

    def test_ambiguous_name_is_not_selected_automatically(self):
        human = {"entity-type": "item", "numeric-id": 5, "id": "Q5"}
        client = FakeClient(json_responses=[
            {"search": [
                {"id": "Q1", "label": "John Smith", "description": "British writer"},
                {"id": "Q2", "label": "John Smith", "description": "American scientist"},
            ]},
            {"entities": {
                "Q1": {"claims": {"P31": entity_claim(human)}},
                "Q2": {"claims": {"P31": entity_claim(human)}},
            }},
        ])
        result = SearchService(client).search_name("John Smith")
        self.assertEqual(result["identity_status"], "ambiguous")
        self.assertEqual(result["address"], NOT_FOUND)
        self.assertEqual(len(result["candidates"]), 2)

    def test_name_hint_selects_unique_candidate(self):
        human = {"entity-type": "item", "numeric-id": 5, "id": "Q5"}
        client = FakeClient(json_responses=[
            {"search": [
                {"id": "Q1", "label": "John Smith", "description": "British writer"},
                {"id": "Q2", "label": "John Smith", "description": "American scientist"},
            ]},
            {"entities": {"Q2": {"labels": {"en": {"value": "John Smith"}}, "descriptions": {"en": {"value": "American scientist"}}, "claims": {"P31": entity_claim(human)}}}},
        ])
        result = SearchService(client).search_name("John Smith", "scientist")
        self.assertEqual(result["matched_entity"], "John Smith (Q2)")
        self.assertEqual(result["identity_status"], "exact human match")

    def test_name_without_public_contacts_has_required_fields(self):
        client = FakeClient(json_responses=[{"search": []}])
        result = SearchService(client).search_name("Unknown Person")
        self.assertEqual(result["address"], NOT_FOUND)
        self.assertEqual(result["phone_number"], NOT_FOUND)

    def test_username_keeps_ten_platforms_without_false_generic_yes(self):
        result = SearchService(FakeClient()).search_username("octocat")
        statuses = {item["platform"]: item["exists"] for item in result["platforms"]}
        self.assertEqual(len(statuses), 10)
        self.assertEqual(statuses["GitHub"], "yes")
        self.assertEqual(statuses["GitLab"], "yes")
        self.assertEqual(statuses["Reddit"], "yes")
        self.assertEqual(statuses["Steam"], "yes")
        self.assertEqual(statuses["Instagram"], "unknown")
        self.assertEqual(statuses["Facebook"], "unknown")

    def test_html_profile_requires_url_and_username_metadata(self):
        profile = "https://www.instagram.com/octocat/"
        html = '<html><head><link rel="canonical" href="https://www.instagram.com/octocat/"><meta property="og:title" content="Octocat (@octocat) on Instagram"></head></html>'
        response = FakeResponse(html, profile)
        status, method = SearchService._classify_html_profile(response, profile, "octocat", {})
        self.assertEqual(status, "yes")
        self.assertIn("canonical", method)

    def test_html_login_wall_is_unknown(self):
        profile = "https://www.instagram.com/octocat/"
        response = FakeResponse("<title>Log in to Instagram</title>", profile)
        status, _ = SearchService._classify_html_profile(response, profile, "octocat", {"blocked": ("log in to instagram",)})
        self.assertEqual(status, "unknown")

    def test_html_missing_marker_is_no(self):
        profile = "https://www.instagram.com/missing/"
        response = FakeResponse("Page isn't available", profile)
        status, _ = SearchService._classify_html_profile(response, profile, "missing", {"missing": ("page isn't available",)})
        self.assertEqual(status, "no")

    def test_html_redirect_is_unknown(self):
        profile = "https://x.com/octocat"
        response = FakeResponse("<title>Octocat</title>", "https://x.com/home")
        status, _ = SearchService._classify_html_profile(response, profile, "octocat", {})
        self.assertEqual(status, "unknown")

    def test_http_404_is_no(self):
        instagram_probe = "https://www.instagram.com/missing/"
        client = FakeClient(errors={instagram_probe: DataSourceError("not found", status_code=404)})
        result = SearchService(client).search_username("missing")
        instagram = next(item for item in result["platforms"] if item["platform"] == "Instagram")
        self.assertEqual(instagram["exists"], "no")


if __name__ == "__main__":
    unittest.main()
