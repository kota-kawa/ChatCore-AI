"""記憶の自動抽出サービス（保存の設定確認、保存した事実の埋め込み予約、候補の一覧のカーソル、
承認時の埋め込みスケジュール、却下）を検証するテスト。

Tests the memory auto-extraction service: the setting check on store, embedding scheduling for saved facts,
candidate list cursors, scheduling embeddings on approval, and rejection.
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services.api_errors import ApiServiceError
from services.context_vault_candidate_service import (
    approve_candidate,
    is_context_extraction_enabled,
    list_candidates,
    reject_candidate,
    store_extracted_facts,
)
from services.error_messages import ERROR_CONTEXT_FACT_CANDIDATE_CURSOR_INVALID


# 日本語: 候補テーブルの 1 行分の辞書を作ります。
# English: Build one candidate-table row dict.
def _candidate(**overrides):
    row = {
        "id": 8,
        "user_id": 7,
        "fact_type": "project",
        "title": "Chat-Core",
        "content": "Phase 2 candidate",
        "source_kind": "chat",
        "source_ref": "room-123",
        "source_client_id": "internal-client",
        "importance": 80,
        "confidence": 0.9,
        "status": "pending",
        "fingerprint": "a" * 64,
        "promoted_fact_id": None,
        "revision": 1,
        "created_at": "2026-07-23T12:00:00",
        "updated_at": "2026-07-23T12:00:00",
    }
    row.update(overrides)
    return row


# 日本語: 事実テーブルの 1 行分の辞書を作ります。
# English: Build one fact-table row dict.
def _fact(**overrides):
    row = {
        "id": 31,
        "user_id": 7,
        "fact_type": "project",
        "title": "Edited title",
        "content": "Edited content",
        "source_kind": "chat",
        "source_ref": "room-123",
        "source_client_id": None,
        "importance": 95,
        "status": "active",
        "revision": 1,
        "created_at": "2026-07-23T12:00:00",
        "updated_at": "2026-07-23T12:00:00",
    }
    row.update(overrides)
    return row


# 日本語: リポジトリの非同期メソッドをモックに差し替えた入れ物を作ります。
# English: Build a repository stand-in whose async methods are mocks.
def _repo():
    repo = MagicMock()
    for name in (
        "get_extraction_settings",
        "store_extracted",
        "list_candidates",
        "count_pending",
        "approve_candidate",
        "reject_candidate",
    ):
        setattr(repo, name, AsyncMock())
    return repo


# 日本語: リポジトリをモックし、サービス層の入出力の整形と呼び出し順を確認します。
# English: Mock the repository and check the service layer's input/output shaping and call order.
class ContextVaultCandidateServiceTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_store_extracted_facts_requires_setting_and_normalizes_input(self):
        repo = _repo()
        repo.get_extraction_settings.side_effect = [False, True]
        repo.store_extracted.return_value = [_fact()]
        with patch("services.context_vault_candidate_service._repository", return_value=repo):
            disabled = await store_extracted_facts(
                7,
                candidates=[{"fact_type": "project", "title": "T", "content": "C"}],
                source_ref="room-123",
                session=object(),
            )
            self.assertEqual(disabled, [])
            repo.store_extracted.assert_not_awaited()
            stored = await store_extracted_facts(
                7,
                candidates=[
                    {
                        "fact_type": "project",
                        "title": "  Chat-Core  ",
                        "content": "  Phase 2  ",
                        "importance": 80,
                        "confidence": 0.9,
                        "internal": "ignored",
                    },
                    {"fact_type": "bogus", "title": "Bad", "content": "Bad"},
                ],
                source_ref="  room-123  ",
                session=object(),
            )
        self.assertEqual([fact["id"] for fact in stored], [31])
        prepared = repo.store_extracted.call_args.args[1]
        self.assertEqual(len(prepared), 1)
        self.assertEqual(prepared[0]["title"], "Chat-Core")
        self.assertEqual(prepared[0]["source_kind"], "chat")
        self.assertEqual(prepared[0]["source_ref"], "room-123")
        self.assertEqual(len(prepared[0]["fingerprint"]), 64)

    async def test_store_extracted_facts_passes_evidence_and_message_origin_to_the_repository(self):
        repo = _repo()
        repo.get_extraction_settings.return_value = True
        repo.store_extracted.return_value = []
        candidates = [
            {"fact_type": "project", "title": "T", "content": "C", "evidence": "  I build T  "},
            {"fact_type": "project", "title": "T2", "content": "C2", "evidence": "x" * 1500},
            {"fact_type": "project", "title": "T3", "content": "C3"},
        ]
        with patch("services.context_vault_candidate_service._repository", return_value=repo):
            await store_extracted_facts(
                7,
                candidates=candidates,
                source_ref="chat:room-1:message:9",
                room_id="room-1",
                user_message_id=8,
                session=object(),
            )

        prepared = repo.store_extracted.call_args.args[1]
        # 長い引用は候補を落とさず 1000 文字で切り、前後の空白は除く。引用が無い候補は空のまま渡す。
        # An overlong quote is cut to 1000 characters instead of dropping the candidate; a missing quote stays empty.
        self.assertEqual([candidate["evidence"] for candidate in prepared], ["I build T", "x" * 1000, ""])
        self.assertEqual(repo.store_extracted.call_args.kwargs, {"room_id": "room-1", "user_message_id": 8})

    async def test_store_extracted_facts_schedules_embedding_for_each_saved_fact_after_commit(self):
        saved = [_fact(id=31, revision=1), _fact(id=32, title="Second", content="Other", revision=1)]
        candidates = [{"fact_type": "project", "title": "T", "content": "C"}]
        with patch(
            "services.context_vault_candidate_service._transaction",
            new=AsyncMock(return_value=saved),
        ), patch("services.context_vault_candidate_service.schedule_embedding") as schedule:
            result = await store_extracted_facts(7, candidates=candidates, source_ref="chat:r:message:1")
        self.assertEqual(result, saved)
        self.assertEqual([call.args[0] for call in schedule.call_args_list], [31, 32])
        schedule.assert_any_call(32, "project", "Second", "Other", 1)

        # 呼び出し側のセッションを使う場合は、コミット前に予約しない。
        # With a caller-supplied session nothing is scheduled before the caller commits.
        repo = _repo()
        repo.get_extraction_settings.return_value = True
        repo.store_extracted.return_value = saved
        with patch("services.context_vault_candidate_service._repository", return_value=repo), patch(
            "services.context_vault_candidate_service.schedule_embedding"
        ) as schedule:
            await store_extracted_facts(7, candidates=candidates, source_ref="chat:r:message:1", session=object())
        schedule.assert_not_called()

    async def test_store_extracted_facts_without_valid_candidates_does_not_touch_repository(self):
        repo = _repo()
        with patch("services.context_vault_candidate_service._repository", return_value=repo):
            result = await store_extracted_facts(
                7,
                candidates=[{"fact_type": "bogus", "title": "Bad", "content": "Bad"}, "not-a-dict"],  # type: ignore[list-item]
                source_ref="room-123",
                session=object(),
            )
        self.assertEqual(result, [])
        repo.get_extraction_settings.assert_not_awaited()

    async def test_extraction_runs_whenever_the_setting_is_on_even_at_the_cap(self):
        # 上限でも入れ替えと再言及の記録があるので、抽出を走らせる条件は設定だけにする。
        # At the cap there is still replacement and re-mention recording, so the setting alone decides whether extraction runs.
        repo = _repo()
        repo.get_extraction_settings.side_effect = [True, False]
        with patch("services.context_vault_candidate_service._repository", return_value=repo):
            self.assertTrue(await is_context_extraction_enabled(7, session=object()))
            self.assertFalse(await is_context_extraction_enabled(7, session=object()))

    async def test_list_candidates_returns_cursor_and_allowlisted_dto(self):
        repo = _repo()
        repo.list_candidates.return_value = [
            _candidate(id=9, created_at="2026-07-23T13:00:00"),
            _candidate(id=8, created_at="2026-07-23T12:00:00"),
            _candidate(id=7, created_at="2026-07-23T11:00:00"),
        ]
        repo.count_pending.return_value = 6
        with patch("services.context_vault_candidate_service._repository", return_value=repo):
            result = await list_candidates(7, limit=2, session=object())
        self.assertEqual(len(result.candidates), 2)
        self.assertEqual(result.next_cursor, "2026-07-23T12:00:00~8")
        self.assertEqual(result.total_pending, 6)
        self.assertNotIn("fingerprint", result.candidates[0].model_dump())

    async def test_invalid_cursor_is_rejected_before_repository_call(self):
        repo = _repo()
        with patch("services.context_vault_candidate_service._repository", return_value=repo):
            with self.assertRaises(ApiServiceError) as error:
                await list_candidates(7, cursor="invalid", session=object())
        self.assertEqual(error.exception.message, ERROR_CONTEXT_FACT_CANDIDATE_CURSOR_INVALID)
        repo.list_candidates.assert_not_awaited()

    async def test_approve_schedules_embedding_only_after_default_transaction(self):
        repo = _repo()
        repo.approve_candidate.return_value = (
            _candidate(status="approved", revision=2, promoted_fact_id=31),
            _fact(confidence=0.72, last_confirmed_at="2026-07-23T12:00:00"),
        )
        with patch("services.context_vault_candidate_service._repository", return_value=repo), patch(
            "services.context_vault_candidate_service.schedule_embedding"
        ) as schedule:
            # セッションを渡すことで、このユニットテストではリポジトリへの委譲だけを切り出して確認する。
            # ルートの既定経路では、自前で開いたトランザクションが終わってから埋め込みを予約する。
            # Passing a session lets this unit test isolate repository delegation;
            # the route-level default path schedules after its owned transaction.
            result = await approve_candidate(
                7,
                8,
                expected_revision=1,
                title=" Edited title ",
                content=" Edited content ",
                importance=95,
                session=object(),
            )
        self.assertEqual(result.fact.id, 31)
        self.assertEqual(result.fact.confidence, 0.72)
        self.assertEqual(result.fact.last_confirmed_at, "2026-07-23T12:00:00")
        repo.approve_candidate.assert_awaited_once_with(
            7,
            8,
            expected_revision=1,
            fact_type=None,
            title="Edited title",
            content="Edited content",
            importance=95,
        )
        schedule.assert_not_called()

    async def test_reject_returns_allowlisted_candidate(self):
        repo = _repo()
        repo.reject_candidate.return_value = _candidate(status="rejected", revision=2)
        with patch("services.context_vault_candidate_service._repository", return_value=repo):
            result = await reject_candidate(7, 8, expected_revision=1, session=object())
        self.assertEqual(result.status, "rejected")
        repo.reject_candidate.assert_awaited_once_with(7, 8, expected_revision=1)


if __name__ == "__main__":
    unittest.main()
