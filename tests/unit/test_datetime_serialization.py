import unittest
from datetime import datetime

from services.datetime_serialization import serialize_datetime_iso


class DateTimeSerializationTestCase(unittest.TestCase):
    def test_serialize_datetime_iso_returns_none_for_none(self):
        self.assertIsNone(serialize_datetime_iso(None))

    def test_serialize_datetime_iso_returns_iso8601_string(self):
        value = datetime(2024, 1, 2, 3, 4, 5)
        self.assertEqual(serialize_datetime_iso(value), "2024-01-02T03:04:05")


if __name__ == "__main__":
    unittest.main()
