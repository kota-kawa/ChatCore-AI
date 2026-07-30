import asyncio
import json
import unittest
from unittest.mock import patch

from services.api_errors import ApiServiceError, ResourceNotFoundError
from services.repositories.chat_repository import ChatRepository
from blueprints.chat.messages import _load_task_prompt_data, _parse_task_launch_message
from blueprints.chat.tasks import (
    _add_task_for_user,
    _delete_task_for_user,
    _edit_task_for_user,
    _update_tasks_order_for_user,
    delete_task,
)
from tests.helpers.request_helpers import build_request


class ScriptedCursor:
    def __init__(self, *, fetchone_results=None, fetchall_result=None, update_rowcounts=None):
        self.fetchone_results = list(fetchone_results or [])
        self.fetchall_result = list(fetchall_result or [])
        self.update_rowcounts = list(update_rowcounts or [])
        self.executed = []
        self.rowcount = 0

    def execute(self, query, params=None):
        normalized = " ".join(query.split())
        self.executed.append((normalized, params))
        if normalized.startswith("UPDATE task_with_examples"):
            self.rowcount = self.update_rowcounts.pop(0) if self.update_rowcounts else 1

    def fetchone(self):
        return self.fetchone_results.pop(0) if self.fetchone_results else None

    def fetchall(self):
        return self.fetchall_result

    def close(self):
        return None


class ScriptedConnection:
    def __init__(self, cursors):
        self.cursors = list(cursors)
        self.committed = False

    def cursor(self, *args, **kwargs):
        return self.cursors.pop(0)

    def commit(self):
        self.committed = True

    def close(self):
        return None

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        return False


class TaskIdentityOperationsTestCase(unittest.TestCase):
    def test_reorder_requires_exact_active_owned_id_set(self):
        cursor = ScriptedCursor(fetchall_result=[(1,), (2,)])
        connection = ScriptedConnection([cursor])

        with patch("blueprints.chat.tasks.get_db_connection", return_value=connection):
            with self.assertRaises(ApiServiceError) as raised:
                _update_tasks_order_for_user(7, [1])

        self.assertEqual(raised.exception.status_code, 400)
        self.assertFalse(connection.committed)
        self.assertFalse(any(query.startswith("UPDATE") for query, _ in cursor.executed))

    def test_reorder_updates_each_owned_id_once_in_one_transaction(self):
        cursor = ScriptedCursor(fetchall_result=[(8,), (3,)], update_rowcounts=[1, 1])
        connection = ScriptedConnection([cursor])

        with patch("blueprints.chat.tasks.get_db_connection", return_value=connection):
            _update_tasks_order_for_user(7, [3, 8])

        updates = [(query, params) for query, params in cursor.executed if query.startswith("UPDATE")]
        self.assertEqual([params for _, params in updates], [(0, 3, 7), (1, 8, 7)])
        self.assertTrue(connection.committed)

    def test_delete_missing_or_foreign_task_is_not_reported_as_success(self):
        cursor = ScriptedCursor(update_rowcounts=[0])
        connection = ScriptedConnection([cursor])

        with patch("blueprints.chat.tasks.get_db_connection", return_value=connection):
            with self.assertRaises(ResourceNotFoundError):
                _delete_task_for_user(7, 99)

        self.assertFalse(connection.committed)

    def test_add_rejects_case_insensitive_trimmed_duplicate(self):
        cursor = ScriptedCursor(fetchone_results=[(1,)])
        connection = ScriptedConnection([cursor])

        with patch("blueprints.chat.tasks.get_db_connection", return_value=connection):
            with self.assertRaises(ApiServiceError) as raised:
                _add_task_for_user(7, " Existing ", "prompt", "", "", "", "")

        self.assertEqual(raised.exception.status_code, 409)
        self.assertFalse(connection.committed)

    def test_add_appends_after_current_max_order(self):
        cursor = ScriptedCursor(fetchone_results=[None, (12,)])
        connection = ScriptedConnection([cursor])

        with patch("blueprints.chat.tasks.get_db_connection", return_value=connection):
            _add_task_for_user(7, "New", "prompt", "", "", "", "")

        insert = next((params for query, params in cursor.executed if query.startswith("INSERT")), None)
        self.assertIsNotNone(insert)
        self.assertEqual(insert[-1], 12)
        self.assertTrue(connection.committed)

    def test_edit_uses_id_and_preserves_omitted_nullable_fields(self):
        select_cursor = ScriptedCursor(fetchone_results=[(42,), None])
        update_cursor = ScriptedCursor(update_rowcounts=[1])
        connection = ScriptedConnection([select_cursor, update_cursor])

        with patch("blueprints.chat.tasks.get_db_connection", return_value=connection):
            _edit_task_for_user(7, 42, "Renamed", None, None, None, None, None)

        update_query, params = update_cursor.executed[0]
        self.assertIn("COALESCE(%s, prompt_template)", update_query)
        self.assertIn("is_system_task_customized", update_query)
        self.assertEqual(params[-2:], (42, 7))
        self.assertTrue(connection.committed)

    def test_delete_route_serializes_service_error(self):
        request = build_request(
            method="POST",
            path="/api/delete_task",
            session={"user_id": 7},
            json_body={"task_id": 99},
        )
        with patch(
            "blueprints.chat.tasks._delete_task_for_user",
            side_effect=ResourceNotFoundError("missing", code="task_not_found"),
        ):
            response = asyncio.run(delete_task(request))

        self.assertEqual(response.status_code, 404)
        self.assertEqual(json.loads(response.body)["code"], "task_not_found")

    def test_task_launch_parser_accepts_optional_positive_task_id(self):
        parsed = _parse_task_launch_message(
            "【タスク】同名タスク\n【タスクID】42\n【状況・作業環境】テスト"
        )
        self.assertEqual(parsed, {"task": "同名タスク", "task_id": 42, "setup_info": "テスト"})

    def test_task_launch_loader_passes_id_to_repository_lookup(self):
        with patch("blueprints.chat.messages._fetch_prompt_data", return_value={"name": "Task"}) as fetch:
            result = asyncio.run(_load_task_prompt_data("Task", 7, 42))

        self.assertEqual(result, {"name": "Task"})
        fetch.assert_called_once_with("Task", 7, 42)

    def test_repository_task_id_lookup_is_scoped_to_owner(self):
        row = {
            "task_id": 42,
            "system_task_key": None,
            "is_system_task_customized": False,
            "name": "Same name",
            "prompt_template": "owned prompt",
            "response_rules": "",
            "output_skeleton": "",
            "input_examples": "",
            "output_examples": "",
        }
        cursor = ScriptedCursor(fetchone_results=[row])
        connection = ScriptedConnection([cursor])
        repository = ChatRepository(connection_getter=lambda: connection)

        result = repository.get_task_prompt_data("Same name", 7, 42)

        query, params = cursor.executed[0]
        self.assertIn("WHERE id = %s", query)
        self.assertIn("AND user_id = %s", query)
        self.assertEqual(params, (42, 7))
        self.assertEqual(result["prompt_template"], "owned prompt")


if __name__ == "__main__":
    unittest.main()
