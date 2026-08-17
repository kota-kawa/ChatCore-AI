import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from services import embeddings
from services.embeddings import (
    EMBEDDING_DIMENSIONS,
    EMBEDDING_FAILURE_THRESHOLD,
    embeddings_available,
    generate_embedding,
    get_embedding_health,
    get_semantic_max_distance,
    reset_embedding_failure_state,
)


def _fake_client(vector):
    """Return a stub OpenAI client whose embeddings endpoint returns ``vector``."""
    client = MagicMock()
    client.embeddings.create.return_value = SimpleNamespace(
        data=[SimpleNamespace(embedding=vector)]
    )
    return client


class EmbeddingGenerationTestCase(unittest.TestCase):
    def setUp(self):
        reset_embedding_failure_state()
        self.addCleanup(reset_embedding_failure_state)

    def test_requests_the_configured_model_and_shortened_dimensions(self):
        client = _fake_client([0.5] * EMBEDDING_DIMENSIONS)

        with patch.object(embeddings, "openai_client", client):
            vector = generate_embedding("  memo body  ")

        self.assertEqual(len(vector), EMBEDDING_DIMENSIONS)
        kwargs = client.embeddings.create.call_args.kwargs
        self.assertEqual(kwargs["model"], embeddings.EMBEDDING_MODEL)
        self.assertEqual(kwargs["dimensions"], EMBEDDING_DIMENSIONS)
        self.assertEqual(kwargs["input"], "memo body")

    def test_input_is_truncated_to_the_provider_limit(self):
        client = _fake_client([0.5] * EMBEDDING_DIMENSIONS)

        with patch.object(embeddings, "openai_client", client):
            generate_embedding("あ" * (embeddings.EMBEDDING_MAX_INPUT_CHARS + 500))

        self.assertEqual(
            len(client.embeddings.create.call_args.kwargs["input"]),
            embeddings.EMBEDDING_MAX_INPUT_CHARS,
        )

    def test_returns_none_without_a_configured_client(self):
        with patch.object(embeddings, "openai_client", None):
            self.assertFalse(embeddings_available())
            self.assertIsNone(generate_embedding("memo body"))

    def test_dimension_mismatch_is_rejected_instead_of_stored(self):
        client = _fake_client([0.5] * (EMBEDDING_DIMENSIONS - 1))

        with patch.object(embeddings, "openai_client", client):
            self.assertIsNone(generate_embedding("memo body"))
            self.assertEqual(get_embedding_health()["consecutive_failures"], 1)


class EmbeddingFailureLatchTestCase(unittest.TestCase):
    """Repeated provider failures must stop the calls instead of degrading silently."""

    def setUp(self):
        reset_embedding_failure_state()
        self.addCleanup(reset_embedding_failure_state)

    def test_repeated_failures_pause_further_calls(self):
        client = MagicMock()
        client.embeddings.create.side_effect = RuntimeError("model_not_found")

        with patch.object(embeddings, "openai_client", client):
            for _ in range(EMBEDDING_FAILURE_THRESHOLD):
                self.assertIsNone(generate_embedding("memo body"))

            self.assertFalse(embeddings_available())
            self.assertIsNone(generate_embedding("memo body"))

            # クールダウン中は追加の呼び出しを行わない（無駄な往復とレイテンシを避ける）。
            # No extra round-trip is made during the cooldown.
            self.assertEqual(
                client.embeddings.create.call_count, EMBEDDING_FAILURE_THRESHOLD
            )
            self.assertEqual(get_embedding_health()["status"], "error")

    def test_a_success_clears_the_latch(self):
        client = MagicMock()
        client.embeddings.create.side_effect = [
            RuntimeError("transient"),
            SimpleNamespace(data=[SimpleNamespace(embedding=[0.5] * EMBEDDING_DIMENSIONS)]),
        ]

        with patch.object(embeddings, "openai_client", client):
            self.assertIsNone(generate_embedding("memo body"))
            self.assertEqual(get_embedding_health()["status"], "degraded")
            self.assertIsNotNone(generate_embedding("memo body"))

            self.assertTrue(embeddings_available())
            self.assertEqual(get_embedding_health()["status"], "ok")

    def test_health_reports_disabled_without_a_client(self):
        with patch.object(embeddings, "openai_client", None):
            self.assertEqual(get_embedding_health()["status"], "disabled")


class SemanticDistanceThresholdTestCase(unittest.TestCase):
    def test_defaults_when_unset_or_out_of_range(self):
        with patch.dict("os.environ", {}, clear=False):
            os.environ.pop("SEMANTIC_MAX_DISTANCE", None)
            self.assertEqual(get_semantic_max_distance(), embeddings.SEMANTIC_MAX_DISTANCE)

        for invalid in ("abc", "0", "-1", "2.5"):
            with patch.dict("os.environ", {"SEMANTIC_MAX_DISTANCE": invalid}):
                self.assertEqual(
                    get_semantic_max_distance(), embeddings.SEMANTIC_MAX_DISTANCE
                )

    def test_environment_override_is_applied(self):
        with patch.dict("os.environ", {"SEMANTIC_MAX_DISTANCE": "0.4"}):
            self.assertEqual(get_semantic_max_distance(), 0.4)


if __name__ == "__main__":
    unittest.main()
