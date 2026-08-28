from __future__ import annotations

import base64
from io import BytesIO
import os
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from services.mcp_prompt_publishing import save_mcp_prompt_image
from services.prompt_attachment_storage import PROMPT_ATTACHMENT_UPLOAD_ROOT_ENV


class McpPromptPublishingTestCase(unittest.TestCase):
    @staticmethod
    def _image_bytes(image_format: str = "PNG") -> bytes:
        buffer = BytesIO()
        Image.new("RGB", (24, 16), color="teal").save(buffer, format=image_format)
        return buffer.getvalue()

    def test_saves_base64_image_with_an_inferred_filename(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {PROMPT_ATTACHMENT_UPLOAD_ROOT_ENV: temp_dir},
        ):
            attachment = save_mcp_prompt_image(
                base64.b64encode(self._image_bytes()).decode("ascii"),
                42,
            )

            self.assertTrue(attachment["url"].startswith("/prompt_share/api/media/"))
            self.assertTrue(attachment["thumbnail_url"].endswith("_card.webp"))
            self.assertEqual(attachment["media_type"], "image/webp")
            self.assertEqual(attachment["width"], "24")
            self.assertEqual(attachment["height"], "16")

    def test_accepts_data_url_and_uses_its_mime_type(self):
        encoded = base64.b64encode(self._image_bytes("JPEG")).decode("ascii")

        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {PROMPT_ATTACHMENT_UPLOAD_ROOT_ENV: temp_dir},
        ):
            attachment = save_mcp_prompt_image(
                f"data:image/jpeg;base64,{encoded}",
                42,
            )

        self.assertTrue(attachment["url"].endswith(".webp"))

    def test_rejects_a_declared_mime_type_that_does_not_match_the_bytes(self):
        encoded = base64.b64encode(self._image_bytes()).decode("ascii")

        with self.assertRaisesRegex(ValueError, "拡張子と画像形式"):
            save_mcp_prompt_image(encoded, 42, mime_type="image/jpeg")

    def test_rejects_invalid_base64_before_writing_any_file(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {PROMPT_ATTACHMENT_UPLOAD_ROOT_ENV: temp_dir},
        ):
            with self.assertRaisesRegex(ValueError, "Base64"):
                save_mcp_prompt_image("not-base64", 42)
            self.assertFalse(any(name.endswith(".webp") for name in os.listdir(temp_dir)))


if __name__ == "__main__":
    unittest.main()
