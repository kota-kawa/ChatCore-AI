import unittest
from unittest.mock import patch

from blueprints.prompt_share.prompt_search import _search_public_prompts


class FakeCursor:
    def __init__(self):
        self.executed = []
        self.closed = False
        self._fetchone_result = None
        self._fetchall_result = []

    def execute(self, query, params=None):
        normalized = " ".join(query.split())
        self.executed.append((normalized, params))
        if "SELECT COUNT(*) AS total" in normalized:
            self._fetchone_result = {"total": 55}
            return
        if "FROM prompts" in normalized and "LIMIT %s OFFSET %s" in normalized:
            self._fetchall_result = [
                {
                    "id": 11,
                    "title": "sample",
                    "category": "仕事",
                    "content": "body",
                    "author": "tester",
                    "input_examples": "",
                    "output_examples": "",
                    "prompt_type": "text",
                    "reference_image_url": None,
                    "created_at": "2024-01-01T00:00:00",
                    "liked": True,
                    "bookmarked": False,
                    "saved_to_list": True,
                }
            ]

    def fetchone(self):
        result = self._fetchone_result
        self._fetchone_result = None
        return result

    def fetchall(self):
        result = self._fetchall_result
        self._fetchall_result = []
        return result

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.closed = False

    def cursor(self, *args, **kwargs):
        return self._cursor

    def close(self):
        self.closed = True


class PromptSearchTestCase(unittest.TestCase):
    def test_search_public_prompts_applies_limit_offset_and_returns_metadata(self):
        fake_cursor = FakeCursor()
        fake_conn = FakeConnection(fake_cursor)

        with patch("blueprints.prompt_share.prompt_search.get_db_connection", return_value=fake_conn):
            payload = _search_public_prompts("sample", 2, 20, 9)

        self.assertEqual(payload["prompts"][0]["id"], 11)
        self.assertTrue(payload["prompts"][0]["liked"])
        self.assertFalse(payload["prompts"][0]["bookmarked"])
        self.assertTrue(payload["prompts"][0]["saved_to_list"])
        self.assertEqual(payload["pagination"]["page"], 2)
        self.assertEqual(payload["pagination"]["per_page"], 20)
        self.assertEqual(payload["pagination"]["total"], 55)
        self.assertEqual(payload["pagination"]["total_pages"], 3)
        self.assertTrue(payload["pagination"]["has_next"])
        self.assertTrue(payload["pagination"]["has_prev"])

        count_query, count_params = fake_cursor.executed[0]
        self.assertIn("SELECT COUNT(*) AS total", count_query)
        self.assertEqual(count_params, ("%sample%", "%sample%", "%sample%", "%sample%"))

        search_query, search_params = fake_cursor.executed[1]
        self.assertIn("LEFT JOIN prompt_likes AS pl", search_query)
        self.assertIn("LIMIT %s OFFSET %s", search_query)
        self.assertEqual(search_params[:3], (9, 9, 9))
        self.assertEqual(search_params[-2:], (20, 20))
        self.assertTrue(fake_cursor.closed)
        self.assertTrue(fake_conn.closed)

    def test_search_public_prompts_returns_empty_payload_when_query_is_blank(self):
        payload = _search_public_prompts("", 1, 20)

        self.assertEqual(payload["prompts"], [])
        self.assertEqual(payload["pagination"]["total"], 0)
        self.assertFalse(payload["pagination"]["has_next"])


if __name__ == "__main__":
    unittest.main()
