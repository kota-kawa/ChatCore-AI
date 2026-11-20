"""記憶のまとめを文脈に入れたターンの規模（件数・見積もりトークン）が、生成テレメトリへ載ることを検証するテスト。

Tests that the size of the memory summary put into a turn's context (facts, estimated tokens) reaches the generation telemetry.
"""

import json
import unittest
from unittest.mock import patch

from blueprints.chat.messages import _iter_llm_stream_events
from services.chat_generation import ChatGenerationJob, build_generation_key, start_generation_job
from services.user_memory import build_user_memory_summary


def _job(**kwargs):
    return ChatGenerationJob(
        conversation_messages=[{"role": "user", "content": "hi"}],
        model="test-model",
        persist_response=lambda *_args, **_kwargs: None,
        **kwargs,
    )


class UserMemoryTelemetryTestCase(unittest.TestCase):
    def test_a_job_records_the_size_of_the_summary_it_was_given_and_never_its_text(self):
        summary = build_user_memory_summary(
            [
                {
                    "id": 1,
                    "fact_type": "profile",
                    "title": "SECRET-TITLE",
                    "content": "SECRET-CONTENT",
                    "importance": 50,
                    "last_mentioned_at": None,
                }
            ]
        )
        assert summary is not None

        payload = _job(user_memory=summary)._telemetry.as_log_extra()

        self.assertEqual(payload["user_memory_fact_count"], 1)
        self.assertEqual(payload["user_memory_estimated_tokens"], summary.estimated_tokens)
        self.assertGreater(summary.estimated_tokens, 0)
        self.assertNotIn("SECRET", json.dumps(payload, ensure_ascii=False))

    def test_the_service_hands_the_summary_size_from_start_to_the_running_job(self):
        summary = build_user_memory_summary(
            [{"id": 1, "fact_type": "profile", "title": "t", "content": "c", "importance": 50, "last_mentioned_at": None}]
        )
        with patch("services.chat_generation_llm_stream.get_llm_response_stream", return_value=iter(["完了"])):
            job = start_generation_job(
                build_generation_key(chat_room_id="room-memory-telemetry", user_id=7),
                conversation_messages=[{"role": "user", "content": "test"}],
                model="openai/gpt-oss-120b",
                persist_response=lambda _: None,
                user_memory=summary,
            )
            list(_iter_llm_stream_events(job))

        self.assertEqual(job._telemetry.user_memory_fact_count, 1)

    def test_a_turn_without_the_summary_records_zero(self):
        payload = _job()._telemetry.as_log_extra()

        self.assertEqual((payload["user_memory_fact_count"], payload["user_memory_estimated_tokens"]), (0, 0))


if __name__ == "__main__":
    unittest.main()
