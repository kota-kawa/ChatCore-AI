"""alembic マイグレーション 20261120_03（承認待ちの候補を空きの分だけ記憶へ移す）の連鎖と SQL を検証するテスト。

Tests the revision chain and SQL of alembic migration 20261120_03, which moves pending candidates into memory
up to the free active slots.
"""

import importlib.util
import re
import unittest
from pathlib import Path
from unittest.mock import patch

from services.repositories.context_fact_repository import MAX_ACTIVE_CONTEXT_FACTS

migration_path = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "20261120_03_promote_pending_context_candidates.py"
)
spec = importlib.util.spec_from_file_location("context_candidate_promotion_migration", migration_path)
if spec is None or spec.loader is None:  # pragma: no cover - importlib invariant
    raise RuntimeError("Unable to load the context candidate promotion migration.")
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


# 日本語: op.execute に渡された SQL を、空白を 1 つに揃えた文字列のリストにします。
# English: Return the SQL passed to op.execute with whitespace collapsed to single spaces.
def _statements(execute):
    return [" ".join(call.args[0].split()) for call in execute.call_args_list]


def _upgrade_statements():
    with patch.object(migration.op, "execute") as execute:
        migration.upgrade()
    return _statements(execute)


class ContextCandidatePromotionMigrationTestCase(unittest.TestCase):
    def test_revision_follows_the_deprecated_reason_migration(self):
        self.assertEqual(migration.revision, "20261120_03")
        self.assertEqual(migration.down_revision, "20261120_02")

    def test_upgrade_locks_the_table_with_a_bounded_wait_before_counting_free_slots(self):
        set_timeout, lock, move, reset_timeout = _upgrade_statements()

        # 件数を数える文より前に、context_facts を 1 回だけ表ロックする。利用者ごとの advisory lock は、承認待ちを持つ利用者の
        # 数だけロックを持ってロック表を使い切り得るので使わない。待ち時間には上限を付け、移行の後の文へ持ち越さない。
        # The table is locked once before the statement that counts free slots. Per-user advisory locks are not used: they
        # hold one lock per user and can exhaust the lock table. The wait is bounded and not carried past this revision.
        self.assertEqual(set_timeout, "SET LOCAL lock_timeout = '5s'")
        self.assertEqual(lock, "LOCK TABLE context_facts IN SHARE ROW EXCLUSIVE MODE")
        self.assertIn("INSERT INTO context_facts", move)
        self.assertEqual(reset_timeout, "SET LOCAL lock_timeout TO DEFAULT")
        self.assertFalse(any("advisory" in sql for sql in (set_timeout, lock, move, reset_timeout)))

    def test_pending_candidates_are_row_locked_before_facts_are_made_from_them(self):
        _, _, move, _ = _upgrade_statements()

        self.assertRegex(move, r"WITH pending AS \(.*WHERE candidate.status = 'pending' FOR UPDATE \)")

    def test_free_slots_use_the_app_cap_and_active_facts_only(self):
        move = _upgrade_statements()[2]

        self.assertEqual(MAX_ACTIVE_CONTEXT_FACTS, 200)
        self.assertIn("ranked.position <= 200 - ( SELECT count(*) FROM context_facts AS fact", move)
        self.assertIn("fact.user_id = ranked.user_id AND fact.status = 'active'", move)

    def test_candidates_are_ranked_by_importance_then_confidence_then_id_per_user(self):
        move = _upgrade_statements()[2]

        self.assertIn("FROM pending AS candidate", move)
        self.assertIn(
            "PARTITION BY candidate.user_id ORDER BY candidate.importance DESC, candidate.confidence DESC, candidate.id ASC",
            move,
        )

    def test_moved_facts_look_like_unconfirmed_chat_saves(self):
        move = _upgrade_statements()[2]

        insert = re.search(r"INSERT INTO context_facts \((.*?)\) SELECT (.*?) FROM selected", move)
        assert insert is not None
        columns = [column.strip() for column in insert.group(1).split(",")]
        # revision は書かず列の初期値 1 のまま入る。上限での入れ替えは revision 1 を「手を入れていない」印にするので対象になる。
        # revision is not written and keeps the column default 1; the cap replacement treats revision 1 as untouched, so these qualify.
        self.assertNotIn("revision", columns)
        values = [value.strip() for value in insert.group(2).split(",")]
        self.assertEqual(
            dict(zip(columns, values, strict=True)),
            {
                "id": "selected.fact_id",
                "user_id": "selected.user_id",
                "fact_type": "selected.fact_type",
                "title": "selected.title",
                "content": "selected.content",
                "source_kind": "'chat'",
                "source_ref": "selected.source_ref",
                "importance": "selected.importance",
                "confidence": "selected.confidence",
                "status": "'active'",
                "embedding_status": "'pending'",
                "created_at": "selected.created_at",
            },
        )
        # 本人が確かめていないので last_confirmed_at を書かない(NULL)。出典の行も作らない。
        # last_confirmed_at is not written (stays NULL), and no source row is created.
        self.assertNotIn("last_confirmed_at", move)
        self.assertNotIn("context_fact_sources", move)

    def test_moved_candidates_are_linked_to_their_facts_with_the_same_ids(self):
        move = _upgrade_statements()[2]

        self.assertIn("nextval(pg_get_serial_sequence('context_facts', 'id')) AS fact_id", move)
        self.assertIn(
            "UPDATE context_fact_candidates AS candidate SET status = 'approved', promoted_fact_id = selected.fact_id, "
            "revision = candidate.revision + 1 FROM selected WHERE candidate.id = selected.candidate_id "
            "AND candidate.status = 'pending'",
            move,
        )

    def test_upgrade_never_deletes_what_did_not_fit(self):
        # 入りきらなかった承認待ちは、安全検査が DELETE を拒否するので残し、表を落とす後続の変更が消す。
        # What did not fit stays because the safety check rejects DELETE; the change that drops the table removes it.
        statements = _upgrade_statements()

        self.assertFalse(any(re.search(r"\b(DELETE|TRUNCATE|DROP)\b", sql) for sql in statements))

    def test_downgrade_changes_nothing(self):
        with patch.object(migration.op, "execute") as execute:
            migration.downgrade()

        execute.assert_not_called()

    def test_data_change_carries_the_review_marker(self):
        self.assertIn("# migration-review: approved-data-backfill", migration_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
