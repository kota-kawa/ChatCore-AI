import unittest
from datetime import datetime

from services.datetime_serialization import serialize_datetime_iso


# 日本語: datetimeオブジェクトのISOフォーマットシリアライズ処理を検証するテストクラス。
# English: Test class to verify the ISO format serialization of datetime objects.
class DateTimeSerializationTestCase(unittest.TestCase):
    # 日本語: Noneを渡した場合に、Noneがそのまま返却されることを検証します。
    # English: Verify that passing None returns None without raising an error.
    def test_serialize_datetime_iso_returns_none_for_none(self):
        self.assertIsNone(serialize_datetime_iso(None))

    # 日本語: datetimeオブジェクトが正しいISO 8601形式の文字列にシリアライズされることを検証します。
    # English: Verify that a datetime object is correctly serialized to an ISO 8601 format string.
    def test_serialize_datetime_iso_returns_iso8601_string(self):
        value = datetime(2024, 1, 2, 3, 4, 5)
        self.assertEqual(serialize_datetime_iso(value), "2024-01-02T03:04:05")


if __name__ == "__main__":
    unittest.main()
