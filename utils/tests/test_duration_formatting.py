from django.test import TestCase

from utils.commons import (
    parse_iso8601_duration,
    format_duration,
    format_iso8601_duration,
    duration_to_seconds,
    iso8601_duration_to_seconds,
)


class ISO8601DurationTests(TestCase):
    """Test ISO 8601 duration parsing and formatting functions."""

    def test_parse_iso8601_duration(self):
        """Test ISO 8601 duration parsing."""
        # Test cases
        test_cases = [
            # Input, Expected output
            ("PT5M30S", {"days": 0, "hours": 0, "minutes": 5, "seconds": 30}),
            ("PT1H30M15S", {"days": 0, "hours": 1, "minutes": 30, "seconds": 15}),
            ("P1DT2H30M", {"days": 1, "hours": 2, "minutes": 30, "seconds": 0}),
            ("PT1H", {"days": 0, "hours": 1, "minutes": 0, "seconds": 0}),
            ("PT30S", {"days": 0, "hours": 0, "minutes": 0, "seconds": 30}),
            ("PT0S", {"days": 0, "hours": 0, "minutes": 0, "seconds": 0}),
            # Edge cases
            ("", {"days": 0, "hours": 0, "minutes": 0, "seconds": 0}),
            (None, {"days": 0, "hours": 0, "minutes": 0, "seconds": 0}),
        ]

        for input_str, expected in test_cases:
            with self.subTest(input_str=input_str):
                result = parse_iso8601_duration(input_str)
                self.assertEqual(result, expected)

    def test_format_duration(self):
        """Test duration formatting."""
        # Test cases for short format
        short_format_cases = [
            # Input, Expected output
            ({"days": 0, "hours": 1, "minutes": 30, "seconds": 15}, "1:30:15"),
            ({"days": 0, "hours": 0, "minutes": 5, "seconds": 30}, "5:30"),
            ({"days": 0, "hours": 0, "minutes": 0, "seconds": 30}, "0:30"),
            ({"days": 1, "hours": 2, "minutes": 30, "seconds": 15}, "26:30:15"),
            ({"days": 0, "hours": 0, "minutes": 0, "seconds": 0}, "0:00"),
        ]

        for input_dict, expected in short_format_cases:
            with self.subTest(input_dict=input_dict, format="short"):
                result = format_duration(input_dict, "short")
                self.assertEqual(result, expected)

        # Test cases for medium format
        medium_format_cases = [
            # Input, Expected output
            ({"days": 0, "hours": 1, "minutes": 30, "seconds": 15}, "1h 30m 15s"),
            ({"days": 0, "hours": 0, "minutes": 5, "seconds": 30}, "5m 30s"),
            ({"days": 0, "hours": 0, "minutes": 0, "seconds": 30}, "30s"),
            ({"days": 1, "hours": 2, "minutes": 30, "seconds": 15}, "1d 2h 30m 15s"),
            ({"days": 0, "hours": 0, "minutes": 0, "seconds": 0}, "0s"),
        ]

        for input_dict, expected in medium_format_cases:
            with self.subTest(input_dict=input_dict, format="medium"):
                result = format_duration(input_dict, "medium")
                self.assertEqual(result, expected)

        # Test cases for long format
        long_format_cases = [
            # Input, Expected output
            (
                {"days": 0, "hours": 1, "minutes": 30, "seconds": 15},
                "1 hour 30 minutes 15 seconds",
            ),
            (
                {"days": 0, "hours": 0, "minutes": 5, "seconds": 30},
                "5 minutes 30 seconds",
            ),
            ({"days": 0, "hours": 0, "minutes": 0, "seconds": 30}, "30 seconds"),
            (
                {"days": 1, "hours": 2, "minutes": 30, "seconds": 15},
                "1 day 2 hours 30 minutes 15 seconds",
            ),
            ({"days": 0, "hours": 0, "minutes": 0, "seconds": 0}, "0 seconds"),
        ]

        for input_dict, expected in long_format_cases:
            with self.subTest(input_dict=input_dict, format="long"):
                result = format_duration(input_dict, "long")
                self.assertEqual(result, expected)

    def test_format_iso8601_duration(self):
        """Test ISO 8601 duration formatting."""
        # Test cases
        test_cases = [
            # (input_str, format_type, expected_output)
            ("PT1H30M15S", "short", "1:30:15"),
            ("PT5M30S", "short", "5:30"),
            ("PT30S", "short", "0:30"),
            ("P1DT2H30M15S", "medium", "1d 2h 30m 15s"),
            ("PT1H30M15S", "long", "1 hour 30 minutes 15 seconds"),
            # Edge cases
            ("", "short", "0:00"),
            (None, "short", "0:00"),
        ]

        for input_str, format_type, expected in test_cases:
            with self.subTest(input_str=input_str, format_type=format_type):
                result = format_iso8601_duration(input_str, format_type)
                self.assertEqual(result, expected)

    def test_duration_to_seconds(self):
        """Test converting duration dictionary to seconds."""
        # Test cases
        test_cases = [
            # Input, Expected output
            ({"days": 0, "hours": 1, "minutes": 30, "seconds": 15}, 5415),
            ({"days": 0, "hours": 0, "minutes": 5, "seconds": 30}, 330),
            ({"days": 1, "hours": 2, "minutes": 30, "seconds": 15}, 95415),
            ({"days": 0, "hours": 0, "minutes": 0, "seconds": 30}, 30),
            ({"days": 0, "hours": 0, "minutes": 0, "seconds": 0}, 0),
        ]

        for input_dict, expected in test_cases:
            with self.subTest(input_dict=input_dict):
                result = duration_to_seconds(input_dict)
                self.assertEqual(result, expected)

    def test_iso8601_duration_to_seconds(self):
        """Test converting ISO 8601 duration string to seconds."""
        # Test cases
        test_cases = [
            # Input, Expected output
            ("PT1H30M15S", 5415),
            ("PT5M30S", 330),
            ("P1DT2H30M15S", 95415),
            ("PT30S", 30),
            ("PT0S", 0),
            # Edge cases
            ("", 0),
            (None, 0),
        ]

        for input_str, expected in test_cases:
            with self.subTest(input_str=input_str):
                result = iso8601_duration_to_seconds(input_str)
                self.assertEqual(result, expected)