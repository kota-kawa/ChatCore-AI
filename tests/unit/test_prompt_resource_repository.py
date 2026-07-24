import hashlib
import unittest

from services.repositories.prompt_resource_repository import PromptResourceRepository
from services.request_models import SkillResourceInput


class FakeCursor:
    def __init__(self, *, rows=None, row=None):
        self.executed = []
        self.rows = rows or []
        self.row = row
        self.closed = False

    def execute(self, sql, params=None):
        self.executed.append((" ".join(sql.split()), params))

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.row

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self, cursor):
        self.db_cursor = cursor
        self.closed = False

    def cursor(self, *args, **kwargs):
        return self.db_cursor

    def close(self):
        self.closed = True


class PromptResourceRepositoryTestCase(unittest.TestCase):
    def setUp(self):
        self.repository = PromptResourceRepository()

    def test_insert_many_records_utf8_size_digest_and_order(self):
        cursor = FakeCursor()
        resources = [
            SkillResourceInput(path="scripts/a.py", role="script", content="あ"),
            SkillResourceInput(path="references/a.md", role="reference", content="# A"),
        ]

        self.repository.insert_many(cursor, 9, resources)

        self.assertEqual(len(cursor.executed), 2)
        first_params = cursor.executed[0][1]
        self.assertEqual(first_params[0:6], (9, "scripts/a.py", "script", "python", "text/x-python", "あ"))
        self.assertEqual(first_params[6], 3)
        self.assertEqual(first_params[7], hashlib.sha256("あ".encode("utf-8")).hexdigest())
        self.assertEqual(first_params[8], 0)
        self.assertEqual(cursor.executed[1][1][8], 1)

    def test_replace_deletes_before_inserting(self):
        cursor = FakeCursor()
        self.repository.replace_for_prompt(
            cursor,
            5,
            [SkillResourceInput(path="config/settings.json", role="config", content="{}")],
        )

        self.assertIn("DELETE FROM prompt_resources", cursor.executed[0][0])
        self.assertIn("INSERT INTO prompt_resources", cursor.executed[1][0])

    def test_list_and_get_map_text_content_to_content(self):
        row = {
            "id": 1,
            "prompt_id": 3,
            "path": "scripts/run.py",
            "content": "print(1)",
        }
        list_cursor = FakeCursor(rows=[row])
        list_connection = FakeConnection(list_cursor)
        self.assertEqual(
            self.repository.list_for_prompt(3, connection=list_connection),
            [row],
        )
        self.assertFalse(list_connection.closed)

        get_cursor = FakeCursor(row=row)
        get_connection = FakeConnection(get_cursor)
        self.assertEqual(
            self.repository.get_for_prompt(
                3,
                "scripts/run.py",
                connection=get_connection,
            ),
            row,
        )
        self.assertIn("lower(path) = lower(%s)", get_cursor.executed[0][0])


if __name__ == "__main__":
    unittest.main()
