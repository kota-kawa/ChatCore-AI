import io
import unittest

from blueprints.chat.profile import _save_avatar_file


# 日本語: Profile Upload Validationの機能や仕様を検証するテストクラスです。
# English: Test case class to verify the functionality and specifications of Profile Upload Validation.
class ProfileUploadValidationTestCase(unittest.TestCase):
    # 日本語: 拒否するdisallowedextensionことを検証します。
    # English: Verify that rejects disallowed extension.
    def test_rejects_disallowed_extension(self):
        avatar = io.BytesIO(b"<html>bad</html>")
        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with self.assertRaisesRegex(ValueError, "JPG / PNG / GIF / WebP"):
            _save_avatar_file(
                "/tmp",
                avatar,
                "payload.html",
                "text/html",
            )

    # 日本語: 拒否するmismatchedcontenttypeことを検証します。
    # English: Verify that rejects mismatched content type.
    def test_rejects_mismatched_content_type(self):
        png_payload = b"\x89PNG\r\n\x1a\n" + b"\x00" * 128
        avatar = io.BytesIO(png_payload)
        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with self.assertRaisesRegex(ValueError, "画像ファイルのみ"):
            _save_avatar_file(
                "/tmp",
                avatar,
                "avatar.png",
                "text/plain",
            )

    # 日本語: signatureのとき、およびextensionmismatch、拒否することを検証します。
    # English: Verify that rejects when signature and extension mismatch.
    def test_rejects_when_signature_and_extension_mismatch(self):
        png_payload = b"\x89PNG\r\n\x1a\n" + b"\x00" * 128
        avatar = io.BytesIO(png_payload)
        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with self.assertRaisesRegex(ValueError, "拡張子と画像形式"):
            _save_avatar_file(
                "/tmp",
                avatar,
                "avatar.jpg",
                "image/jpeg",
            )

    # 日本語: 拒否するoversizedペイロードことを検証します。
    # English: Verify that rejects oversized payload.
    def test_rejects_oversized_payload(self):
        oversized_jpeg = b"\xff\xd8\xff" + b"\x00" * (5 * 1024 * 1024 + 8)
        avatar = io.BytesIO(oversized_jpeg)
        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with self.assertRaisesRegex(ValueError, "5MB以下"):
            _save_avatar_file(
                "/tmp",
                avatar,
                "avatar.jpg",
                "image/jpeg",
            )


if __name__ == "__main__":
    unittest.main()
