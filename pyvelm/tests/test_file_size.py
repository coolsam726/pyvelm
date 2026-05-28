"""Table-driven tests for the ``human_size`` Jinja filter."""

import unittest

from pyvelm.file_size import human_size


class HumanSizeTests(unittest.TestCase):
    def test_table(self):
        cases = [
            (None, "—"),
            (0, "—"),
            (-1, "—"),
            (1, "1 B"),
            (1023, "1023 B"),
            (1024, "1.0 KB"),
            (1536, "1.5 KB"),
            (1_500_000, "1.4 MB"),
            (2_147_483_648, "2.0 GB"),
            (5 * 1024 ** 4, "5.0 TB"),
        ]
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(human_size(value), expected)

    def test_non_numeric_yields_dash(self):
        self.assertEqual(human_size("not-a-number"), "—")
        self.assertEqual(human_size(object()), "—")


if __name__ == "__main__":
    unittest.main()
