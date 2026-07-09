import unittest
from unittest.mock import patch

from blueprints.memo.repository import fetch_memo_summaries


class FakeCursor:
    def __init__(self):
        self.executed = []
        self.closed = False
        self._fetchone_result = None
        self._fetchall_result = []

    def execute(self, query, params=None):
        normalized = " ".join(query.split())
        self.executed.append((normalized, params))
        if "COUNT(*) AS total_count" in normalized:
            self._fetchone_result = {"total_count": 900}
        elif "embedding_vector <=>" in normalized:
            self._fetchall_result = [
                {
                    "id": 1,
                    "title": "Semantic result",
                    "created_at": None,
                    "updated_at": None,
                    "archived_at": None,
                    "pinned_at": None,
                    "preview_response": "body",
                    "collection_id": None,
                    "background_color": None,
                    "collection_name": None,
                    "collection_color": None,
                    "share_token": None,
                    "expires_at": None,
                    "revoked_at": None,
                }
            ]

    def fetchone(self):
        return self._fetchone_result

    def fetchall(self):
        return self._fetchall_result

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self, cursor):
        self.cursor_instance = cursor
        self.closed = False

    def cursor(self, *args, **kwargs):
        return self.cursor_instance

    def close(self):
        self.closed = True


class MemoSearchRepositoryTestCase(unittest.TestCase):
    def test_semantic_search_uses_pgvector_with_database_pagination(self):
        cursor = FakeCursor()
        connection = FakeConnection(cursor)

        with patch(
            "blueprints.memo.repository._get_db_connection",
            return_value=connection,
        ):
            result = fetch_memo_summaries(
                7,
                limit=20,
                offset=400,
                query="architecture",
                date_from="",
                date_to="",
                sort="recent",
                include_archived=False,
                only_archived=False,
                pinned_first=True,
                collection_id=None,
                semantic_query_embedding=[0.1, 0.2, 0.3],
            )

        self.assertEqual(result["total"], 900)
        self.assertEqual(result["memos"][0]["id"], 1)
        self.assertEqual(len(cursor.executed), 2)

        semantic_query, semantic_params = cursor.executed[1]
        self.assertIn("embedding_vector <=> %s::vector", semantic_query)
        self.assertNotIn("SEMANTIC_SEARCH_MAX_MEMOS", semantic_query)
        self.assertNotIn("me.embedding,", semantic_query)
        self.assertEqual(semantic_params[-3:], ("[0.1,0.2,0.3]", 20, 400))
        self.assertTrue(cursor.closed)
        self.assertTrue(connection.closed)


if __name__ == "__main__":
    unittest.main()
