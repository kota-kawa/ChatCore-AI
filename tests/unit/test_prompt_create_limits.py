from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi import Request

from blueprints.prompt_share.prompt_share_api import (
    PROMPT_ATTACHMENT_MAX_REQUEST_BYTES,
    _request_body_exceeds_prompt_attachment_limit,
)
from services.prompt_create_limits import consume_prompt_create_limits


def _request(headers: list[tuple[bytes, bytes]]) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/prompt_share/api/prompts",
            "headers": headers,
            "client": ("203.0.113.9", 1234),
        }
    )


class PromptCreateAttachmentLimitTestCase(unittest.TestCase):
    def test_rejects_content_length_above_upload_request_limit(self):
        request = _request(
            [(b"content-length", str(PROMPT_ATTACHMENT_MAX_REQUEST_BYTES + 1).encode())]
        )
        self.assertTrue(_request_body_exceeds_prompt_attachment_limit(request))

    def test_rejects_invalid_content_length(self):
        self.assertTrue(_request_body_exceeds_prompt_attachment_limit(_request([(b"content-length", b"oops")])))


# Web の投稿フォームとチャットの publish_prompt 承認実行は、同じこの関数を通して同じキー・
# 同じ上限を消費する。Both the Web composer and a chat publish_prompt approval consume the same
# limit through this one function.
class PromptCreateLimitTestCase(unittest.TestCase):
    def test_rate_limit_stops_after_first_rejected_scope(self):
        with patch(
            "services.prompt_create_limits.consume_rate_limit",
            return_value=(False, 12, 25),
        ) as consume:
            allowed, message, retry_after = consume_prompt_create_limits("203.0.113.9", 42)

        self.assertFalse(allowed)
        self.assertIn("25秒", message or "")
        self.assertEqual(retry_after, 25)
        self.assertEqual(consume.call_count, 1)
        self.assertEqual(consume.call_args.args[0], "prompt:create:ip")

    def test_checks_ip_then_user_then_cooldown_in_order(self):
        with patch(
            "services.prompt_create_limits.consume_rate_limit",
            return_value=(True, 0, 0),
        ) as consume:
            allowed, message, retry_after = consume_prompt_create_limits("203.0.113.9", 42)

        self.assertTrue(allowed)
        self.assertIsNone(message)
        self.assertIsNone(retry_after)
        self.assertEqual(
            [call.args[0] for call in consume.call_args_list],
            ["prompt:create:ip", "prompt:create:user", "prompt:create:cooldown"],
        )

    def test_missing_client_ip_skips_only_the_ip_check(self):
        with patch(
            "services.prompt_create_limits.consume_rate_limit",
            return_value=(True, 0, 0),
        ) as consume:
            allowed, message, retry_after = consume_prompt_create_limits(None, 42)

        self.assertTrue(allowed)
        self.assertEqual(
            [call.args[0] for call in consume.call_args_list],
            ["prompt:create:user", "prompt:create:cooldown"],
        )


if __name__ == "__main__":
    unittest.main()
