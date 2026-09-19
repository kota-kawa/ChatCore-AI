import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

from blueprints.prompt_share.prompt_share_api import create_prompt
from services.error_messages import ERROR_PROMPT_FORM_UNPARSABLE
from services.prompt_attachment_storage import PROMPT_ATTACHMENT_MAX_BYTES
from tests.helpers.request_helpers import build_request

# 日本語: 旧上限(256KB)は python-multipart のパート単位チェックに使われていた値。
#         日本語（マルチバイト）本文は文字数の上限内でもUTF-8バイト数が256KBを超えやすく、
#         この値で弾かれていた。新上限は添付画像の上限(5MB)に揃えている。
# English: The old cap (256KB) was the python-multipart per-part limit. Multi-byte Japanese
#          text easily exceeds 256KB in UTF-8 bytes even while within the character-count cap
#          Pydantic allows, so it used to be rejected. The new cap matches the 5MB attachment cap.
_OLD_PART_SIZE_CAP = 256 * 1024


def _multipart_field(name: str, value: str) -> bytes:
    return (
        b'Content-Disposition: form-data; name="' + name.encode("ascii") + b'"\r\n\r\n'
        + value.encode("utf-8")
    )


def _multipart_body(boundary: bytes, fields: dict[str, str]) -> bytes:
    parts = [b"--" + boundary + b"\r\n" + _multipart_field(name, value) + b"\r\n" for name, value in fields.items()]
    return b"".join(parts) + b"--" + boundary + b"--\r\n"


def _make_request(content: str):
    boundary = b"----promptformlimitboundary"
    fields = {
        "title": "長文プロンプト",
        "category": "",
        "content": content,
        "description": "",
        "content_format": "prompt",
        "media_type": "text",
        "input_examples": "",
        "output_examples": "",
        "ai_model": "",
    }
    body = _multipart_body(boundary, fields)
    request = build_request(
        method="POST",
        path="/prompt_share/api/prompts",
        raw_body=body,
        headers=[(b"content-type", b"multipart/form-data; boundary=" + boundary)],
        # 日本語: プロンプト投稿には短いクールダウンがあるため、他テストと衝突しない専用IDを使う。
        # English: Prompt creation has a short per-user cooldown; use an id unlikely to collide with other tests.
        session={"user_id": 8_042_017},
    )
    # 日本語: 実際のASGIアプリは scope["app"] を設定しており、Starletteはそれがある場合のみ
    #         MultiPartException を HTTPException(400) へ変換する。本番の挙動を再現するために設定する。
    # English: The real ASGI app sets scope["app"]; Starlette only converts MultiPartException to
    #          HTTPException(400) when it is present. Set it here to mirror production behavior.
    request.scope["app"] = True
    return request


class PromptFormPartSizeLimitTestCase(unittest.TestCase):
    """
    プロンプト共有APIの multipart パート上限が添付画像の上限(5MB)に揃っており、
    上限超過時は日本語のJSONエラーになることを検証します。
    Verify the prompt-share multipart part-size cap matches the 5MB attachment cap and that
    exceeding it now surfaces a Japanese JSON error instead of Starlette's raw message.
    """

    def test_long_japanese_content_over_the_old_256kb_cap_is_accepted(self):
        # 日本語1文字はUTF-8で3バイト。10万字なら約293KBとなり、旧256KB上限なら弾かれていた。
        # A single Japanese character is 3 UTF-8 bytes; 100,000 of them is ~293KB, which the
        # old 256KB part cap would have rejected.
        content = "桜" * 100_000
        self.assertGreater(len(content.encode("utf-8")), _OLD_PART_SIZE_CAP)
        self.assertLess(len(content.encode("utf-8")), PROMPT_ATTACHMENT_MAX_BYTES)
        request = _make_request(content)

        with patch(
            "blueprints.prompt_share.prompt_share_api.create_shared_prompt",
            new=AsyncMock(return_value=101),
        ) as create_for_user:
            response = asyncio.run(create_prompt(request))

        body = json.loads(response.body.decode("utf-8"))
        self.assertEqual(response.status_code, 201, body)
        create_for_user.assert_awaited_once()

    def test_field_over_the_5mb_cap_returns_a_japanese_error_not_starlettes_raw_message(self):
        oversized_content = "a" * (PROMPT_ATTACHMENT_MAX_BYTES + 1024)
        request = _make_request(oversized_content)

        with patch(
            "blueprints.prompt_share.prompt_share_api.create_shared_prompt",
            new=AsyncMock(),
        ) as create_for_user:
            response = asyncio.run(create_prompt(request))

        body = json.loads(response.body.decode("utf-8"))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(body["error"], ERROR_PROMPT_FORM_UNPARSABLE)
        create_for_user.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
