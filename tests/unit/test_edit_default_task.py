import asyncio
import unittest
from unittest.mock import patch

from blueprints.chat.tasks import edit_task
from tests.helpers.request_helpers import build_request


class FakeCursor:
    def __init__(self):
        self.executed = []
        self._fetchone_result = None

    def execute(self, query, params=None):
        self.executed.append((query, params))
        if "SELECT 1" in query:
            self._fetchone_result = (1,)
        else:
            self._fetchone_result = None

    def fetchone(self):
        result = self._fetchone_result
        self._fetchone_result = None
        return result

    def close(self):
        pass


class FakeConnection:
    def __init__(self):
        self.committed = False
        self.closed = False
        self.cursors = []

    def cursor(self, dictionary=False):
        cursor = FakeCursor()
        self.cursors.append(cursor)
        return cursor

    def commit(self):
        self.committed = True

    def close(self):
        self.closed = True


def make_request(json_body, session=None):
    return build_request(
        method="POST",
        path="/api/edit_task",
        json_body=json_body,
        session=session,
    )


class EditDefaultTaskTestCase(unittest.TestCase):
    def test_editing_copied_default_task_is_allowed(self):
        fake_connection = FakeConnection()
        request = make_request(
            {
                "old_task": "Default Task",
                "new_task": "Updated Task",
                "prompt_template": "Prompt",
                "response_rules": "Rules",
                "output_skeleton": "Skeleton",
                "input_examples": "input",
                "output_examples": "output",
            },
            session={"user_id": 123},
        )

        with patch("blueprints.chat.tasks.get_db_connection", return_value=fake_connection):
            response = asyncio.run(edit_task(request))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(fake_connection.committed)
        self.assertTrue(any("SELECT 1" in query for query, _ in fake_connection.cursors[0].executed))


if __name__ == "__main__":
    unittest.main()
