import unittest

from services.avatar_storage import (
    AVATAR_PUBLIC_URL_PREFIX,
    AVATAR_URL_MAX_LENGTH,
    DEFAULT_AVATAR_URL,
    build_avatar_public_url,
    normalize_avatar_url,
)


class AvatarStorageTestCase(unittest.TestCase):
    # 日本語: 保存済みファイル名から公開URLが1つの接頭辞で組み立てられることを検証します。
    # English: Verify the public URL is built from the single shared prefix.
    def test_builds_the_public_url_from_the_shared_prefix(self):
        self.assertEqual(
            build_avatar_public_url("avatar_abc123.png"),
            f"{AVATAR_PUBLIC_URL_PREFIX}/avatar_abc123.png",
        )

    # 日本語: 別のパスへ逸れるファイル名を拒否することを検証します。
    # English: Verify filenames that would escape the prefix are rejected.
    def test_rejects_a_filename_that_is_not_a_single_path_segment(self):
        for filename in (None, "", "   ", "../secret.png", "dir/avatar.png", "avatar.png?x=1"):
            with self.subTest(filename=filename):
                with self.assertRaises(ValueError):
                    build_avatar_public_url(filename)

    # 日本語: 空や長すぎるURLは既定アイコンへ正規化されることを検証します。
    # English: Verify blank or over-long URLs normalize to the default icon.
    def test_normalizes_blank_and_over_long_urls_to_the_default_icon(self):
        self.assertEqual(normalize_avatar_url(None), DEFAULT_AVATAR_URL)
        self.assertEqual(normalize_avatar_url("   "), DEFAULT_AVATAR_URL)
        self.assertEqual(
            normalize_avatar_url("/static/uploads/" + "x" * AVATAR_URL_MAX_LENGTH),
            DEFAULT_AVATAR_URL,
        )
        self.assertEqual(
            normalize_avatar_url("  /static/uploads/avatar_abc123.png  "),
            "/static/uploads/avatar_abc123.png",
        )


if __name__ == "__main__":
    unittest.main()
