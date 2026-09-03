from __future__ import annotations

import base64
from io import BytesIO
import os
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from services import mcp_image_upload_session
from services.mcp_image_upload_session import (
    append_mcp_image_upload_chunk,
    cleanup_expired_mcp_image_uploads,
    consume_mcp_image_upload,
    create_mcp_image_upload,
    delete_consumed_mcp_image_upload,
    delete_mcp_image_upload,
)
from services.mcp_prompt_publishing import save_mcp_prompt_image
from services.prompt_attachment_storage import PROMPT_ATTACHMENT_UPLOAD_ROOT_ENV


class McpImageUploadSessionTestCase(unittest.TestCase):
    def test_stages_ordered_fragments_and_accepts_an_identical_retry(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {PROMPT_ATTACHMENT_UPLOAD_ROOT_ENV: temp_dir},
        ):
            upload_id = create_mcp_image_upload(42, "client-a", 8)

            first_progress = append_mcp_image_upload_chunk(
                upload_id,
                42,
                "client-a",
                0,
                "aGVs",
            )
            retry_progress = append_mcp_image_upload_chunk(
                upload_id,
                42,
                "client-a",
                0,
                "aGVs",
            )
            final_progress = append_mcp_image_upload_chunk(
                upload_id,
                42,
                "client-a",
                1,
                "bG8=",
            )

            self.assertEqual(first_progress, (1, 4))
            self.assertEqual(retry_progress, (1, 4))
            self.assertEqual(final_progress, (2, 8))
            self.assertEqual(consume_mcp_image_upload(42, "client-a", upload_id), "aGVsbG8=")
            with self.assertRaisesRegex(ValueError, "有効期限"):
                consume_mcp_image_upload(42, "client-a", upload_id)
            with self.assertRaisesRegex(ValueError, "有効期限"):
                append_mcp_image_upload_chunk(upload_id, 42, "client-a", 2, "AAAA")

            delete_consumed_mcp_image_upload(upload_id, 42, "client-a")
            with self.assertRaisesRegex(ValueError, "有効期限"):
                consume_mcp_image_upload(42, "client-a", upload_id)

    def test_rejects_a_different_actor_or_out_of_order_chunk(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {PROMPT_ATTACHMENT_UPLOAD_ROOT_ENV: temp_dir},
        ):
            upload_id = create_mcp_image_upload(42, "client-a", 8)

            with self.assertRaisesRegex(ValueError, "有効期限"):
                append_mcp_image_upload_chunk(upload_id, 43, "client-a", 0, "aGVs")
            with self.assertRaisesRegex(ValueError, "順序"):
                append_mcp_image_upload_chunk(upload_id, 42, "client-a", 1, "aGVs")

    def test_rejects_invalid_or_oversized_chunk_data(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {PROMPT_ATTACHMENT_UPLOAD_ROOT_ENV: temp_dir},
        ):
            upload_id = create_mcp_image_upload(42, "client-a", 4)

            with self.assertRaisesRegex(ValueError, "チャンク"):
                append_mcp_image_upload_chunk(upload_id, 42, "client-a", 0, "not_base64!")
            with patch.object(mcp_image_upload_session, "MCP_PROMPT_IMAGE_BASE64_MAX_LENGTH", 3):
                with self.assertRaisesRegex(ValueError, "5MB以下"):
                    append_mcp_image_upload_chunk(upload_id, 42, "client-a", 0, "aGVs")

    def test_cleanup_removes_expired_sessions(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {PROMPT_ATTACHMENT_UPLOAD_ROOT_ENV: temp_dir},
        ):
            with patch("services.mcp_image_upload_session.time.time", return_value=100.0):
                upload_id = create_mcp_image_upload(42, "client-a", 8)
            deleted = cleanup_expired_mcp_image_uploads(
                now=100.0 + mcp_image_upload_session.MCP_IMAGE_UPLOAD_TTL_SECONDS,
            )

            self.assertEqual(deleted, 1)
            self.assertFalse(os.path.exists(os.path.join(temp_dir, ".mcp-image-uploads", upload_id)))

    def test_limits_active_sessions_for_one_actor(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {PROMPT_ATTACHMENT_UPLOAD_ROOT_ENV: temp_dir},
        ), patch.object(mcp_image_upload_session, "MCP_IMAGE_UPLOAD_MAX_ACTIVE_PER_USER", 2):
            create_mcp_image_upload(42, "client-a", 8)
            create_mcp_image_upload(42, "client-a", 8)

            with self.assertRaisesRegex(ValueError, "同時に保持"):
                create_mcp_image_upload(42, "client-a", 8)

            with self.assertRaisesRegex(ValueError, "同時に保持"):
                create_mcp_image_upload(42, "client-b", 8)

            create_mcp_image_upload(43, "client-a", 8)

    def test_incomplete_upload_can_resume_before_it_is_consumed(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {PROMPT_ATTACHMENT_UPLOAD_ROOT_ENV: temp_dir},
        ):
            upload_id = create_mcp_image_upload(42, "client-a", 8)
            append_mcp_image_upload_chunk(upload_id, 42, "client-a", 0, "aGVs")

            with self.assertRaisesRegex(ValueError, "未完了"):
                consume_mcp_image_upload(42, "client-a", upload_id)

            append_mcp_image_upload_chunk(upload_id, 42, "client-a", 1, "bG8=")
            self.assertEqual(consume_mcp_image_upload(42, "client-a", upload_id), "aGVsbG8=")

    def test_deletes_an_unfinished_upload_for_cancellation(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {PROMPT_ATTACHMENT_UPLOAD_ROOT_ENV: temp_dir},
        ):
            upload_id = create_mcp_image_upload(42, "client-a", 8)
            append_mcp_image_upload_chunk(upload_id, 42, "client-a", 0, "aGVs")

            delete_mcp_image_upload(upload_id, 42, "client-a")

            with self.assertRaisesRegex(ValueError, "有効期限"):
                consume_mcp_image_upload(42, "client-a", upload_id)

    def test_cleanup_retries_a_claimed_directory_after_removal_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {PROMPT_ATTACHMENT_UPLOAD_ROOT_ENV: temp_dir},
        ):
            with patch("services.mcp_image_upload_session.time.time", return_value=100.0):
                upload_id = create_mcp_image_upload(42, "client-a", 8)
            with patch(
                "services.mcp_image_upload_session._remove_session_directory",
                side_effect=OSError("disk unavailable"),
            ), patch("services.mcp_image_upload_session.logger.warning") as warning:
                deleted = cleanup_expired_mcp_image_uploads(
                    now=100.0 + mcp_image_upload_session.MCP_IMAGE_UPLOAD_TTL_SECONDS,
                )

            self.assertEqual(deleted, 0)
            warning.assert_called_once()
            staging_root = os.path.join(temp_dir, ".mcp-image-uploads")
            self.assertTrue(any(name.startswith(f"{upload_id}.deleting-") for name in os.listdir(staging_root)))
            self.assertEqual(
                cleanup_expired_mcp_image_uploads(
                    now=100.0 + mcp_image_upload_session.MCP_IMAGE_UPLOAD_TTL_SECONDS,
                ),
                1,
            )

    def test_chunked_png_uses_the_shared_image_processing_pipeline(self):
        source_buffer = BytesIO()
        Image.new("RGB", (18, 12), color="navy").save(source_buffer, format="PNG")
        encoded = base64.b64encode(source_buffer.getvalue()).decode("ascii")
        split_at = len(encoded) // 2

        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {PROMPT_ATTACHMENT_UPLOAD_ROOT_ENV: temp_dir},
        ):
            upload_id = create_mcp_image_upload(42, "client-a", len(encoded))
            append_mcp_image_upload_chunk(upload_id, 42, "client-a", 0, encoded[:split_at])
            append_mcp_image_upload_chunk(upload_id, 42, "client-a", 1, encoded[split_at:])

            assembled = consume_mcp_image_upload(42, "client-a", upload_id)
            attachment = save_mcp_prompt_image(assembled, 42)
            delete_consumed_mcp_image_upload(upload_id, 42, "client-a")

        self.assertEqual(attachment["width"], "18")
        self.assertEqual(attachment["height"], "12")
        self.assertEqual(attachment["media_type"], "image/webp")



if __name__ == "__main__":
    unittest.main()
