import unittest
from datetime import datetime

from services.datetime_serialization import serialize_datetime_iso


# 日本語: Date Time Serializationの機能や仕様を検証するテストクラスです。
# English: Test case class to verify the functionality and specifications of Date Time Serialization.
class DateTimeSerializationTestCase(unittest.TestCase):
    # 日本語: noneに対して、serialize日時iso返却するnoneことを検証します。
    # English: Verify that serialize datetime iso returns none for none.
    def test_serialize_datetime_iso_returns_none_for_none(self):
        self.assertIsNone(serialize_datetime_iso(None))

    # 日本語: serialize日時iso返却するiso8601stringことを検証します。
    # English: Verify that serialize datetime iso returns iso8601 string.
    def test_serialize_datetime_iso_returns_iso8601_string(self):
        value = datetime(2024, 1, 2, 3, 4, 5)
        self.assertEqual(serialize_datetime_iso(value), "2024-01-02T03:04:05")


if __name__ == "__main__":
    unittest.main()
