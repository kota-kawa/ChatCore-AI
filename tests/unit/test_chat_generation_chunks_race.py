"""停止経路と生成スレッドが `_chunks` / `_pending_stream_chunks` を同時に書き換える
レースを再現し、`_chunks_lock` がそれを防ぐことを検証するテスト。

両方の実行順序（cancel()が先／生成スレッドの確定処理が先）を単一スレッドで明示的に
再現することで、タイミング頼みの再現性の低いテストを避ける。ロックが守る不変条件は
「実行順序に関係なく、同じ本文が二重に保存されない」ことであり、これは順序を固定して
検証できる。

Reproduces the race between the stop path and the generation thread over `_chunks` /
`_pending_stream_chunks`, and verifies `_chunks_lock` prevents it.

Both possible orderings (cancel() first vs. the generation thread's own completion first)
are reproduced explicitly on a single thread, instead of relying on real thread timing,
which would make the test flaky. The invariant the lock protects — the same text is never
saved twice, regardless of which side runs first — can be checked with the order fixed.
"""

import unittest

from services.chat_generation import ChatGenerationJob


def _make_job() -> ChatGenerationJob:
    return ChatGenerationJob(
        conversation_messages=[{"role": "user", "content": "hi"}],
        model="openai/gpt-oss-120b",
        persist_response=lambda response, **kwargs: None,
    )


# 日本語: `_iter_llm_stream_with_retry` が成功時に行う「配信前にバッファを空にしてから
# publish する」手順を再現するヘルパー。
# English: Helper reproducing the "clear the buffer, then publish" sequence that
# `_iter_llm_stream_with_retry` performs on a successful stream.
def _run_normal_completion(job: ChatGenerationJob, state, text: str) -> None:
    with job._chunks_lock:
        job._pending_stream_chunks.clear()
    job._publish_completed_answer_step(state, [text])


class ChatGenerationChunksRaceTestCase(unittest.TestCase):
    # 日本語: 生成スレッドの通常完了が先に本文を確定させた後、遅れて cancel() の
    # salvage が同じ内容に追いついても、二重に保存されないことを確認する。
    # English: Verify that when the generation thread's normal completion commits the text
    # first and cancel()'s salvage catches up afterward, the text is never saved twice.
    def test_normal_completion_then_late_cancel_does_not_duplicate(self):
        job = _make_job()
        state = job._build_turn_run_state()
        shared_text = "shared step text"
        # `_iter_llm_stream_with_retry` がストリームを完了させた直後の状態を再現する:
        # 配信予定の本文はまだ `_pending_stream_chunks` に載っている。
        job._pending_stream_chunks = [shared_text]

        _run_normal_completion(job, state, shared_text)
        self.assertEqual(job._chunks.count(shared_text), 1)

        # cancel() が後から追いついても、既に確定済みの本文を二重に積まないこと。
        job.cancel()
        self.assertEqual(job._chunks.count(shared_text), 1)

    # 日本語: cancel() が先に本文を salvage した後、生成スレッド側の完了処理が
    # 遅れて同じ内容を確定させようとしても、二重に保存されないことを確認する。
    # 修正前（`_publish_completed_answer_step` に `_cancelled` チェックが無い版）では、
    # この呼び出しが無条件に追記するため二重化する。
    # English: Verify that when cancel() salvages the text first and the generation thread's
    # completion path tries to commit the same text afterward, it is never saved twice.
    # Against the pre-fix `_publish_completed_answer_step` (no `_cancelled` check), this call
    # appends unconditionally and duplicates the text.
    def test_cancel_then_late_normal_completion_does_not_duplicate(self):
        job = _make_job()
        state = job._build_turn_run_state()
        shared_text = "shared step text"
        job._pending_stream_chunks = [shared_text]

        job.cancel()
        self.assertEqual(job._chunks.count(shared_text), 1)

        # 生成スレッドが後から確定処理を試みても、既に salvage 済みの本文を
        # 二重に積まないこと。
        _run_normal_completion(job, state, shared_text)
        self.assertEqual(
            job._chunks.count(shared_text),
            1,
            f"the step text was saved more than once: {job._chunks!r}",
        )

    # 日本語: 生成スレッドが `_publish_completed_answer_step` へ到達した時点で
    # 既にキャンセル済みなら、そのステップの本文を追記しないことを直接確認する。
    # これが上の2つのテストで確認している不変条件の核心の分岐。
    # English: Directly verify that once the generation thread reaches
    # `_publish_completed_answer_step`, it skips appending if cancellation already happened.
    # This is the core branch behind the invariant the two tests above check.
    def test_publish_completed_answer_step_skips_append_after_cancel(self):
        # `.start()` を呼ばないため生成スレッドは一切走らず、このテストスレッドだけで
        # 分岐を検証できる。
        # `.start()` is never called, so no generation thread runs at all; the branch is
        # exercised entirely on this test thread.
        job = _make_job()
        job._cancelled = True
        state = job._build_turn_run_state()
        before = list(job._chunks)
        job._publish_completed_answer_step(state, ["should not be appended"])
        self.assertEqual(job._chunks, before)


if __name__ == "__main__":
    unittest.main()
