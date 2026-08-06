import unittest

from digital_detective.search import NOT_FOUND, SearchService


class FakeResponse:
    def __init__(self, text="", url="https://example.test/contact"):
        self.text = text
        self.url = url

    def json(self):
        if "api.github.com/users/" in self.url:
            return {"login": self.url.rsplit("/", 1)[-1]}
        if "gitlab.com/api/v4/users" in self.url:
            return [{"username": self.url.rsplit("=", 1)[-1]}]
        return {}


class FakeClient:
    def __init__(self, json_responses=None, pages=None):
        self.json_responses = list(json_responses or [])
        self.pages = pages or {}

    def get_json(self, url, **kwargs):
        return self.json_responses.pop(0)

    def get(self, url, **kwargs):
        return self.pages.get(url, FakeResponse("profile page", url))


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

    def test_full_name_extracts_public_contact_details(self):
        official = "https://example.test/contact"
        client = FakeClient(
            json_responses=[
                {"search": [{"id": "Q1", "label": "Jane Example"}]},
                {"entities": {"Q1": {"labels": {"en": {"value": "Jane Example"}}, "claims": {
                    "P856": [{"mainsnak": {"datavalue": {"value": official}}}],
                }}}},
            ],
            pages={official: FakeResponse('<address>1 Public Square, Example City</address><a href="tel:+1-555-0100">Call</a>', official)},
        )
        result = SearchService(client).search_name("Jane Example")
        self.assertEqual(result["address"], "1 Public Square, Example City")
        self.assertEqual(result["phone_number"], "+1-555-0100")
        self.assertIn(official, result["sources"])

    def test_name_without_public_contacts_still_has_required_fields(self):
        client = FakeClient(json_responses=[{"search": []}])
        result = SearchService(client).search_name("Unknown Person")
        self.assertEqual(result["address"], NOT_FOUND)
        self.assertEqual(result["phone_number"], NOT_FOUND)

    def test_username_checks_at_least_five_platforms(self):
        result = SearchService(FakeClient()).search_username("octocat")
        self.assertEqual(len(result["platforms"]), 10)
        self.assertIn("Instagram", {item["platform"] for item in result["platforms"]})
        self.assertIn("Steam", {item["platform"] for item in result["platforms"]})
        self.assertTrue(all(item["exists"] == "yes" for item in result["platforms"]))


if __name__ == "__main__":
    unittest.main()
