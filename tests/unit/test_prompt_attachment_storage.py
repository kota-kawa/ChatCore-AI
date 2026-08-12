import asyncio
from io import BytesIO
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from starlette.datastructures import Headers, UploadFile

from blueprints.prompt_share.prompt_share_api import (
    _delete_prompt_attachments,
    _save_prompt_attachment,
    get_prompt_attachment_media,
)
from services.error_messages import ERROR_PROMPT_ATTACHMENT_NOT_FOUND
from services.prompt_attachment_storage import (
    PROMPT_ATTACHMENT_UPLOAD_ROOT_ENV,
    get_prompt_attachment_upload_root,
    normalize_prompt_attachment_public_url,
    resolve_prompt_attachment_path,
)


class PromptAttachmentStorageTestCase(unittest.TestCase):
    def test_default_upload_root_is_outside_frontend_public(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(PROMPT_ATTACHMENT_UPLOAD_ROOT_ENV, None)
            root = get_prompt_attachment_upload_root()

        self.assertTrue(root.endswith(os.path.join("data", "uploads", "prompt_share")))
        self.assertNotIn(os.path.join("frontend", "public"), root)

    def test_legacy_url_is_normalized_to_backend_media_url(self):
        self.assertEqual(
            normalize_prompt_attachment_public_url(
                "/static/uploads/prompt_share/user_7_abc.png"
            ),
            "/prompt_share/api/media/user_7_abc.png",
        )

    def test_external_url_is_not_normalized_or_treated_as_local_file(self):
        for url in (
            "https://cdn.example.com/static/uploads/prompt_share/image.png",
            "//cdn.example.com/static/uploads/prompt_share/image.png",
        ):
            with self.subTest(url=url):
                self.assertIsNone(normalize_prompt_attachment_public_url(url))

    def test_path_resolution_rejects_unsafe_or_unsupported_filenames(self):
        for filename in ("../secret.png", "nested/image.png", "image.svg", ".hidden.png"):
            with self.subTest(filename=filename), self.assertRaises(ValueError):
                resolve_prompt_attachment_path(filename)

    def test_save_serve_and_delete_attachment(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {PROMPT_ATTACHMENT_UPLOAD_ROOT_ENV: temp_dir},
        ):
            upload = UploadFile(
                BytesIO(b"\x89PNG\r\n\x1a\nexample"),
                filename="example.png",
                headers=Headers({"content-type": "image/png"}),
            )

            attachment = _save_prompt_attachment(upload, 42, "image")
            filename = attachment["url"].rsplit("/", 1)[-1]
            stored_path = resolve_prompt_attachment_path(filename)

            self.assertTrue(os.path.isfile(stored_path))
            self.assertEqual(attachment["media_type"], "image/png")
            self.assertTrue(attachment["url"].startswith("/prompt_share/api/media/"))

            response = asyncio.run(get_prompt_attachment_media(filename))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.media_type, "image/png")
            self.assertEqual(response.headers["x-content-type-options"], "nosniff")
            self.assertEqual(
                response.headers["cache-control"],
                "public, max-age=31536000, immutable",
            )

            _delete_prompt_attachments([attachment])
            self.assertFalse(os.path.exists(stored_path))

    def test_media_route_returns_404_for_invalid_or_missing_file(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {PROMPT_ATTACHMENT_UPLOAD_ROOT_ENV: temp_dir},
        ):
            invalid_response = asyncio.run(get_prompt_attachment_media("image.svg"))
            missing_response = asyncio.run(get_prompt_attachment_media("missing.png"))

        self.assertEqual(invalid_response.status_code, 404)
        self.assertEqual(missing_response.status_code, 404)
        payload = json.loads(invalid_response.body.decode("utf-8"))
        self.assertEqual(payload["error"], ERROR_PROMPT_ATTACHMENT_NOT_FOUND)

    def test_media_route_reads_legacy_location_as_fallback(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            legacy_path = os.path.join(temp_dir, "legacy.png")
            with open(legacy_path, "wb") as legacy_file:
                legacy_file.write(b"\x89PNG\r\n\x1a\nlegacy")
            with patch(
                "blueprints.prompt_share.prompt_share_api.resolve_prompt_attachment_path",
                return_value=os.path.join(temp_dir, "missing.png"),
            ), patch(
                "blueprints.prompt_share.prompt_share_api.resolve_legacy_prompt_attachment_path",
                return_value=legacy_path,
            ):
                response = asyncio.run(get_prompt_attachment_media("legacy.png"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.media_type, "image/png")

    def test_save_rejects_empty_and_mismatched_image_data(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {PROMPT_ATTACHMENT_UPLOAD_ROOT_ENV: temp_dir},
        ):
            for content in (b"", b"not a png"):
                with self.subTest(content=content):
                    upload = UploadFile(
                        BytesIO(content),
                        filename="example.png",
                        headers=Headers({"content-type": "image/png"}),
                    )
                    with self.assertRaises(ValueError):
                        _save_prompt_attachment(upload, 42, "image")
            self.assertEqual(os.listdir(temp_dir), [])


if __name__ == "__main__":
    unittest.main()
