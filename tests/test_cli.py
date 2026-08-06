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

    def search_name(self, value):
        return {"type": "Full Name", "query": value, "matched_entity": value, "address": "Public address", "phone_number": "+1 555 0100", "confidence": "high", "sources": [], "errors": []}

    def search_username(self, value):
        return {"type": "Username", "query": "@" + value.lstrip("@"), "platforms": [{"platform": "GitHub", "exists": "yes", "url": "https://github.com/example"}], "confidence": "platform-response", "errors": []}


class CliTests(unittest.TestCase):
    def test_help_lists_all_search_options(self):
        help_text = build_parser().format_help()
        self.assertIn("-n FULL_NAME", help_text)
        self.assertIn("-ip IP_ADDRESS", help_text)
        self.assertIn("-un USERNAME", help_text)

    def test_no_arguments_displays_usage(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit):
            main([])
        self.assertIn("usage:", stderr.getvalue().casefold())

    def test_invalid_ip_displays_usage(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit):
            main(["-ip", "not-an-ip"])
        self.assertIn("usage:", stderr.getvalue().casefold())
        self.assertIn("invalid IP address", stderr.getvalue())

    @patch("digital_detective.cli.SearchService", FakeService)
    def test_multiple_parameters_print_and_save(self):
        with tempfile.TemporaryDirectory() as directory:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(["-n", "Jane Doe", "-ip", "8.8.8.8", "-un", "janedoe", "--output-dir", directory, "--json"])
            self.assertEqual(code, 0)
            self.assertIn("Address: Public address", output.getvalue())
            self.assertTrue((Path(directory) / "n_ip_un_jane_doe.txt").exists())
            self.assertTrue((Path(directory) / "n_ip_un_jane_doe.json").exists())


if __name__ == "__main__":
    unittest.main()
