import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from blueprints.prompt_share.prompt_share_api import (
    _get_public_prompt_by_id,
    record_prompt_view,
)
from services.repositories.prompt_view_repository import PromptViewRepository


class PromptViewCountTestCase(unittest.TestCase):
    def test_prompt_detail_returns_current_view_count_without_incrementing_it(self):
        with patch(
            "blueprints.prompt_share.prompt_share_api._service",
        ) as service_factory:
            service = service_factory.return_value
            service.get_public_prompt_detail = AsyncMock(
                return_value={
                    "id": 42,
                    "title": "Prompt",
                    "content": "Body",
                    "content_format": "prompt",
                    "media_type": "text",
                    "view_count": 5,
                }
            )
            prompt = asyncio.run(_get_public_prompt_by_id(42))

        self.assertEqual(prompt["view_count"], 5)
        service.get_public_prompt_detail.assert_awaited_once_with(42)

    def test_record_view_atomically_upserts_for_an_active_public_prompt(self):
        session = MagicMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = 6
        session.execute = AsyncMock(return_value=result)

        view_count = asyncio.run(PromptViewRepository().increment_public_view(session, 42))

        self.assertEqual(view_count, 6)
        statement = session.execute.call_args.args[0]
        sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
        self.assertIn("ON CONFLICT", sql)
        self.assertIn("RETURNING", sql)
        self.assertIn("prompts.is_public", sql)
        self.assertIn("prompts.deleted_at", sql)

    def test_record_view_does_not_commit_when_prompt_is_not_public_and_active(self):
        session = MagicMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=result)

        view_count = asyncio.run(PromptViewRepository().increment_public_view(session, 99))

        self.assertIsNone(view_count)
        session.commit.assert_not_called()
        session.rollback.assert_not_called()

    def test_record_view_endpoint_returns_incremented_count(self):
        service = MagicMock()
        service.record_public_view = AsyncMock(return_value=8)
        with patch(
            "blueprints.prompt_share.prompt_share_api._service",
            return_value=service,
        ):
            response = asyncio.run(record_prompt_view(42))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.body.decode("utf-8"))["view_count"], 8)
        service.record_public_view.assert_awaited_once_with(42)

    def test_record_view_endpoint_returns_404_for_unavailable_prompt(self):
        service = MagicMock()
        service.record_public_view = AsyncMock(return_value=None)
        with patch("blueprints.prompt_share.prompt_share_api._service", return_value=service):
            response = asyncio.run(record_prompt_view(99))

        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
