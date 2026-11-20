"""記憶の画面からの複数行にまたがる書き込み(置き換えを元に戻す・1 件の完全削除・すべての記憶の削除)の SQL、実行順、状態の再確認、
エラーの変換を検証するテスト。

Tests the SQL, execution order, state re-checks and error translation of the memory screen's multi-row writes:
undoing a replacement, deleting one memory for good and deleting all memories.
"""

import unittest
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.dialects.postgresql import dialect

from services.api_errors import ApiServiceError, ResourceNotFoundError
from services.repositories.context_fact_curation_repository import ContextFactCurationRepository
from tests.helpers.sql_helpers import bind_statement_parameters


def _sql(statement):
    # RETURNING は全列を読み戻すので、書き込み側の文だけを見る。
    # RETURNING reads every column back, so look at the writing part of the statement only.
    return " ".join(str(statement.compile(dialect=dialect())).split()).split(" RETURNING")[0]


def _fact_row(fact_id, **overrides):
    row = {
        "id": fact_id,
        "user_id": 7,
        "fact_type": "profile",
        "title": "住所",
        "content": "東京に住んでいる",
        "source_kind": "chat",
        "source_ref": None,
        "source_client_id": None,
        "importance": 50,
        "idempotency_key_hash": None,
        "idempotency_payload_hash": None,
        "status": "active",
        "revision": 1,
        "embedding_status": "ready",
        "confidence": None,
        "last_confirmed_at": None,
        "deprecated_reason": None,
        "created_at": None,
        "updated_at": None,
    }
    row.update(overrides)
    return row


# 日本語: execute と scalar の呼び出しを 1 本の順序つきログに記録するセッション。結果は呼び出しの順に渡す。
# English: A session that records execute and scalar calls in one ordered log; results are handed out in call order.
class _Session:
    def __init__(self, results):
        self.log = []
        self._results = list(results)
        self.execute = AsyncMock(side_effect=self._execute)
        self.scalar = AsyncMock(side_effect=self._scalar)

    async def _execute(self, statement):
        self.log.append(statement)
        return self._results.pop(0)

    async def _scalar(self, statement):
        self.log.append(statement)
        return self._results.pop(0)

    def sql(self):
        return [_sql(statement) for statement in self.log]


def _locked_row(*, status="active", revision=2):
    result = MagicMock()
    result.first.return_value = MagicMock(id=4, status=status, revision=revision)
    return result


def _missing_row():
    result = MagicMock()
    result.first.return_value = None
    return result


def _returning(row):
    result = MagicMock()
    result.mappings.return_value.first.return_value = row
    return result


def _count(rowcount):
    result = MagicMock()
    result.rowcount = rowcount
    return result


_LOCK = MagicMock()


class RevertReplacementTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_deprecates_the_new_fact_and_restores_the_old_one_in_lock_check_update_order(self):
        newer = _fact_row(4, status="deprecated", deprecated_reason="user", revision=3)
        older = _fact_row(3, title="旧住所", content="大阪に住んでいる", status="active", revision=6)
        session = _Session([_LOCK, _locked_row(), 3, _returning(newer), _returning(older)])

        deprecated, restored = await ContextFactCurationRepository(session).revert_replacement(7, 4, 2)

        sql = session.sql()
        self.assertEqual(len(sql), 5)
        self.assertIn("pg_advisory_xact_lock", sql[0])
        self.assertEqual(bind_statement_parameters(session.log[0])["pg_advisory_xact_lock_3"], 7)
        # 新しい事実の行ロック（revision を確かめる）→ 古い事実の行ロック → 2 行の更新、の順。
        # Row lock on the new fact (revision checked), then the old fact's row lock, then the two updates.
        self.assertIn("FROM context_facts", sql[1])
        self.assertIn("FOR UPDATE", sql[1])
        self.assertIn("FOR UPDATE", sql[2])
        self.assertIn("UPDATE context_facts", sql[3])
        self.assertIn("UPDATE context_facts", sql[4])
        self.assertEqual((deprecated["id"], deprecated["status"], deprecated["deprecated_reason"]), (4, "deprecated", "user"))
        self.assertEqual((restored["id"], restored["status"]), (3, "active"))

    async def test_old_fact_lookup_requires_owners_superseded_fact_pointing_at_the_new_one(self):
        session = _Session([_LOCK, _locked_row(), 3, _returning(_fact_row(4)), _returning(_fact_row(3))])
        await ContextFactCurationRepository(session).revert_replacement(7, 4, 2)

        lookup = session.log[2]
        sql = _sql(lookup)
        for condition in (
            "context_facts.user_id =",
            "context_facts.status =",
            "context_facts.deprecated_reason =",
            "context_facts.superseded_by_fact_id =",
        ):
            self.assertIn(condition, sql)
        self.assertIn("ORDER BY context_facts.updated_at DESC, context_facts.id DESC", sql)
        bound = bind_statement_parameters(lookup)
        self.assertIn("deprecated", bound.values())
        self.assertIn("superseded", bound.values())
        self.assertIn(4, bound.values())
        self.assertIn(7, bound.values())

    async def test_new_fact_update_is_a_user_deprecation_guarded_by_revision_and_keeps_sources(self):
        session = _Session([_LOCK, _locked_row(), 3, _returning(_fact_row(4)), _returning(_fact_row(3))])
        await ContextFactCurationRepository(session).revert_replacement(7, 4, 2)

        statement = session.log[3]
        self.assertIn("context_facts.revision = %(revision_2)s", _sql(statement))
        bound = bind_statement_parameters(statement)
        # 理由は user（この内容は再び覚えない）。revision は呼び出しの値と一致する行だけ。
        # Reason user (that content is not remembered again); only the row at the caller's revision.
        self.assertEqual(
            {key: bound[key] for key in ("status", "deprecated_reason", "superseded_by_fact_id", "id_1", "user_id_1", "revision_2")},
            {
                "status": "deprecated",
                "deprecated_reason": "user",
                "superseded_by_fact_id": None,
                "id_1": 4,
                "user_id_1": 7,
                "revision_2": 2,
            },
        )
        # 出典と候補は触らない（新しい記憶の出典は残す）。有効件数は差し引き 0 なので数えない。
        # Sources and candidates are not touched (the new memory keeps its sources); the active count nets to zero, so it is not counted.
        for text in session.sql():
            self.assertNotIn("context_fact_sources", text)
            self.assertNotIn("context_fact_candidates", text)
            self.assertNotIn("DELETE", text)
            self.assertNotIn("count(", text)

    async def test_old_fact_update_rechecks_state_and_clears_reason_and_link(self):
        session = _Session([_LOCK, _locked_row(), 3, _returning(_fact_row(4)), _returning(_fact_row(3))])
        await ContextFactCurationRepository(session).revert_replacement(7, 4, 2)

        statement = session.log[4]
        bound = bind_statement_parameters(statement)
        # 書く値: 有効へ戻し、理由と置き換え先を NULL に。
        # Written values: active again, reason and replacement link cleared.
        self.assertEqual(
            {key: bound[key] for key in ("status", "deprecated_reason", "superseded_by_fact_id")},
            {"status": "active", "deprecated_reason": None, "superseded_by_fact_id": None},
        )
        # 条件: 本人の、無効化済みで理由が superseded、置き換え先が新しい事実の行だけ（行ロックを取った後でも再確認する）。
        # Condition: only the owner's deprecated row with reason superseded pointing at the new fact (re-checked even after the row lock).
        self.assertEqual(
            {key: bound[key] for key in ("id_1", "user_id_1", "status_1", "deprecated_reason_1", "superseded_by_fact_id_1")},
            {"id_1": 3, "user_id_1": 7, "status_1": "deprecated", "deprecated_reason_1": "superseded", "superseded_by_fact_id_1": 4},
        )

    async def test_missing_fact_is_404_and_nothing_is_written(self):
        session = _Session([_LOCK, _missing_row()])
        with self.assertRaises(ResourceNotFoundError):
            await ContextFactCurationRepository(session).revert_replacement(7, 4, 2)
        self.assertEqual(len(session.log), 2)

    async def test_revision_mismatch_is_409_and_nothing_is_written(self):
        session = _Session([_LOCK, _locked_row(revision=5)])
        with self.assertRaises(ApiServiceError) as error:
            await ContextFactCurationRepository(session).revert_replacement(7, 4, 2)
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(len(session.log), 2)

    async def test_a_deprecated_new_fact_is_409(self):
        session = _Session([_LOCK, _locked_row(status="deprecated")])
        with self.assertRaises(ApiServiceError) as error:
            await ContextFactCurationRepository(session).revert_replacement(7, 4, 2)
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(len(session.log), 2)

    async def test_no_replaced_old_fact_is_409_and_nothing_is_written(self):
        # 古い事実が復元・編集・削除されて条件を満たさないときは、新しい事実も無効化しない。
        # When the old fact was restored, edited or deleted and no longer qualifies, the new fact is not deprecated either.
        session = _Session([_LOCK, _locked_row(), None])
        with self.assertRaises(ApiServiceError) as error:
            await ContextFactCurationRepository(session).revert_replacement(7, 4, 2)
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(len(session.log), 3)
        self.assertFalse([text for text in session.sql() if text.startswith("UPDATE")])

    async def test_an_update_that_matches_no_row_is_409(self):
        for results in (
            [_LOCK, _locked_row(), 3, _returning(None), _returning(_fact_row(3))],
            [_LOCK, _locked_row(), 3, _returning(_fact_row(4)), _returning(None)],
        ):
            with self.subTest(results=len(results)), self.assertRaises(ApiServiceError) as error:
                await ContextFactCurationRepository(_Session(results)).revert_replacement(7, 4, 2)
            self.assertEqual(error.exception.status_code, 409)


class DeleteFactTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_candidates_are_deleted_before_the_fact_so_the_reference_is_still_there(self):
        session = _Session([_LOCK, _locked_row(), _count(1), _count(1)])
        await ContextFactCurationRepository(session).delete_fact(7, 4, 2)

        sql = session.sql()
        self.assertEqual(len(sql), 4)
        self.assertIn("pg_advisory_xact_lock", sql[0])
        self.assertIn("FOR UPDATE", sql[1])
        self.assertTrue(sql[2].startswith("DELETE FROM context_fact_candidates"))
        self.assertIn("context_fact_candidates.promoted_fact_id =", sql[2])
        self.assertIn("context_fact_candidates.user_id =", sql[2])
        self.assertTrue(sql[3].startswith("DELETE FROM context_facts"))
        self.assertIn("context_facts.user_id =", sql[3])

    async def test_sources_and_replacement_links_are_left_to_the_foreign_keys(self):
        session = _Session([_LOCK, _locked_row(), _count(0), _count(1)])
        await ContextFactCurationRepository(session).delete_fact(7, 4, 2)
        for text in session.sql():
            self.assertNotIn("context_fact_sources", text)
            self.assertFalse(text.startswith("UPDATE"))

    async def test_deleting_works_for_an_active_or_a_deprecated_fact(self):
        for status in ("active", "deprecated"):
            session = _Session([_LOCK, _locked_row(status=status), _count(0), _count(1)])
            with self.subTest(status=status):
                await ContextFactCurationRepository(session).delete_fact(7, 4, 2)
                self.assertEqual(len(session.log), 4)

    async def test_missing_fact_is_404_and_revision_mismatch_is_409_without_deleting(self):
        session = _Session([_LOCK, _missing_row()])
        with self.assertRaises(ResourceNotFoundError):
            await ContextFactCurationRepository(session).delete_fact(7, 4, 2)
        self.assertEqual(len(session.log), 2)

        session = _Session([_LOCK, _locked_row(revision=9)])
        with self.assertRaises(ApiServiceError) as error:
            await ContextFactCurationRepository(session).delete_fact(7, 4, 2)
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(len(session.log), 2)


class DeleteAllFactsTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_deletes_candidates_of_every_status_then_facts_and_returns_the_count(self):
        session = _Session([_LOCK, _count(5), _count(12)])
        deleted = await ContextFactCurationRepository(session).delete_all_facts(7)

        self.assertEqual(deleted, 12)
        sql = session.sql()
        self.assertEqual(len(sql), 3)
        self.assertIn("pg_advisory_xact_lock", sql[0])
        self.assertEqual(sql[1].split(" WHERE ")[0], "DELETE FROM context_fact_candidates")
        # 候補は状態で絞らない（却下済みを含む全状態）。
        # Candidates are not narrowed by status (every status, rejected ones included).
        self.assertNotIn("context_fact_candidates.status", sql[1])
        self.assertIn("context_fact_candidates.user_id =", sql[1])
        self.assertEqual(sql[2].split(" WHERE ")[0], "DELETE FROM context_facts")
        self.assertIn("context_facts.user_id =", sql[2])
        self.assertIn(7, bind_statement_parameters(session.log[2]).values())

    async def test_settings_and_sources_are_not_written_directly(self):
        session = _Session([_LOCK, _count(0), _count(0)])
        await ContextFactCurationRepository(session).delete_all_facts(7)
        for text in session.sql():
            self.assertNotIn("users", text)
            self.assertNotIn("context_fact_sources", text)
            self.assertFalse(text.startswith("UPDATE"))


if __name__ == "__main__":
    unittest.main()
