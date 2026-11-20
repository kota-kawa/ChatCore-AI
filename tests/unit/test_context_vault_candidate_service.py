"""記憶の自動抽出サービス（保存の設定確認、入力の整形、保存した事実の埋め込み予約、抽出の設定）を検証するテスト。

Tests the memory auto-extraction service: the setting check on store, input shaping, embedding scheduling for
saved facts, and the extraction setting.
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services.context_vault_candidate_service import (
    get_extraction_settings,
    is_context_extraction_enabled,
    store_extracted_facts,
    update_extraction_settings,
)


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
        "update_extraction_settings",
        "store_extracted",
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


    async def test_get_and_update_extraction_settings_return_the_stored_value(self):
        repo = _repo()
        repo.get_extraction_settings.return_value = True
        repo.update_extraction_settings.return_value = False
        with patch("services.context_vault_candidate_service._repository", return_value=repo):
            current = await get_extraction_settings(7, session=object())
            updated = await update_extraction_settings(7, False, session=object())

        self.assertTrue(current.enabled)
        self.assertFalse(updated.enabled)
        repo.update_extraction_settings.assert_awaited_once_with(7, False)


if __name__ == "__main__":
    unittest.main()
