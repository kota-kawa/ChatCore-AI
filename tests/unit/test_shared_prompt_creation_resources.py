import json
import unittest
from unittest.mock import patch

from services.request_models import SharedPromptCreateRequest
from services.shared_prompt_service import create_shared_prompt


class FakeCursor:
    def __init__(self):
        self.executed = []
        self.closed = False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchone(self):
        return (42,)

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self):
        self.db_cursor = FakeCursor()
        self.committed = False
        self.rolled_back = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self):
        return self.db_cursor

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


class RecordingResourceRepository:
    def __init__(self, error=None):
        self.calls = []
        self.error = error

    def insert_many(self, cursor, prompt_id, resources):
        self.calls.append((cursor, prompt_id, list(resources)))
        if self.error:
            raise self.error


class SharedPromptCreationResourcesTestCase(unittest.TestCase):
    def _payload(self):
        return SharedPromptCreateRequest.model_validate(
            {
                "title": "Portable skill",
                "content_format": "skill",
                "attributes": {
                    "skill_markdown": "# Portable skill",
                    "skill_python_script": "print('legacy')",
                },
                "resources": [
                    {
                        "path": "scripts/run.ts",
                        "role": "script",
                        "language": "typescript",
                        "content": "export const run = () => true;",
                    }
                ],
            }
        )

    def test_saves_prompt_and_resources_with_one_transaction(self):
        connection = FakeConnection()
        repository = RecordingResourceRepository()

        with patch(
            "services.shared_prompt_service.get_db_connection",
            return_value=connection,
        ):
            prompt_id = create_shared_prompt(
                7,
                self._payload(),
                resource_repository=repository,
            )

        self.assertEqual(prompt_id, 42)
        self.assertTrue(connection.committed)
        self.assertFalse(connection.rolled_back)
        self.assertEqual(repository.calls[0][0], connection.db_cursor)
        self.assertEqual(repository.calls[0][1], 42)
        self.assertEqual(
            [item.path for item in repository.calls[0][2]],
            ["scripts/run.ts", "scripts/main.py"],
        )
        persisted_attributes = json.loads(connection.db_cursor.executed[0][1][6])
        self.assertEqual(persisted_attributes, {"skill_markdown": "# Portable skill"})

    def test_rolls_back_when_resource_insert_fails(self):
        connection = FakeConnection()
        repository = RecordingResourceRepository(error=RuntimeError("insert failed"))

        with patch(
            "services.shared_prompt_service.get_db_connection",
            return_value=connection,
        ), self.assertRaises(RuntimeError):
            create_shared_prompt(
                7,
                self._payload(),
                resource_repository=repository,
            )

        self.assertFalse(connection.committed)
        self.assertTrue(connection.rolled_back)
        self.assertTrue(connection.db_cursor.closed)


if __name__ == "__main__":
    unittest.main()
