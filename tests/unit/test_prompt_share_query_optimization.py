import unittest
from unittest.mock import patch

from blueprints.prompt_share.prompt_share_api import _get_prompts_with_flags


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.executed = []
        self.closed = False

    def execute(self, query, params=None):
        self.executed.append((" ".join(query.split()), params))

    def fetchall(self):
        return self.rows

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


class PromptShareQueryOptimizationTestCase(unittest.TestCase):
    def test_get_prompts_with_flags_uses_single_join_query(self):
        fake_cursor = FakeCursor(
            [
                {
                    "id": 1,
                    "title": "Prompt",
                    "category": "仕事",
                    "content": "Body",
                    "author": "tester",
                    "input_examples": "",
                    "output_examples": "",
                    "ai_model": "gemini",
                    "prompt_type": "text",
                    "reference_image_url": None,
                    "created_at": "2024-01-01T00:00:00",
                    "liked": True,
                    "bookmarked": True,
                    "saved_to_list": False,
                }
            ]
        )
        fake_conn = FakeConnection(fake_cursor)

        with patch("blueprints.prompt_share.prompt_share_api.get_db_connection", return_value=fake_conn):
            prompts = _get_prompts_with_flags(7)

        self.assertEqual(len(fake_cursor.executed), 1)
        query, params = fake_cursor.executed[0]
        self.assertIn("LEFT JOIN prompt_likes AS pl", query)
        self.assertIn("LEFT JOIN task_with_examples AS b", query)
        self.assertIn("LEFT JOIN prompt_list_entries AS ple", query)
        self.assertEqual(params, (7, 7, 7))
        self.assertTrue(prompts[0]["liked"])
        self.assertTrue(prompts[0]["bookmarked"])
        self.assertFalse(prompts[0]["saved_to_list"])
        self.assertTrue(fake_cursor.closed)
        self.assertTrue(fake_conn.closed)


if __name__ == "__main__":
    unittest.main()
