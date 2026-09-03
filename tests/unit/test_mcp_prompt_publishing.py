from __future__ import annotations

import base64
from io import BytesIO
import os
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from services.mcp_prompt_publishing import (
    OpenAIFileInput,
    save_mcp_prompt_file,
    save_mcp_prompt_image,
)
from services.prompt_attachment_storage import (
    PROMPT_ATTACHMENT_MAX_BYTES,
    PROMPT_ATTACHMENT_UPLOAD_ROOT_ENV,
)


class McpPromptPublishingTestCase(unittest.TestCase):
    class _DownloadResponse:
        def __init__(self, body: bytes, *, status_code: int = 200, headers=None):
            self.body = body
            self.status_code = status_code
            self.headers = headers or {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def iter_content(self, chunk_size: int):
            for offset in range(0, len(self.body), chunk_size):
                yield self.body[offset : offset + chunk_size]

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

    def test_downloads_and_saves_a_chatgpt_file_parameter(self):
        source = self._image_bytes()
        response = self._DownloadResponse(
            source,
            headers={"Content-Length": str(len(source)), "Content-Type": "image/png"},
        )
        image_file = OpenAIFileInput(
            download_url="https://files.oaiusercontent.com/file-123/download?token=signed",
            file_id="file-123",
            mime_type="image/png",
            file_name="reference.png",
        )

        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch.dict(os.environ, {PROMPT_ATTACHMENT_UPLOAD_ROOT_ENV: temp_dir}),
            patch("services.mcp_prompt_publishing.requests.get", return_value=response) as get,
        ):
            attachment = save_mcp_prompt_file(image_file, 42)

        self.assertTrue(attachment["url"].startswith("/prompt_share/api/media/"))
        self.assertEqual(attachment["width"], "24")
        self.assertEqual(attachment["height"], "16")
        self.assertFalse(get.call_args.kwargs["allow_redirects"])
        self.assertTrue(get.call_args.kwargs["stream"])

    def test_downloads_and_saves_a_chatgpt_azure_blob_file_parameter(self):
        source = self._image_bytes("JPEG")
        response = self._DownloadResponse(
            source,
            headers={"Content-Length": str(len(source)), "Content-Type": "image/jpeg"},
        )
        image_file = OpenAIFileInput(
            download_url=(
                "https://oaisdmntprwestus3.blob.core.windows.net/"
                "files/file-123/reference.jpg?sp=r&sig=signed"
            ),
            file_id="file-123",
            mime_type="image/jpeg",
            file_name="reference.jpg",
        )

        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch.dict(os.environ, {PROMPT_ATTACHMENT_UPLOAD_ROOT_ENV: temp_dir}),
            patch("services.mcp_prompt_publishing.requests.get", return_value=response) as get,
        ):
            attachment = save_mcp_prompt_file(image_file, 42)

        self.assertTrue(attachment["url"].startswith("/prompt_share/api/media/"))
        self.assertEqual(attachment["width"], "24")
        self.assertEqual(attachment["height"], "16")
        self.assertEqual(get.call_args.args[0], str(image_file.download_url))

    def test_downloads_and_saves_a_chatgpt_generated_image_file_parameter(self):
        source = self._image_bytes()
        response = self._DownloadResponse(
            source,
            headers={"Content-Length": str(len(source)), "Content-Type": "image/png"},
        )
        image_file = OpenAIFileInput(
            download_url=(
                "https://oaidalleapiprodscus.blob.core.windows.net/"
                "private/generated-image.png?st=signed"
            ),
            file_id="file-generated-123",
            mime_type="image/png",
            file_name="generated-image.png",
        )

        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch.dict(os.environ, {PROMPT_ATTACHMENT_UPLOAD_ROOT_ENV: temp_dir}),
            patch("services.mcp_prompt_publishing.requests.get", return_value=response) as get,
        ):
            attachment = save_mcp_prompt_file(image_file, 42)

        self.assertTrue(attachment["url"].startswith("/prompt_share/api/media/"))
        self.assertEqual(attachment["width"], "24")
        self.assertEqual(attachment["height"], "16")
        self.assertEqual(get.call_args.args[0], str(image_file.download_url))

    def test_downloads_from_an_openai_file_host_sibling(self):
        source = self._image_bytes()
        response = self._DownloadResponse(
            source,
            headers={"Content-Length": str(len(source)), "Content-Type": "image/png"},
        )
        image_file = OpenAIFileInput(
            download_url="https://images.oaiusercontent.com/file-123?token=signed",
            file_id="file-123",
            mime_type="image/png",
            file_name="reference.png",
        )

        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch.dict(os.environ, {PROMPT_ATTACHMENT_UPLOAD_ROOT_ENV: temp_dir}),
            patch("services.mcp_prompt_publishing.requests.get", return_value=response) as get,
        ):
            attachment = save_mcp_prompt_file(image_file, 42)

        self.assertTrue(attachment["url"].startswith("/prompt_share/api/media/"))
        self.assertEqual(get.call_args.args[0], str(image_file.download_url))

    def test_rejects_a_non_openai_file_download_url_without_fetching_it(self):
        image_file = OpenAIFileInput(
            download_url="https://example.com/reference.png",
            file_id="file-123",
            mime_type="image/png",
            file_name="reference.png",
        )

        with patch("services.mcp_prompt_publishing.requests.get") as get:
            with self.assertRaisesRegex(ValueError, "ダウンロードURL"):
                save_mcp_prompt_file(image_file, 42)

        get.assert_not_called()

    def test_rejects_an_arbitrary_azure_blob_download_url_without_fetching_it(self):
        image_file = OpenAIFileInput(
            download_url="https://example.blob.core.windows.net/reference.png?sig=signed",
            file_id="file-123",
            mime_type="image/png",
            file_name="reference.png",
        )

        with patch("services.mcp_prompt_publishing.requests.get") as get:
            with self.assertRaisesRegex(ValueError, "ダウンロードURL"):
                save_mcp_prompt_file(image_file, 42)

        get.assert_not_called()

    def test_rejects_a_lookalike_openai_file_host_without_fetching_it(self):
        image_file = OpenAIFileInput(
            download_url="https://images.oaiusercontent.com.example.test/reference.png",
            file_id="file-123",
            mime_type="image/png",
            file_name="reference.png",
        )

        with patch("services.mcp_prompt_publishing.requests.get") as get:
            with self.assertRaisesRegex(ValueError, "ダウンロードURL"):
                save_mcp_prompt_file(image_file, 42)

        get.assert_not_called()

    def test_rejects_a_declared_oversize_file_before_streaming(self):
        response = self._DownloadResponse(
            b"",
            headers={"Content-Length": str(PROMPT_ATTACHMENT_MAX_BYTES + 1)},
        )
        image_file = OpenAIFileInput(
            download_url="https://files.oaiusercontent.com/file-123/download",
            file_id="file-123",
        )

        with patch("services.mcp_prompt_publishing.requests.get", return_value=response):
            with self.assertRaisesRegex(ValueError, "5MB以下"):
                save_mcp_prompt_file(image_file, 42)

    def test_stops_streaming_when_an_undeclared_file_exceeds_the_limit(self):
        response = self._DownloadResponse(b"x" * (PROMPT_ATTACHMENT_MAX_BYTES + 1))
        image_file = OpenAIFileInput(
            download_url="https://files.oaiusercontent.com/file-123/download",
            file_id="file-123",
        )

        with patch("services.mcp_prompt_publishing.requests.get", return_value=response):
            with self.assertRaisesRegex(ValueError, "5MB以下"):
                save_mcp_prompt_file(image_file, 42)

    def test_does_not_follow_a_file_download_redirect(self):
        response = self._DownloadResponse(b"", status_code=302, headers={"Location": "http://127.0.0.1/"})
        image_file = OpenAIFileInput(
            download_url="https://files.oaiusercontent.com/file-123/download",
            file_id="file-123",
        )

        with patch("services.mcp_prompt_publishing.requests.get", return_value=response):
            with self.assertRaisesRegex(ValueError, "取得できません"):
                save_mcp_prompt_file(image_file, 42)


if __name__ == "__main__":
    unittest.main()
