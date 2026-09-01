import unittest
from datetime import datetime, timedelta, timezone

from services.share_common import (
    DEFAULT_SHARE_TOKEN_BYTES,
    ShareContentKind,
    TokenShareLifecycle,
    build_share_path,
    build_share_url,
    generate_share_token,
    is_unique_violation,
)


class ShareCommonTestCase(unittest.TestCase):
    def test_builds_the_canonical_paths_for_each_content_kind(self):
        self.assertEqual(build_share_path(ShareContentKind.CHAT, "chat-token"), "/shared/chat-token")
        self.assertEqual(build_share_path("memo", "memo-token"), "/shared/memo/memo-token")
        self.assertEqual(build_share_path("PROMPT", 42), "/shared/prompt/42")

    def test_build_share_url_normalizes_the_base_url(self):
        self.assertEqual(
            build_share_url("https://example.test/", "prompt", 42),
            "https://example.test/shared/prompt/42",
        )

    def test_rejects_an_empty_or_nested_identifier(self):
        for identifier in (None, "", "  ", "token/other", "token?next=other"):
            with self.subTest(identifier=identifier):
                with self.assertRaises(ValueError):
                    build_share_path("chat", identifier)

    def test_lifecycle_uses_the_same_active_expired_and_revoked_flags(self):
        active = TokenShareLifecycle(
            "token",
            datetime.now(timezone.utc) + timedelta(days=1),
            None,
        )
        self.assertTrue(active.is_active)
        self.assertFalse(active.is_expired)
        self.assertFalse(active.is_revoked)

        expired = TokenShareLifecycle("token", datetime.utcnow() - timedelta(seconds=1), None)
        self.assertTrue(expired.is_expired)
        self.assertFalse(expired.is_active)

        revoked = TokenShareLifecycle("token", None, datetime.utcnow())
        self.assertTrue(revoked.is_revoked)
        self.assertFalse(revoked.is_active)
        self.assertEqual(revoked.to_dict()["share_token"], "token")

    def test_token_generation_uses_the_shared_byte_size(self):
        received = []

        def generator(size):
            received.append(size)
            return "generated"

        self.assertEqual(generate_share_token(generator), "generated")
        self.assertEqual(received, [DEFAULT_SHARE_TOKEN_BYTES])

    def test_unique_violation_detection_reads_wrapped_sqlstate(self):
        class UniqueViolation(Exception):
            sqlstate = "23505"

        class WrappedError(Exception):
            def __init__(self):
                self.orig = UniqueViolation()

        self.assertTrue(is_unique_violation(WrappedError()))
        self.assertFalse(is_unique_violation(RuntimeError("other database error")))


if __name__ == "__main__":
    unittest.main()
