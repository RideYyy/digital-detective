"""Optional live checks; excluded from normal deterministic test runs."""

import os
import unittest

from digital_detective.http_client import HttpClient, RetryPolicy
from digital_detective.search import SearchService


@unittest.skipUnless(os.getenv("RUN_INTEGRATION_TESTS") == "1", "set RUN_INTEGRATION_TESTS=1 to run live checks")
class LiveIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        client = HttpClient(
            "DigitalDetective/1.1 integration-test",
            policy=RetryPolicy(attempts=2, timeout=15, min_interval=0.2),
        )
        cls.service = SearchService(client)

    def test_two_public_ip_sources(self):
        result = self.service.search_ip("8.8.8.8")
        self.assertGreaterEqual(len(result["providers"]), 1)
        self.assertNotEqual(result["isp"], "Not found in public sources")

    def test_known_github_username(self):
        result = self.service.search_username("octocat")
        platforms = {item["platform"]: item["exists"] for item in result["platforms"]}
        self.assertEqual(platforms["GitHub"], "yes")
        self.assertTrue(set(platforms.values()) <= {"yes", "no", "unknown"})

    def test_human_identity_filter(self):
        result = self.service.search_name("Elon Musk", "businessman")
        self.assertEqual(result["matched_entity"], "Elon Musk (Q317521)")
        self.assertEqual(result["identity_status"], "exact human match")


if __name__ == "__main__":
    unittest.main()
