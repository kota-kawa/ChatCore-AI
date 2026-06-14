import io
import unittest

from blueprints.chat.profile import _save_avatar_file


# 日本語: ProfileUploadValidationTestCase に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to ProfileUploadValidationTestCase.
class ProfileUploadValidationTestCase(unittest.TestCase):
    # 日本語: test rejects disallowed extension のテスト検証を担当します。
    # English: Handle verifying test behavior for test rejects disallowed extension.
    def test_rejects_disallowed_extension(self):
        avatar = io.BytesIO(b"<html>bad</html>")
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with self.assertRaisesRegex(ValueError, "JPG / PNG / GIF / WebP"):
            _save_avatar_file(
                "/tmp",
                avatar,
                "payload.html",
                "text/html",
            )

    # 日本語: test rejects mismatched content type のテスト検証を担当します。
    # English: Handle verifying test behavior for test rejects mismatched content type.
    def test_rejects_mismatched_content_type(self):
        png_payload = b"\x89PNG\r\n\x1a\n" + b"\x00" * 128
        avatar = io.BytesIO(png_payload)
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with self.assertRaisesRegex(ValueError, "画像ファイルのみ"):
            _save_avatar_file(
                "/tmp",
                avatar,
                "avatar.png",
                "text/plain",
            )

    # 日本語: test rejects when signature and extension mismatch のテスト検証を担当します。
    # English: Handle verifying test behavior for test rejects when signature and extension mismatch.
    def test_rejects_when_signature_and_extension_mismatch(self):
        png_payload = b"\x89PNG\r\n\x1a\n" + b"\x00" * 128
        avatar = io.BytesIO(png_payload)
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with self.assertRaisesRegex(ValueError, "拡張子と画像形式"):
            _save_avatar_file(
                "/tmp",
                avatar,
                "avatar.jpg",
                "image/jpeg",
            )

    # 日本語: test rejects oversized payload のテスト検証を担当します。
    # English: Handle verifying test behavior for test rejects oversized payload.
    def test_rejects_oversized_payload(self):
        oversized_jpeg = b"\xff\xd8\xff" + b"\x00" * (5 * 1024 * 1024 + 8)
        avatar = io.BytesIO(oversized_jpeg)
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with self.assertRaisesRegex(ValueError, "5MB以下"):
            _save_avatar_file(
                "/tmp",
                avatar,
                "avatar.jpg",
                "image/jpeg",
            )


if __name__ == "__main__":
    unittest.main()
