import unittest
from datetime import datetime

from services.repositories.shared_content_repository import (
    SNIPPET_SOURCE_MAX_LENGTH,
    SharedContentRepository,
)
from services.shared_content_service import (
    InvalidSharedContentCursor,
    SHARED_CONTENT_MAX_LIMIT,
    SHARED_CONTENT_SNIPPET_LENGTH,
    SharedContentService,
)


class FakeCursor:
    def __init__(self, *, rows=None, row=None):
        self.rows = list(rows or [])
        self.row = row
        self.executed = []
        self.closed = False

    def execute(self, query, params=None):
        self.executed.append((" ".join(query.split()), params))

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.row

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


class SharedContentRepositoryTestCase(unittest.TestCase):
    def test_list_searches_public_skill_markdown_with_stable_cursor_and_closes_db(self):
        rows = [
            {"id": 9, "title": "one"},
            {"id": 8, "title": "two"},
            {"id": 7, "title": "extra"},
        ]
        cursor = FakeCursor(rows=rows)
        connection = FakeConnection(cursor)
        repository = SharedContentRepository(connection_getter=lambda: connection)
        created_at = datetime(2026, 7, 16, 12, 0, 0)

        result, has_next = repository.list_public_content(
            limit=2,
            cursor=(created_at, 10),
            query="helper",
            category="coding",
            content_format="skill",
            media_type="text",
            matching_category_keys=["coding"],
        )

        self.assertEqual(result, rows[:2])
        self.assertTrue(has_next)
        sql, params = cursor.executed[0]
        self.assertIn("p.is_public = TRUE", sql)
        self.assertIn("p.deleted_at IS NULL", sql)
        self.assertIn("p.attributes->>'skill_markdown'", sql)
        self.assertIn("p.title ILIKE %s", sql)
        self.assertIn("p.content ILIKE %s", sql)
        self.assertIn("p.category ILIKE %s", sql)
        self.assertIn("p.author ILIKE %s", sql)
        self.assertIn("u.username ILIKE %s", sql)
        self.assertIn("(p.created_at, p.id) < (%s, %s)", sql)
        self.assertIn("ORDER BY p.created_at DESC, p.id DESC", sql)
        self.assertIn("AS snippet_source", sql)
        self.assertNotIn("p.input_examples", sql)
        self.assertEqual(params[:4], (SNIPPET_SOURCE_MAX_LENGTH, "coding", "skill", "text"))
        self.assertEqual(params[4:11], (
            "%helper%",
            "%helper%",
            "%helper%",
            ["coding"],
            "%helper%",
            "%helper%",
            "%helper%",
        ))
        self.assertEqual(params[11:13], (created_at, 10))
        self.assertEqual(params[-1], 3)
        self.assertTrue(cursor.closed)
        self.assertTrue(connection.closed)

    def test_search_escapes_like_wildcards_and_limits_skill_expression(self):
        cursor = FakeCursor(rows=[])
        connection = FakeConnection(cursor)
        repository = SharedContentRepository(connection_getter=lambda: connection)

        repository.list_public_content(limit=20, query=r"100%_done\now")

        sql, params = cursor.executed[0]
        self.assertIn("p.content_format = 'skill'", sql)
        self.assertIn("ESCAPE", sql)
        self.assertEqual(params[1], r"%100\%\_done\\now%")

    def test_detail_is_parameterized_and_restricted_to_visible_content(self):
        row = {"id": 12, "title": "detail"}
        cursor = FakeCursor(row=row)
        connection = FakeConnection(cursor)
        repository = SharedContentRepository(connection_getter=lambda: connection)

        result = repository.get_public_content(12)

        self.assertEqual(result, row)
        sql, params = cursor.executed[0]
        self.assertIn("WHERE p.id = %s", sql)
        self.assertIn("p.is_public = TRUE", sql)
        self.assertIn("p.deleted_at IS NULL", sql)
        self.assertIn("p.attributes", sql)
        self.assertIn("p.updated_at", sql)
        self.assertEqual(params, (12,))
        self.assertTrue(cursor.closed)
        self.assertTrue(connection.closed)


class StubSharedContentRepository:
    def __init__(self, *, rows=None, has_next=False, detail=None):
        self.rows = list(rows or [])
        self.has_next = has_next
        self.detail = detail
        self.list_calls = []
        self.detail_calls = []

    def list_public_content(self, **kwargs):
        self.list_calls.append(kwargs)
        return self.rows, self.has_next

    def get_public_content(self, prompt_id):
        self.detail_calls.append(prompt_id)
        return self.detail


class StubPromptResourceRepository:
    def __init__(self, *, resources=None):
        self.resources = list(resources or [])
        self.list_calls = []
        self.get_calls = []

    def list_for_prompt(self, prompt_id):
        self.list_calls.append(prompt_id)
        return self.resources

    def get_for_prompt(self, prompt_id, path):
        self.get_calls.append((prompt_id, path))
        return next(
            (resource for resource in self.resources if resource["path"] == path),
            None,
        )


class SharedContentServiceTestCase(unittest.TestCase):
    def test_list_normalizes_filters_clamps_limit_and_returns_bounded_snippets(self):
        created_at = datetime(2026, 7, 16, 12, 0, 0)
        repository = StubSharedContentRepository(
            rows=[
                {
                    "id": 21,
                    "title": "Skill helper",
                    "category": "business",
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

        page = service.list_public_content(
            query="  Skill  ",
            limit=500,
            category="仕事",
            content_format="SKILL",
            media_type="TEXT",
        )

        self.assertEqual(page.limit, SHARED_CONTENT_MAX_LIMIT)
        self.assertTrue(page.has_next)
        self.assertIsNotNone(page.next_cursor)
        self.assertEqual(len(page.items), 1)
        item = page.items[0]
        self.assertEqual(item.prompt_id, 21)
        self.assertEqual(str(item.public_url), "https://example.com/shared/prompt/21")
        self.assertNotIn("\n", item.snippet)
        self.assertLessEqual(len(item.snippet), SHARED_CONTENT_SNIPPET_LENGTH)
        self.assertTrue(item.snippet.endswith("…"))

        call = repository.list_calls[0]
        self.assertEqual(call["query"], "Skill")
        self.assertEqual(call["limit"], SHARED_CONTENT_MAX_LIMIT)
        self.assertEqual(call["category"], "business")
        self.assertEqual(call["content_format"], "skill")
        self.assertEqual(call["media_type"], "text")

    def test_cursor_round_trip_is_bound_to_search_filters(self):
        created_at = datetime(2026, 7, 16, 12, 0, 0)
        first_repository = StubSharedContentRepository(
            rows=[
                {
                    "id": 21,
                    "title": "one",
                    "category": "coding",
                    "author": "tester",
                    "content_format": "skill",
                    "media_type": "text",
                    "snippet_source": "body",
                    "created_at": created_at,
                }
            ],
            has_next=True,
        )
        first_service = SharedContentService(
            public_base_url="https://example.com",
            repository=first_repository,
        )
        first_page = first_service.list_public_content(
            query="helper",
            category="coding",
            content_format="skill",
        )

        second_repository = StubSharedContentRepository()
        second_service = SharedContentService(
            public_base_url="https://example.com",
            repository=second_repository,
        )
        second_service.list_public_content(
            query="helper",
            category="coding",
            content_format="skill",
            cursor=first_page.next_cursor,
        )
        self.assertEqual(
            second_repository.list_calls[0]["cursor"],
            (created_at, 21),
        )

        with self.assertRaises(InvalidSharedContentCursor):
            second_service.list_public_content(
                query="different",
                category="coding",
                content_format="skill",
                cursor=first_page.next_cursor,
            )

    def test_detail_returns_full_skill_attributes_and_public_url(self):
        created_at = datetime(2026, 7, 16, 12, 0, 0)
        updated_at = datetime(2026, 7, 16, 13, 0, 0)
        repository = StubSharedContentRepository(
            detail={
                "id": 31,
                "title": "Git Skill",
                "category": "coding",
                "content": "",
                "author": "tester",
                "content_format": "skill",
                "media_type": "text",
                "attributes": {
                    "skill_markdown": "# Git Skill\n\nFull instructions",
                    "skill_python_script": "print('safe string only')",
                },
                "attachments": [],
                "input_examples": None,
                "output_examples": None,
                "ai_model": "model-name",
                "created_at": created_at,
                "updated_at": updated_at,
            }
        )
        resource_repository = StubPromptResourceRepository(
            resources=[
                {
                    "path": "scripts/main.py",
                    "role": "script",
                    "language": "python",
                    "media_type": "text/x-python",
                    "text_content": "print('derived resource')",
                    "size_bytes": 25,
                    "sha256": "abc123",
                }
            ]
        )
        service = SharedContentService(
            public_base_url="https://example.com",
            repository=repository,
            resource_repository=resource_repository,
        )

        detail = service.get_public_content(31)

        self.assertIsNotNone(detail)
        self.assertEqual(detail.skill_markdown, "# Git Skill\n\nFull instructions")
        self.assertEqual(detail.skill_python_script, "print('derived resource')")
        self.assertEqual(len(detail.resources), 1)
        self.assertEqual(detail.resources[0].path, "scripts/main.py")
        self.assertNotIn("content", detail.resources[0].model_dump())
        self.assertNotIn("attributes", detail.model_dump())
        self.assertEqual(detail.input_examples, "")
        self.assertEqual(detail.updated_at, updated_at)
        self.assertEqual(str(detail.public_url), "https://example.com/shared/prompt/31")
        self.assertEqual(repository.detail_calls, [31])
        self.assertEqual(resource_repository.list_calls, [31])
        self.assertEqual(resource_repository.get_calls, [(31, "scripts/main.py")])

    def test_skill_resources_are_listed_without_content_and_loaded_by_path(self):
        repository = StubSharedContentRepository(
            detail={
                "id": 44,
                "title": "Multi-file Skill",
                "content_format": "skill",
                "media_type": "text",
                "attributes": {"skill_markdown": "# Skill"},
                "created_at": datetime(2026, 7, 16, 12, 0, 0),
            }
        )
        resource_repository = StubPromptResourceRepository(
            resources=[
                {
                    "path": "references/api.md",
                    "role": "reference",
                    "language": "markdown",
                    "media_type": "text/markdown",
                    "text_content": "0123456789",
                    "size_bytes": 10,
                    "sha256": "hash",
                }
            ]
        )
        service = SharedContentService(
            public_base_url="https://example.com",
            repository=repository,
            resource_repository=resource_repository,
        )

        resources = service.list_public_skill_resources(44)
        resource = service.get_public_skill_resource(44, "references/api.md")

        self.assertEqual([item.path for item in resources], ["references/api.md"])
        self.assertNotIn("content", resources[0].model_dump())
        self.assertEqual(resource.content, "0123456789")
        self.assertEqual(resource.role, "reference")
        self.assertEqual(repository.detail_calls, [44, 44])

    def test_skill_resource_lookup_rejects_non_skill_posts(self):
        repository = StubSharedContentRepository(
            detail={
                "id": 45,
                "title": "Prompt",
                "content": "text",
                "content_format": "prompt",
                "media_type": "text",
                "created_at": datetime(2026, 7, 16, 12, 0, 0),
            }
        )
        service = SharedContentService(
            public_base_url="https://example.com",
            repository=repository,
            resource_repository=StubPromptResourceRepository(),
        )

        with self.assertRaisesRegex(ValueError, "SKILLではありません"):
            service.list_public_skill_resources(45)

    def test_detail_returns_none_for_invisible_or_missing_content(self):
        repository = StubSharedContentRepository(detail=None)
        service = SharedContentService(
            public_base_url="https://example.com",
            repository=repository,
        )

        self.assertIsNone(service.get_public_content(999))
        with self.assertRaises(ValueError):
            service.get_public_content(0)

    def test_search_rejects_a_blank_query(self):
        service = SharedContentService(
            public_base_url="https://example.com",
            repository=StubSharedContentRepository(),
        )

        with self.assertRaises(ValueError):
            service.list_public_content(query="   ")


if __name__ == "__main__":
    unittest.main()
