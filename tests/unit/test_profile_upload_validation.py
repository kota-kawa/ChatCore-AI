import io
import unittest

from blueprints.chat.profile import _save_avatar_file


class ProfileUploadValidationTestCase(unittest.TestCase):
    def test_rejects_disallowed_extension(self):
        avatar = io.BytesIO(b"<html>bad</html>")
        with self.assertRaisesRegex(ValueError, "JPG / PNG / GIF / WebP"):
            _save_avatar_file(
                "/tmp",
                avatar,
                "payload.html",
                "text/html",
            )

    def test_rejects_mismatched_content_type(self):
        png_payload = b"\x89PNG\r\n\x1a\n" + b"\x00" * 128
        avatar = io.BytesIO(png_payload)
        with self.assertRaisesRegex(ValueError, "画像ファイルのみ"):
            _save_avatar_file(
                "/tmp",
                avatar,
                "avatar.png",
                "text/plain",
            )

    def test_rejects_when_signature_and_extension_mismatch(self):
        png_payload = b"\x89PNG\r\n\x1a\n" + b"\x00" * 128
        avatar = io.BytesIO(png_payload)
        with self.assertRaisesRegex(ValueError, "拡張子と画像形式"):
            _save_avatar_file(
                "/tmp",
                avatar,
                "avatar.jpg",
                "image/jpeg",
            )

    def test_rejects_oversized_payload(self):
        oversized_jpeg = b"\xff\xd8\xff" + b"\x00" * (5 * 1024 * 1024 + 8)
        avatar = io.BytesIO(oversized_jpeg)
        with self.assertRaisesRegex(ValueError, "5MB以下"):
            _save_avatar_file(
                "/tmp",
                avatar,
                "avatar.jpg",
                "image/jpeg",
            )


if __name__ == "__main__":
    unittest.main()
