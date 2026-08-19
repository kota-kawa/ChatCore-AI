from __future__ import annotations

from io import BytesIO
import unittest
from unittest.mock import patch

from PIL import Image

from services.prompt_attachment_processing import process_prompt_attachment


def _image_bytes(
    image_format: str = "PNG",
    *,
    size: tuple[int, int] = (64, 48),
) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, color="teal").save(buffer, format=image_format)
    return buffer.getvalue()


class PromptAttachmentProcessingTestCase(unittest.TestCase):
    def test_normalizes_to_bounded_webp_variants_without_exif(self):
        source = _image_bytes("JPEG", size=(3000, 1000))

        processed = process_prompt_attachment(source)

        self.assertLessEqual(processed.width, 2048)
        self.assertLessEqual(processed.height, 2048)
        self.assertLessEqual(len(processed.display_bytes), 2 * 1024 * 1024)
        self.assertLessEqual(len(processed.thumbnail_bytes), 400 * 1024)
        with Image.open(BytesIO(processed.display_bytes)) as output:
            self.assertEqual(output.format, "WEBP")
            self.assertEqual(dict(output.getexif()), {})

    def test_rejects_corrupt_payload_that_only_has_a_valid_signature(self):
        with self.assertRaisesRegex(ValueError, "読み取れません"):
            process_prompt_attachment(b"\x89PNG\r\n\x1a\nnot-a-real-image")

    def test_rejects_images_exceeding_the_pixel_limit(self):
        source = _image_bytes(size=(64, 64))
        with patch("services.prompt_attachment_processing.PROMPT_ATTACHMENT_MAX_PIXELS", 100):
            with self.assertRaisesRegex(ValueError, "総ピクセル数"):
                process_prompt_attachment(source)

    def test_rejects_animated_uploads(self):
        first = Image.new("RGB", (8, 8), color="red")
        second = Image.new("RGB", (8, 8), color="blue")
        buffer = BytesIO()
        first.save(buffer, format="GIF", save_all=True, append_images=[second], loop=0)

        with self.assertRaisesRegex(ValueError, "アニメーション"):
            process_prompt_attachment(buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
