import unittest
from datetime import datetime

from services.shared_content_service import (
    InvalidSharedContentCursor,
    SHARED_CONTENT_MAX_LIMIT,
    SHARED_CONTENT_SNIPPET_LENGTH,
    SharedContentService,
)


class _Repository:
    def __init__(self, *, rows=None, has_next=False, detail=None):
        self.rows = rows or []
        self.has_next = has_next
        self.detail = detail
        self.calls = []

    async def list_public_content(self, session, **kwargs):
        self.calls.append(("list", session, kwargs))
        return self.rows, self.has_next

    async def get_public_content(self, session, prompt_id):
        self.calls.append(("detail", session, prompt_id))
        return self.detail


class _ResourceRepository:
    def __init__(self, resources=None):
        self.resources = resources or []
        self.calls = []

    async def list_for_prompt(self, session, prompt_id):
        self.calls.append(("list", session, prompt_id))
        return self.resources

    async def get_for_prompt(self, session, prompt_id, path):
        self.calls.append(("get", session, prompt_id, path))
        return next((item for item in self.resources if item["path"] == path), None)


class SharedContentServiceTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_list_normalizes_filters_clamps_limit_and_returns_bounded_snippets(self):
        created_at = datetime(2026, 7, 16, 12, 0, 0)
        repository = _Repository(
            rows=[
                {
                    "id": 21,
                    "title": "Skill helper",
                    "category": "business",
                    "description": "説明文",
                    "author": "tester",
                    "content_format": "skill",
                    "media_type": "text",
                    "snippet_source": "  line one\n\n" + "x" * 400,
                    "created_at": created_at,
                }
            ],
            has_next=True,
        )
        service = SharedContentService(
            public_base_url="https://example.com/",
            repository=repository,
        )

        page = await service.list_public_content(
            query="  Skill  ",
            limit=500,
            category="仕事",
            content_format="SKILL",
            media_type="TEXT",
            session=object(),
        )

        self.assertEqual(page.limit, SHARED_CONTENT_MAX_LIMIT)
        self.assertTrue(page.has_next)
        self.assertIsNotNone(page.next_cursor)
        self.assertLessEqual(len(page.items[0].snippet), SHARED_CONTENT_SNIPPET_LENGTH)
        call = repository.calls[0][2]
        self.assertEqual(call["query"], "Skill")
        self.assertEqual(call["category"], "business")
        self.assertEqual(call["limit"], SHARED_CONTENT_MAX_LIMIT)

    async def test_cursor_is_bound_to_search_filters(self):
        created_at = datetime(2026, 7, 16, 12, 0, 0)
        repository = _Repository(
            rows=[
                {
                    "id": 21,
                    "title": "one",
                    "category": "coding",
                    "content_format": "skill",
                    "media_type": "text",
                    "snippet_source": "body",
                    "created_at": created_at,
                }
            ],
            has_next=True,
        )
        service = SharedContentService(public_base_url="https://example.com", repository=repository)
        first = await service.list_public_content(query="helper", category="coding", session=object())
        second = await service.list_public_content(
            query="helper",
            category="coding",
            cursor=first.next_cursor,
            session=object(),
        )
        self.assertEqual(repository.calls[-1][2]["cursor"], (created_at, 21))
        self.assertIsNotNone(second)
        with self.assertRaises(InvalidSharedContentCursor):
            await service.list_public_content(query="different", category="coding", cursor=first.next_cursor, session=object())

    async def test_detail_loads_resource_metadata_and_legacy_script_from_same_session(self):
        session = object()
        repository = _Repository(
            detail={
                "id": 31,
                "title": "Git Skill",
                "content": "",
                "category": "coding",
                "content_format": "skill",
                "media_type": "text",
                "attributes": {"skill_markdown": "# Git"},
                "attachments": [],
                "created_at": datetime(2026, 7, 16, 12, 0, 0),
            }
        )
        resources = _ResourceRepository(
            [{
                "path": "scripts/main.py",
                "role": "script",
                "language": "python",
                "media_type": "text/x-python",
                "text_content": "print(1)",
                "size_bytes": 8,
                "sha256": "abc",
            }]
        )
        service = SharedContentService(
            public_base_url="https://example.com",
            repository=repository,
            resource_repository=resources,
        )

        detail = await service.get_public_content(31, session=session)

        self.assertEqual(detail.skill_markdown, "# Git")
        self.assertEqual(detail.skill_python_script, "print(1)")
        self.assertEqual(detail.resources[0].path, "scripts/main.py")
        self.assertEqual({call[1] for call in resources.calls}, {session})

    async def test_blank_query_is_rejected_before_database_access(self):
        repository = _Repository()
        service = SharedContentService(public_base_url="https://example.com", repository=repository)
        with self.assertRaises(ValueError):
            await service.list_public_content(query="   ", session=object())
        self.assertEqual(repository.calls, [])


if __name__ == "__main__":
    unittest.main()
