import asyncio
import json
import unittest
from unittest.mock import patch

from blueprints.prompt_share.prompt_share_api import (
    _add_prompt_as_task_for_user,
    _compose_task_prompt_template,
    _remove_prompt_as_task_for_user,
    add_prompt_as_task,
    remove_prompt_as_task,
)
from tests.helpers.request_helpers import build_request


# プロンプトをチャットで使うためのAPIテスト用HTTPリクエストを構築します。
# Build a mock HTTP request for testing prompt use-in-chat API endpoints.
def make_request(method, path, payload, session=None):
    return build_request(
        method=method,
        path=path,
        json_body=payload,
        session=session,
    )


class ScriptedCursor:
    def __init__(self, fetchone_results, *, rowcount=1):
        self.fetchone_results = list(fetchone_results)
        self.executed = []
        self.rowcount = rowcount

    def execute(self, query, params=None):
        self.executed.append((" ".join(query.split()), params))

    def fetchone(self):
        return self.fetchone_results.pop(0) if self.fetchone_results else None

    def close(self):
        return None


class ScriptedConnection:
    def __init__(self, cursor):
        self.cursor_instance = cursor
        self.committed = False
        self.rolled_back = False

    def cursor(self, *args, **kwargs):
        return self.cursor_instance

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        return None


class PromptUseInChatApiTestCase(unittest.TestCase):
    # 共有プロンプトを「チャットで使う」ための追加処理が、専用のエンドポイントを通じて実行できることを検証します。
    # Verify that adding a prompt for chat use goes through the dedicated task-creation endpoint.
    def test_add_prompt_as_task_uses_separate_endpoint(self):
        request = make_request(
            "POST",
            "/prompt_share/api/task",
            {"prompt_id": 10},
            session={"user_id": 5},
        )

        # タスク追加ヘルパーの戻り値をモック
        # Mock the helper response for adding a prompt as a task
        with patch(
            "blueprints.prompt_share.prompt_share_api._add_prompt_as_task_for_user",
            return_value=({"message": "チャットで使えるように追加しました。", "used_in_chat": True}, 201),
        ) as mock_add:
            response = asyncio.run(add_prompt_as_task(request))

        self.assertEqual(response.status_code, 201)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertTrue(payload["used_in_chat"])
        mock_add.assert_called_once_with(5, 10)

    # 共有プロンプトの「チャットで使う」状態を解除する処理が、専用エンドポイントから実行できることを検証します。
    # Verify that removing a prompt from chat use goes through the dedicated task-removal endpoint.
    def test_remove_prompt_as_task_uses_separate_endpoint(self):
        request = make_request(
            "DELETE",
            "/prompt_share/api/task",
            {"prompt_id": 10},
            session={"user_id": 5},
        )

        with patch(
            "blueprints.prompt_share.prompt_share_api._remove_prompt_as_task_for_user",
            return_value=({"message": "チャットで使う設定を解除しました。", "used_in_chat": False}, 200),
        ) as mock_remove:
            response = asyncio.run(remove_prompt_as_task(request))

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertFalse(payload["used_in_chat"])
        mock_remove.assert_called_once_with(5, 10)

    def test_prompt_import_does_not_claim_same_title_custom_task(self):
        prompt = {
            "title": "Same title",
            "content": "Shared body",
            "input_examples": "",
            "output_examples": "",
            "content_format": "prompt",
            "media_type": "text",
            "attributes": {},
            "resources": [],
        }
        cursor = ScriptedCursor(
            [
                prompt,
                None,  # no task with this source_prompt_id
                (1,),  # the plain title belongs to a custom task
                None,  # suffixed name is available
                {"next_display_order": 4},
                {"id": 44},
            ]
        )
        connection = ScriptedConnection(cursor)

        with patch(
            "blueprints.prompt_share.prompt_share_api.get_db_connection",
            return_value=connection,
        ):
            payload, status = _add_prompt_as_task_for_user(5, 10)

        self.assertEqual(status, 201)
        self.assertEqual(payload["saved_id"], 44)
        source_query = next(
            query
            for query, _ in cursor.executed
            if "SELECT id FROM task_with_examples" in query and "source_prompt_id" in query
        )
        self.assertNotIn("name = %s", source_query)
        insert_query, insert_params = next(
            (query, params)
            for query, params in cursor.executed
            if "INSERT INTO task_with_examples" in query
        )
        self.assertIn("ON CONFLICT DO NOTHING", insert_query)
        self.assertEqual(insert_params[2], "Same title (2)")
        self.assertEqual(insert_params[-1], 4)
        self.assertTrue(connection.committed)

    def test_prompt_removal_targets_only_one_exact_source(self):
        cursor = ScriptedCursor([], rowcount=1)
        connection = ScriptedConnection(cursor)

        with patch(
            "blueprints.prompt_share.prompt_share_api.get_db_connection",
            return_value=connection,
        ):
            payload, status = _remove_prompt_as_task_for_user(5, 10)

        self.assertEqual(status, 200)
        self.assertFalse(payload["used_in_chat"])
        query, params = cursor.executed[0]
        self.assertIn("source_prompt_id = %s", query)
        self.assertIn("ORDER BY id ASC LIMIT 1", query)
        self.assertNotIn("name = %s", query)
        self.assertEqual(params, (5, 10))

    # SKILLからタスク用テンプレートを生成する際、Markdownと複数の名前付きリソースを維持することを検証します。
    # Verify that composing a task template preserves Markdown and named resources.
    def test_compose_task_prompt_template_keeps_skill_body_and_resources(self):
        template = _compose_task_prompt_template(
            {
                "content_format": "skill",
                "content": "",
                "attributes": {"skill_markdown": "# SKILL\n\n使い方"},
                "resources": [
                    {
                        "path": "scripts/main.py",
                        "role": "script",
                        "language": "python",
                        "content": "print('hello')",
                    },
                    {
                        "path": "config/example.json",
                        "role": "config",
                        "language": "json",
                        "content": '{"enabled": true}',
                    },
                ],
            }
        )

        self.assertIn("# SKILL", template)
        self.assertIn("## Resource: `scripts/main.py`", template)
        self.assertIn("```python\nprint('hello')\n```", template)
        self.assertIn("## Resource: `config/example.json`", template)
        self.assertIn('```json\n{"enabled": true}\n```', template)

    def test_compose_task_prompt_template_uses_safe_longer_fence(self):
        template = _compose_task_prompt_template(
            {
                "content_format": "skill",
                "attributes": {"skill_markdown": "# SKILL"},
                "resources": [
                    {
                        "path": "references/fences.md",
                        "language": "markdown",
                        "content": "```python\nprint('nested')\n```",
                    }
                ],
            }
        )

        self.assertIn("````markdown", template)
        self.assertIn("```python", template)


if __name__ == "__main__":
    unittest.main()
