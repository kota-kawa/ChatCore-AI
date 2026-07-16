import unittest
from unittest.mock import patch

from blueprints.memo.embeddings import store_embedding


class FakeCursor:
    def __init__(self):
        self.executed = []
        self.closed = False

    def execute(self, query, params):
        self.executed.append((" ".join(query.split()), params))

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self, cursor):
        self.cursor_instance = cursor
        self.committed = False
        self.closed = False

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.committed = True

    def close(self):
        self.closed = True


class MemoEmbeddingRevisionTestCase(unittest.TestCase):
    def test_store_embedding_rejects_stale_background_results(self):
        cursor = FakeCursor()
        connection = FakeConnection(cursor)
        with patch("blueprints.memo.embeddings._get_db_connection", return_value=connection):
            store_embedding(9, [0.1, 0.2], expected_revision=4)

        sql, params = cursor.executed[0]
        self.assertIn("WHERE id = %s AND revision = %s", sql)
        self.assertEqual(params[-2:], (9, 4))
        self.assertTrue(connection.committed)
        self.assertTrue(cursor.closed)
        self.assertTrue(connection.closed)


if __name__ == "__main__":
    unittest.main()
