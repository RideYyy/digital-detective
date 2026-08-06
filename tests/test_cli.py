import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from digital_detective.cli import build_parser, main


class FakeService:
    def __init__(self, client):
        pass

    def search_ip(self, value):
        return {"type": "IP", "query": value, "location": "City, Country", "coordinates": "1, 2", "isp": "Example ISP", "cross_reference": "country=match, ISP=match", "confidence": "high", "providers": [], "errors": []}

    def search_name(self, value, hint=None):
        return {"type": "Full Name", "query": value, "matched_entity": value, "identity_description": hint or "Example person", "identity_status": "exact human match", "address": "Public address", "address_type": "Public official/business contact", "phone_number": "+1 555 0100", "phone_type": "Public official/business contact", "contact_verification": "confirmed", "confidence": "high", "candidates": [], "sources": [], "errors": []}

    def search_username(self, value):
        return {"type": "Username", "query": "@" + value.lstrip("@"), "platforms": [{"platform": "GitHub", "exists": "yes", "url": "https://github.com/example"}], "confidence": "platform-response", "errors": []}


class CliTests(unittest.TestCase):
    def test_help_lists_all_search_options(self):
        help_text = build_parser().format_help()
        self.assertIn("-n FULL_NAME", help_text)
        self.assertIn("-ip IP_ADDRESS", help_text)
        self.assertIn("-un USERNAME", help_text)
        self.assertIn("--name-hint TEXT", help_text)
        self.assertIn("--html", help_text)

    def test_no_arguments_displays_usage(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit):
            main([])
        self.assertIn("usage:", stderr.getvalue().casefold())

    def test_version(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit):
            main(["--version"])
        self.assertIn("1.2.0", output.getvalue())

    def test_invalid_ip_displays_usage(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit):
            main(["-ip", "not-an-ip"])
        self.assertIn("usage:", stderr.getvalue().casefold())
        self.assertIn("invalid IP address", stderr.getvalue())

    def test_name_hint_requires_name(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit):
            main(["-un", "octocat", "--name-hint", "scientist"])
        self.assertIn("--name-hint requires", stderr.getvalue())

    @patch("digital_detective.cli.SearchService", FakeService)
    def test_multiple_parameters_print_and_save(self):
        with tempfile.TemporaryDirectory() as directory:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(["-n", "Jane Doe", "-ip", "8.8.8.8", "-un", "janedoe", "--output-dir", directory, "--json", "--html"])
            self.assertEqual(code, 0)
            self.assertIn("Address: Public address", output.getvalue())
            self.assertTrue((Path(directory) / "n_ip_un_jane_doe.txt").exists())
            self.assertTrue((Path(directory) / "n_ip_un_jane_doe.json").exists())
            self.assertTrue((Path(directory) / "n_ip_un_jane_doe.html").exists())
            self.assertIn("HTML visualization written to file", output.getvalue())


if __name__ == "__main__":
    unittest.main()
