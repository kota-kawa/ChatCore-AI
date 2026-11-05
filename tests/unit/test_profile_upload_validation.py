"""プロフィール画像の保存関数 _save_avatar_file が、拡張子・Content-Type・署名・サイズの不正を ValueError で拒否することを検証するテスト。

Tests that _save_avatar_file rejects bad extensions, content types, signatures and sizes with a ValueError.
"""

import io
import unittest

from blueprints.chat.profile import _save_avatar_file


# 日本語: プロフィール画像の保存関数 _save_avatar_file が、不正なアップロードを ValueError で拒否することを検証するクラスです。
# English: Test case class to verify the functionality and specifications of Profile Upload Validation.
class ProfileUploadValidationTestCase(unittest.TestCase):
    # 日本語: 許可されていない拡張子のファイルを拒否することを検証します。
    # English: Verify that a file with a disallowed extension is rejected.
    def test_rejects_disallowed_extension(self):
        avatar = io.BytesIO(b"<html>bad</html>")
        # 許可されていない拡張子は、案内メッセージ付きの ValueError で拒否される。
        # A disallowed extension is rejected with a ValueError carrying the guidance message.
        with self.assertRaisesRegex(ValueError, "JPG / PNG / GIF / WebP"):
            _save_avatar_file(
                "/tmp",
                avatar,
                "payload.html",
                "text/html",
            )

    # 日本語: Content-Type が画像と一致しないアップロードを拒否することを検証します。
    # English: Verify that an upload whose content type does not match an image is rejected.
    def test_rejects_mismatched_content_type(self):
        png_payload = b"\x89PNG\r\n\x1a\n" + b"\x00" * 128
        avatar = io.BytesIO(png_payload)
        # Content-Type が画像でなければ、画像のみ許可の ValueError で拒否される。
        # A non-image Content-Type is rejected with the images-only ValueError.
        with self.assertRaisesRegex(ValueError, "画像ファイルのみ"):
            _save_avatar_file(
                "/tmp",
                avatar,
                "avatar.png",
                "text/plain",
            )

    # 日本語: 画像の署名と拡張子が食い違うアップロードを拒否することを検証します。
    # English: Verify that an upload whose signature and extension disagree is rejected.
    def test_rejects_when_signature_and_extension_mismatch(self):
        png_payload = b"\x89PNG\r\n\x1a\n" + b"\x00" * 128
        avatar = io.BytesIO(png_payload)
        # 画像の署名（先頭バイト）と拡張子が食い違えば、ValueError で拒否される。
        # A mismatch between the image signature (leading bytes) and the extension raises a ValueError.
        with self.assertRaisesRegex(ValueError, "拡張子と画像形式"):
            _save_avatar_file(
                "/tmp",
                avatar,
                "avatar.jpg",
                "image/jpeg",
            )

    # 日本語: サイズ上限を超えたアップロードを拒否することを検証します。
    # English: Verify that an oversized upload is rejected.
    def test_rejects_oversized_payload(self):
        oversized_jpeg = b"\xff\xd8\xff" + b"\x00" * (5 * 1024 * 1024 + 8)
        avatar = io.BytesIO(oversized_jpeg)
        # 上限（5MB）を超えるデータは、ValueError で拒否される。
        # Data above the 5 MB cap is rejected with a ValueError.
        with self.assertRaisesRegex(ValueError, "5MB以下"):
            _save_avatar_file(
                "/tmp",
                avatar,
                "avatar.jpg",
                "image/jpeg",
            )


if __name__ == "__main__":
    unittest.main()
