import unittest
from datetime import datetime

from services.api_errors import ForbiddenOperationError, ResourceNotFoundError
from services.repositories.project_repository import ProjectRepository


# スクリプト化した fetch 結果を順に返す疑似カーソル。
# Mock cursor that returns scripted fetchone/fetchall results in order.
class FakeCursor:
    def __init__(self, fetchone_results=None, fetchall_results=None):
        self._fetchone = list(fetchone_results or [])
        self._fetchall = list(fetchall_results or [])
        self.executed = []
        self.closed = False

    def execute(self, query, params=None):
        self.executed.append((query, params))

    def fetchone(self):
        return self._fetchone.pop(0) if self._fetchone else None

    def fetchall(self):
        return self._fetchall.pop(0) if self._fetchall else []

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False
        self.rolled_back = False

    def cursor(self):
        return self._cursor

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        return False


def _make_repo(cursor):
    connection = FakeConnection(cursor)
    repo = ProjectRepository(
        connection_getter=lambda: connection,
        retryable_error_checker=lambda exc: False,
        rollback=lambda conn: conn.rollback() or True,
        sleep=lambda _seconds: None,
    )
    return repo, connection


class ProjectRepositoryTestCase(unittest.TestCase):
    def test_create_project_returns_serialized_row(self):
        now = datetime(2026, 6, 21, 12, 0, 0)
        cursor = FakeCursor(fetchone_results=[(7, "リサーチ", "丁寧に", now, now)])
        repo, connection = _make_repo(cursor)

        project = repo.create_project(user_id=1, name="リサーチ", instructions="丁寧に")

        self.assertEqual(project["id"], 7)
        self.assertEqual(project["name"], "リサーチ")
        self.assertEqual(project["instructions"], "丁寧に")
        self.assertTrue(connection.committed)
        self.assertTrue(cursor.closed)

    def test_create_project_normalizes_blank_name(self):
        now = datetime(2026, 6, 21, 12, 0, 0)
        cursor = FakeCursor(fetchone_results=[(7, "新規プロジェクト", None, now, now)])
        repo, _ = _make_repo(cursor)

        repo.create_project(user_id=1, name="   ", instructions=None)

        # INSERT に渡された name が既定値へ正規化されていること。
        insert_params = cursor.executed[0][1]
        self.assertEqual(insert_params[1], "新規プロジェクト")

    def test_get_project_raises_404_when_missing(self):
        cursor = FakeCursor(fetchone_results=[None])
        repo, _ = _make_repo(cursor)

        with self.assertRaises(ResourceNotFoundError):
            repo.get_project(project_id=5, user_id=1)

    def test_get_project_raises_403_for_other_user(self):
        now = datetime(2026, 6, 21, 12, 0, 0)
        # user_id (idx 5) が 99 で、リクエストユーザー 1 と不一致。
        cursor = FakeCursor(fetchone_results=[(5, "P", "instr", now, now, 99)])
        repo, _ = _make_repo(cursor)

        with self.assertRaises(ForbiddenOperationError):
            repo.get_project(project_id=5, user_id=1)

    def test_get_project_includes_rooms(self):
        now = datetime(2026, 6, 21, 12, 0, 0)
        cursor = FakeCursor(
            fetchone_results=[(5, "P", "instr", now, now, 1)],
            fetchall_results=[
                [("room-1", "設計", "normal", now)],  # rooms
            ],
        )
        repo, _ = _make_repo(cursor)

        project = repo.get_project(project_id=5, user_id=1)

        self.assertNotIn("files", project)
        self.assertEqual(len(project["rooms"]), 1)
        self.assertEqual(project["rooms"][0]["id"], "room-1")

    def test_delete_project_checks_ownership(self):
        cursor = FakeCursor(fetchone_results=[(99,)])  # owner is user 99
        repo, _ = _make_repo(cursor)

        with self.assertRaises(ForbiddenOperationError):
            repo.delete_project(project_id=5, user_id=1)

    def test_assign_room_to_project_raises_404_when_room_missing(self):
        cursor = FakeCursor(fetchone_results=[None])
        repo, _ = _make_repo(cursor)

        with self.assertRaises(ResourceNotFoundError):
            repo.assign_room_to_project(room_id="missing", user_id=1, project_id=5)

    def test_get_project_context_returns_none_when_unassigned(self):
        cursor = FakeCursor(fetchone_results=[None])
        repo, _ = _make_repo(cursor)

        self.assertIsNone(repo.get_project_context("room-1"))

    def test_get_project_context_returns_instructions(self):
        cursor = FakeCursor(
            fetchone_results=[(5, "P", "従ってください")],
        )
        repo, _ = _make_repo(cursor)

        context = repo.get_project_context("room-1")

        self.assertEqual(context["project_id"], 5)
        self.assertEqual(context["instructions"], "従ってください")
        self.assertNotIn("knowledge_text", context)


if __name__ == "__main__":
    unittest.main()
