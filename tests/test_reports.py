import tempfile
import unittest
from pathlib import Path

from digital_detective.reports import available_path, report_stem


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


if __name__ == "__main__":
    unittest.main()
