import asyncio
import json
import os
import tempfile
import time
import unittest
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch

from blueprints.chat.avatar_media import get_avatar_media
from blueprints.chat.profile import _save_avatar_file
from services.avatar_storage import (
    AVATAR_PUBLIC_URL_PREFIX,
    AVATAR_UPLOAD_ROOT_ENV,
    AVATAR_URL_MAX_LENGTH,
    DEFAULT_AVATAR_URL,
    LEGACY_AVATAR_URL_PREFIX,
    avatar_filename_from_url,
    build_avatar_public_url,
    cleanup_unreferenced_avatars,
    get_avatar_upload_root,
    normalize_avatar_url,
    resolve_avatar_path,
)
from services.error_messages import ERROR_AVATAR_NOT_FOUND
from services.repositories.shared_content_repository import _rows
from services.repositories.user_repository import UserRepository


def _png_bytes() -> bytes:
    # 実ファイルを読ませる必要はないため、マジックバイトだけを持つ最小データを使う。
    # The route only stats the file, so magic bytes plus filler are enough.
    return b"\x89PNG\r\n\x1a\n" + b"0" * 64


class AvatarStorageTestCase(unittest.TestCase):
    # 日本語: 保存済みファイル名から公開URLが1つの接頭辞で組み立てられることを検証します。
    # English: Verify the public URL is built from the single shared prefix.
    def test_builds_the_public_url_from_the_shared_prefix(self):
        self.assertEqual(
            build_avatar_public_url("avatar_abc123.png"),
            f"{AVATAR_PUBLIC_URL_PREFIX}/avatar_abc123.png",
        )

    # 日本語: 公開URLの接頭辞が nginx の backend location 正規表現に一致することを検証します。
    # English: Verify the public prefix falls under the nginx backend location regex.
    def test_public_prefix_is_routed_to_the_backend(self):
        self.assertTrue(AVATAR_PUBLIC_URL_PREFIX.startswith("/api/"))

    # 日本語: 別のパスへ逸れるファイル名を拒否することを検証します。
    # English: Verify filenames that would escape the prefix are rejected.
    def test_rejects_a_filename_that_is_not_a_single_path_segment(self):
        for filename in (None, "", "   ", "../secret.png", "dir/avatar.png", "avatar.png?x=1"):
            with self.subTest(filename=filename):
                with self.assertRaises(ValueError):
                    build_avatar_public_url(filename)

    # 日本語: パストラバーサルや未対応拡張子がパス解決で拒否されることを検証します。
    # English: Verify traversal and unsupported extensions are refused when resolving a path.
    def test_path_resolution_rejects_unsafe_or_unsupported_filenames(self):
        for filename in ("../secret.png", "nested/avatar.png", "avatar.svg", ".hidden.png", "..%2Fsecret.png"):
            with self.subTest(filename=filename), self.assertRaises(ValueError):
                resolve_avatar_path(filename)

    # 日本語: 既定の保存先が frontend/public の外にあることを検証します。
    # English: Verify the default storage root sits outside frontend/public.
    def test_default_upload_root_is_outside_frontend_public(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(AVATAR_UPLOAD_ROOT_ENV, None)
            root = get_avatar_upload_root()

        self.assertTrue(root.endswith(os.path.join("data", "uploads", "avatars")))
        self.assertNotIn(os.path.join("frontend", "public"), root)

    # 日本語: 保存先が環境変数で差し替えられることを検証します。
    # English: Verify the storage root follows the environment variable.
    def test_upload_root_follows_the_environment_variable(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {AVATAR_UPLOAD_ROOT_ENV: temp_dir},
        ):
            self.assertEqual(get_avatar_upload_root(), os.path.abspath(temp_dir))

    # 日本語: 空や長すぎるURLは既定アイコンへ正規化されることを検証します。
    # English: Verify blank or over-long URLs normalize to the default icon.
    def test_normalizes_blank_and_over_long_urls_to_the_default_icon(self):
        self.assertEqual(normalize_avatar_url(None), DEFAULT_AVATAR_URL)
        self.assertEqual(normalize_avatar_url("   "), DEFAULT_AVATAR_URL)
        self.assertEqual(
            normalize_avatar_url("/static/uploads/" + "x" * AVATAR_URL_MAX_LENGTH),
            DEFAULT_AVATAR_URL,
        )

    # 日本語: DBに残る旧 `/static/uploads/` 形式が現行の配信URLへ読み替えられることを検証します。
    # English: Verify the legacy `/static/uploads/` value is rewritten to the served URL.
    def test_legacy_static_uploads_url_is_normalized_to_the_backend_route(self):
        self.assertEqual(
            normalize_avatar_url("  /static/uploads/avatar_abc123.png  "),
            f"{AVATAR_PUBLIC_URL_PREFIX}/avatar_abc123.png",
        )
        self.assertEqual(
            normalize_avatar_url(f"{AVATAR_PUBLIC_URL_PREFIX}/avatar_abc123.png"),
            f"{AVATAR_PUBLIC_URL_PREFIX}/avatar_abc123.png",
        )

    # 日本語: 既定アイコンと外部URLは書き換えずにそのまま返すことを検証します。
    # English: Verify the default icon and remote URLs are returned untouched.
    def test_default_icon_and_remote_urls_are_left_untouched(self):
        self.assertEqual(normalize_avatar_url(DEFAULT_AVATAR_URL), DEFAULT_AVATAR_URL)
        remote = "https://lh3.googleusercontent.com/a/photo.png"
        self.assertEqual(normalize_avatar_url(remote), remote)
        self.assertIsNone(
            avatar_filename_from_url("https://cdn.example.com/static/uploads/avatar.png")
        )
        self.assertIsNone(
            avatar_filename_from_url("//cdn.example.com/static/uploads/avatar.png")
        )

    # 日本語: 旧形式・現行形式のどちらからも同じファイル名を取り出せることを検証します。
    # English: Verify both URL shapes resolve to the same stored filename.
    def test_both_url_shapes_resolve_to_the_same_filename(self):
        self.assertEqual(
            avatar_filename_from_url(f"{LEGACY_AVATAR_URL_PREFIX}/avatar_abc123.png"),
            "avatar_abc123.png",
        )
        self.assertEqual(
            avatar_filename_from_url(f"{AVATAR_PUBLIC_URL_PREFIX}/avatar_abc123.png"),
            "avatar_abc123.png",
        )
        self.assertIsNone(avatar_filename_from_url(f"{LEGACY_AVATAR_URL_PREFIX}/../secret.png"))

    # 日本語: DBから読んだ旧形式のURLが、利用者向けの応答では現行URLになることを検証します。
    # English: Verify rows read from the database expose the current URL shape.
    def test_stored_legacy_urls_are_rewritten_on_read(self):
        user = SimpleNamespace(
            id=1,
            email="a@example.com",
            is_verified=True,
            created_at=None,
            username="a",
            bio="",
            avatar_url="/static/uploads/avatar_abc123.png",
            llm_profile_context="",
            generative_ui_skill_enabled=False,
            preferred_locale="ja",
        )
        self.assertEqual(
            UserRepository._serialize_user(user)["avatar_url"],
            f"{AVATAR_PUBLIC_URL_PREFIX}/avatar_abc123.png",
        )

        mappings = SimpleNamespace(
            all=lambda: [
                {"author_avatar_url": "/static/uploads/avatar_abc123.png"},
                {"avatar_url": DEFAULT_AVATAR_URL},
            ]
        )
        rows = _rows(SimpleNamespace(mappings=lambda: mappings))
        self.assertEqual(rows[0]["author_avatar_url"], f"{AVATAR_PUBLIC_URL_PREFIX}/avatar_abc123.png")
        self.assertEqual(rows[1]["avatar_url"], DEFAULT_AVATAR_URL)


class AvatarMediaRouteTestCase(unittest.TestCase):
    # 日本語: アップロードしたアバターが配信ルートから取得できることを検証します。
    # English: Verify an uploaded avatar is served back by the media route.
    def test_saved_avatar_is_served_by_the_media_route(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {AVATAR_UPLOAD_ROOT_ENV: temp_dir},
        ):
            avatar_url = _save_avatar_file(
                get_avatar_upload_root(),
                BytesIO(_png_bytes()),
                "portrait.png",
                "image/png",
            )
            self.assertTrue(avatar_url.startswith(f"{AVATAR_PUBLIC_URL_PREFIX}/"))

            filename = avatar_url.rsplit("/", 1)[-1]
            stored_path = resolve_avatar_path(filename)
            self.assertTrue(os.path.isfile(stored_path))
            self.assertEqual(os.path.dirname(stored_path), os.path.realpath(temp_dir))

            response = asyncio.run(get_avatar_media(filename))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.path, stored_path)
            self.assertEqual(response.media_type, "image/png")
            self.assertEqual(response.headers["x-content-type-options"], "nosniff")
            self.assertEqual(
                response.headers["cache-control"],
                "public, max-age=31536000, immutable",
            )

    # 日本語: 旧形式のURLを持つユーザーでも、正規化後のURLで同じファイルに届くことを検証します。
    # English: Verify a user still holding a legacy URL reaches the same stored file.
    def test_legacy_avatar_url_still_reaches_the_stored_file(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {AVATAR_UPLOAD_ROOT_ENV: temp_dir},
        ):
            saved_url = _save_avatar_file(
                get_avatar_upload_root(),
                BytesIO(_png_bytes()),
                "portrait.png",
                "image/png",
            )
            filename = saved_url.rsplit("/", 1)[-1]
            legacy_url = f"{LEGACY_AVATAR_URL_PREFIX}/{filename}"

            normalized = normalize_avatar_url(legacy_url)
            self.assertEqual(normalized, saved_url)

            response = asyncio.run(get_avatar_media(normalized.rsplit("/", 1)[-1]))
            self.assertEqual(response.status_code, 200)

    # 日本語: 不正なファイル名と存在しないファイルが404になることを検証します。
    # English: Verify invalid filenames and missing files answer 404.
    def test_media_route_returns_404_for_invalid_or_missing_file(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {AVATAR_UPLOAD_ROOT_ENV: temp_dir},
        ):
            responses = {
                name: asyncio.run(get_avatar_media(name))
                for name in ("avatar.svg", "missing.png", "../secret.png", "..%2F..%2Fetc%2Fpasswd")
            }

        for name, response in responses.items():
            with self.subTest(filename=name):
                self.assertEqual(response.status_code, 404)
                payload = json.loads(response.body.decode("utf-8"))
                self.assertEqual(payload["error"], ERROR_AVATAR_NOT_FOUND)

    # 日本語: 保存先の外にあるファイルをシンボリックリンク経由でも配信しないことを検証します。
    # English: Verify a symlink pointing outside the storage root is not served.
    def test_media_route_refuses_a_symlink_escaping_the_upload_root(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            upload_root = os.path.join(temp_dir, "uploads")
            os.makedirs(upload_root)
            secret_path = os.path.join(temp_dir, "secret.png")
            with open(secret_path, "wb") as secret_file:
                secret_file.write(_png_bytes())
            os.symlink(secret_path, os.path.join(upload_root, "linked.png"))

            with patch.dict(os.environ, {AVATAR_UPLOAD_ROOT_ENV: upload_root}):
                with self.assertRaises(ValueError):
                    resolve_avatar_path("linked.png")
                response = asyncio.run(get_avatar_media("linked.png"))

        self.assertEqual(response.status_code, 404)

    # 日本語: 旧保存先に残ったファイルも読み出せることを検証します。
    # English: Verify files left in the former location are still readable.
    def test_media_route_reads_the_legacy_location_as_fallback(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            legacy_path = os.path.join(temp_dir, "legacy.png")
            with open(legacy_path, "wb") as legacy_file:
                legacy_file.write(_png_bytes())
            with patch(
                "blueprints.chat.avatar_media.resolve_avatar_path",
                return_value=os.path.join(temp_dir, "missing.png"),
            ), patch(
                "blueprints.chat.avatar_media.resolve_legacy_avatar_path",
                return_value=legacy_path,
            ):
                response = asyncio.run(get_avatar_media("legacy.png"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.media_type, "image/png")


class AvatarCleanupTestCase(unittest.TestCase):
    @staticmethod
    def _write_old_file(root: str, name: str) -> str:
        path = os.path.join(root, name)
        with open(path, "wb") as file_obj:
            file_obj.write(_png_bytes())
        old = time.time() - (2 * 60 * 60)
        os.utime(path, (old, old))
        return path

    # 日本語: 参照されていない古いアバターだけが削除されることを検証します。
    # English: Verify only unreferenced, aged avatar files are removed.
    def test_cleanup_removes_only_unreferenced_aged_files(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {AVATAR_UPLOAD_ROOT_ENV: temp_dir},
        ):
            referenced = self._write_old_file(temp_dir, "avatar_referenced.png")
            legacy_referenced = self._write_old_file(temp_dir, "avatar_legacy.png")
            orphan = self._write_old_file(temp_dir, "avatar_orphan.png")
            recent_orphan = os.path.join(temp_dir, "avatar_recent.png")
            with open(recent_orphan, "wb") as file_obj:
                file_obj.write(_png_bytes())

            deleted = cleanup_unreferenced_avatars(
                [
                    f"{AVATAR_PUBLIC_URL_PREFIX}/avatar_referenced.png",
                    f"{LEGACY_AVATAR_URL_PREFIX}/avatar_legacy.png",
                    DEFAULT_AVATAR_URL,
                    "https://lh3.googleusercontent.com/a/photo.png",
                ]
            )

            self.assertEqual(deleted, 1)
            self.assertTrue(os.path.isfile(referenced))
            self.assertTrue(os.path.isfile(legacy_referenced))
            self.assertTrue(os.path.isfile(recent_orphan))
            self.assertFalse(os.path.exists(orphan))

    # 日本語: 保存先が存在しない場合でも失敗しないことを検証します。
    # English: Verify cleanup is a no-op when the storage root does not exist.
    def test_cleanup_is_a_no_op_without_a_storage_root(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {AVATAR_UPLOAD_ROOT_ENV: os.path.join(temp_dir, "absent")},
        ):
            self.assertEqual(cleanup_unreferenced_avatars([]), 0)


if __name__ == "__main__":
    unittest.main()
