import tempfile
import unittest
from pathlib import Path

from digital_detective.reports import available_path, render_html_report, report_stem, save_report


class ReportTests(unittest.TestCase):
    def test_required_single_search_names(self):
        self.assertEqual(report_stem("Dwight Schrute", None, None), "n_dwight_schrute")
        self.assertEqual(report_stem(None, "192.168.1.1", None), "ip_192_168_1_1")
        self.assertEqual(report_stem(None, None, "@recyclops"), "un_recyclops")

    def test_multiple_search_name(self):
        self.assertEqual(report_stem("Dwight Schrute", "8.8.8.8", "recyclops"), "n_ip_un_dwight_schrute")

    def test_existing_file_gets_number_suffix(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "n_jane_doe.txt").touch()
            self.assertEqual(available_path(root, "n_jane_doe").name, "n_jane_doe1.txt")

    def test_html_visualization_is_consistent_across_search_types(self):
        results = [
            {
                "type": "Full Name", "query": "Jane Doe", "matched_entity": "Jane Doe (Q1)",
                "identity_description": "researcher", "identity_status": "exact human match",
                "address": "Public office", "address_type": "Public official/business contact",
                "phone_number": "+1 555 0100", "phone_type": "Public official/business contact",
                "contact_verification": "confirmed", "confidence": "high",
                "sources": ["https://example.test/contact"], "errors": [],
            },
            {
                "type": "IP", "query": "8.8.8.8", "location": "Mountain View, United States",
                "coordinates": "1, 2", "isp": "Example ISP", "cross_reference": "country=match, ISP=match",
                "confidence": "high", "providers": [
                    {"source": "Provider", "city": "Mountain View", "country": "United States", "isp": "Example ISP"}
                ], "errors": [],
            },
            {
                "type": "Username", "query": "@janedoe", "confidence": "conservative platform validation",
                "platforms": [
                    {"platform": "GitHub", "exists": "yes", "url": "https://github.com/janedoe", "method": "API match"},
                    {"platform": "Instagram", "exists": "unknown", "url": "https://instagram.com/janedoe", "method": "login wall"},
                ], "errors": [],
            },
        ]
        html = render_html_report(results)
        self.assertEqual(html.count('<section class="panel">'), 3)
        self.assertIn("Provider comparison", html)
        self.assertIn("Platform result summary", html)
        self.assertIn("bar-yes", html)
        self.assertIn("Verification sources", html)

    def test_html_visualization_escapes_untrusted_values(self):
        html = render_html_report([{
            "type": "Username", "query": "<script>alert(1)</script>", "confidence": "none",
            "platforms": [{"platform": "Site", "exists": "unknown", "url": "javascript:alert(1)", "method": "<unsafe>"}],
            "errors": [],
        }])
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertNotIn('href="javascript:', html)
        self.assertIn("&lt;unsafe&gt;", html)

    def test_save_report_creates_matching_html_file(self):
        with tempfile.TemporaryDirectory() as directory:
            text_path, json_path, html_path = save_report(
                Path(directory), "un_octocat",
                [{"type": "Username", "query": "@octocat", "platforms": [], "confidence": "none", "errors": []}],
                save_json=True, save_html=True,
            )
            self.assertEqual(text_path.name, "un_octocat.txt")
            self.assertEqual(json_path.name, "un_octocat.json")
            self.assertEqual(html_path.name, "un_octocat.html")
            self.assertIn("<!doctype html>", html_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
