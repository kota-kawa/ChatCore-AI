from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi import Request

from blueprints.prompt_share.prompt_share_api import (
    PROMPT_ATTACHMENT_MAX_REQUEST_BYTES,
    _consume_prompt_create_limits,
    _request_body_exceeds_prompt_attachment_limit,
)


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


class PromptCreateLimitTestCase(unittest.TestCase):
    def test_rejects_content_length_above_upload_request_limit(self):
        request = _request(
            [(b"content-length", str(PROMPT_ATTACHMENT_MAX_REQUEST_BYTES + 1).encode())]
        )
        self.assertTrue(_request_body_exceeds_prompt_attachment_limit(request))

    def test_rejects_invalid_content_length(self):
        self.assertTrue(_request_body_exceeds_prompt_attachment_limit(_request([(b"content-length", b"oops")])))

    def test_rate_limit_stops_after_first_rejected_scope(self):
        request = _request([])
        with patch(
            "blueprints.prompt_share.prompt_share_api.consume_rate_limit",
            return_value=(False, 12, 25),
        ) as consume:
            allowed, message, retry_after = _consume_prompt_create_limits(request, 42)

        self.assertFalse(allowed)
        self.assertIn("25秒", message or "")
        self.assertEqual(retry_after, 25)
        self.assertEqual(consume.call_count, 1)


if __name__ == "__main__":
    unittest.main()
