"""アカウントが所有するユーザーデータ(users 行)の永続化。

プロフィール項目、ログイン用メール、希望ロケール、アカウント削除、標準タスクの初期コピーを扱う。
認証プロバイダーの情報は auth_identity_repository、Skill の設定列は Skill のリポジトリが持つ。

Async SQLAlchemy persistence for account-owned user data.

This repository owns the ``users`` row itself: the profile fields, the
sign-in email and the preferred locale, plus account deletion and the
bundled task seed.  Authentication provider metadata stays in
:mod:`services.repositories.auth_identity_repository`, and the Skill
preference column stays with the Skill repository that owns that feature.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import delete, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from services.avatar_storage import normalize_avatar_url
from services.models import (
    ChatRoom,
    MemoEntry,
    MemoryFact,
    Prompt,
    PromptLike,
    Task,
    User,
    UserAuthProvider,
    UserPasskey,
)

# 日本語: チャットのツールが編集できるプロフィール項目。変更検知のフィンガープリントにもこの順で使う。
# English: Profile fields editable by the chat tools; also the ordered input of the change-detection fingerprint.
PROFILE_SETTINGS_FINGERPRINT_FIELDS = (
    "username",
    "bio",
    "llm_profile_context",
    "preferred_locale",
)


def profile_settings_fingerprint(profile: dict[str, Any]) -> str:
    """プロフィール項目の、安定した(元に戻せない)比較用トークンを返す。

    チャットのツールが提案した時点と承認時点で内容が変わっていないかの確認に使う。

    Return a stable, non-reversible comparison token for the persistent profile fields.
    """
    canonical = json.dumps(
        [profile.get(field) for field in PROFILE_SETTINGS_FINGERPRINT_FIELDS],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class UserRepository:
    """``users`` 行とそのプロフィール項目、アカウント削除を扱うリポジトリ。

    commit はせず、トランザクションは Service 側が持つ(1 つの作業単位ごとに独立した AsyncSession を渡す)。

    Repository for the ``users`` row, its profile fields and account cleanup.

    The repository never commits.  Services own the transaction and pass an
    isolated ``AsyncSession`` for one unit of work.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # プロフィールと設定
    # Profile and preferences ------------------------------------------------

    async def get_user_by_id(self, user_id: int) -> dict[str, Any] | None:
        user = await self.session.get(User, user_id)
        return self._serialize_user(user) if user is not None else None

    async def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        user = await self.session.scalar(select(User).where(User.email == email).limit(1))
        return self._serialize_user(user) if user is not None else None

    async def get_chat_profile_settings(self, user_id: int) -> dict[str, Any] | None:
        """プロフィール設定ツールに公開する項目だけを読み出す。メールとアバターは取得しない。

        Read only fields exposed to the profile settings tools; never fetch email or avatar.
        """
        result = await self.session.execute(
            select(
                User.id,
                User.username,
                User.bio,
                User.llm_profile_context,
                User.preferred_locale,
            ).where(User.id == int(user_id))
        )
        row = result.mappings().first()
        if row is None:
            return None
        return {
            field: row[field]
            for field in ("id", "username", "bio", "llm_profile_context", "preferred_locale")
        }

    async def update_chat_profile_settings_if_unchanged(
        self,
        user_id: int,
        *,
        expected_fingerprint: str | None,
        updates: dict[str, Any],
    ) -> bool | None:
        """行ロックを持ったまま、プロフィールを比較して更新する。

        ``None`` は認証済みユーザーの行が無くなったこと、``False`` は提案時のスナップショットから内容が変わったことを表す。
        トランザクションは呼び出し側が持つため、承認の確定とこの書き込みは一緒に commit または rollback される。

        Compare and update the user's profile while holding its row lock.

        ``None`` means the authenticated user's row disappeared; ``False`` means the snapshot
        changed since proposal time. The caller owns the transaction, so approval settlement and
        this write commit or roll back together.
        """
        user = await self.session.scalar(
            select(User).where(User.id == int(user_id)).with_for_update()
        )
        if user is None:
            return None
        current = {
            "username": user.username,
            "bio": user.bio,
            "llm_profile_context": user.llm_profile_context,
            "preferred_locale": user.preferred_locale,
        }
        if expected_fingerprint is not None and profile_settings_fingerprint(current) != expected_fingerprint:
            return False

        # 日本語: 想定外の列を更新させないよう、許可した項目以外が含まれていれば拒否する。
        # English: Reject updates that include anything outside the allowed fields so no unexpected column can be written.
        allowed_fields = {"username", "bio", "llm_profile_context", "preferred_locale"}
        if set(updates) - allowed_fields:
            raise ValueError("profile settings update contains an unsupported field")
        if not updates:
            return True
        result = await self.session.execute(
            update(User).where(User.id == int(user_id)).values(**updates)
        )
        return bool(result.rowcount)

    async def list_active_avatar_urls(self) -> list[str]:
        """Read every avatar URL still referenced by a user row.

        アバターの孤児ファイル掃除は、プロンプト添付と同じく DB を正として
        照合する。保存済みの値は正規化せずそのまま返し、旧形式のURLも
        参照済みとして扱えるようにする。
        English: The avatar reconciler treats the database as the source of
        truth. Stored values are returned verbatim so legacy URLs still count
        as referenced.
        """
        values = await self.session.scalars(select(User.avatar_url).where(User.avatar_url.is_not(None)))
        return [str(value) for value in values if value]

    # 日本語: プロフィールを更新する。avatar_url が None のときはアバターを変更しない。
    # English: Updates the profile; a None avatar_url leaves the avatar unchanged.
    async def update_user_profile(
        self,
        user_id: int,
        *,
        username: str,
        bio: str,
        avatar_url: str | None,
        llm_profile_context: str,
    ) -> bool:
        values: dict[str, Any] = {
            "username": username,
            "bio": bio,
            "llm_profile_context": llm_profile_context,
        }
        if avatar_url is not None:
            values["avatar_url"] = avatar_url
        result = await self.session.execute(update(User).where(User.id == user_id).values(**values))
        return bool(result.rowcount)

    # 日本語: メールアドレスの変更を確定する。他のユーザーが(大文字小文字を無視して)同じアドレスを持っていれば False。
    # English: Commits an email change; returns False if another user already holds the address (case-insensitive).
    async def commit_email_change(self, user_id: int, new_email: str) -> bool:
        # 日本語: SELECT ... FOR UPDATE は見つかった行しかロックしないため、対象のメールに一致する行が無いと何もロックされない。
        # 大文字小文字だけが違う 2 つの変更が同時に走ると、どちらも 0 行を見て両方 commit し、lower(email) の確認が防ぐはずの重複ができる。
        # 正規化した対象メールをキーにした advisory lock で同じアドレスの取得を直列化し、スキーマ変更なしにこの隙間を塞ぐ。
        # services/guest_prompt_service.py のゲスト投稿の回数制限ロックと同じ方式。
        # English: A `SELECT ... FOR UPDATE` locks the rows it finds, but when no row matches
        # the target email it locks nothing.  Two concurrent changes to emails that
        # only differ by case (`Foo@x.com` / `foo@x.com`) then both see zero rows and
        # both commit, producing a duplicate the `lower(email)` check was meant to
        # block.  An advisory lock keyed on the normalized target email serializes
        # any concurrent attempts to claim the same address, closing that window
        # without a schema change.  Same pattern as the guest-prompt quota lock in
        # ``services/guest_prompt_service.py``.
        normalized_email = new_email.strip().lower()
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
            {"lock_key": f"user-email-change:{normalized_email}"},
        )
        current = await self.session.scalar(
            select(User).where(func.lower(User.email) == func.lower(new_email)).with_for_update()
        )
        if current is not None and current.id != user_id:
            return False
        result = await self.session.execute(update(User).where(User.id == user_id).values(email=new_email))
        return bool(result.rowcount)

    async def get_user_preferred_locale(self, user_id: int) -> str | None:
        return await self.session.scalar(select(User.preferred_locale).where(User.id == user_id))

    async def update_user_preferred_locale(self, user_id: int, locale: str) -> bool:
        result = await self.session.execute(update(User).where(User.id == user_id).values(preferred_locale=locale))
        return bool(result.rowcount)

    # アカウントのライフサイクル
    # Account lifecycle ------------------------------------------------------

    # 日本語: アカウントを削除する。users 行をロックしたうえで、旧来の削除手順にある表を明示的に消し、残
    # りは ON DELETE CASCADE と最後の users 削除に任せる。
    # English: Deletes the account: locks the users row, explicitly deletes the tables from the legacy workflow,
    # and leaves the rest to ON DELETE CASCADE and the final users delete.
    async def delete_account(self, user_id: int) -> bool:
        user = await self.session.scalar(
            select(User)
            .where(User.id == int(user_id))
            .with_for_update()
        )
        if user is None:
            return False

        # 旧処理の明示削除を残し、その他の所有行は同じトランザクションのusers削除とCASCADEに任せる。
        # These are the explicit deletes from the legacy account workflow.
        # Other user-owned rows use ON DELETE CASCADE from users and are
        # removed by the final ORM delete in the same transaction.
        for model in (
            PromptLike,
            MemoEntry,
            MemoryFact,
            UserAuthProvider,
            UserPasskey,
            ChatRoom,
            Task,
            Prompt,
        ):
            await self.session.execute(
                delete(model).where(model.user_id == int(user_id))
            )

        await self.session.execute(
            delete(User).where(User.id == int(user_id))
        )
        return True

    async def copy_default_tasks(self, user_id: int) -> None:
        """同梱の標準タスクをユーザーへコピーする。advisory lock により同時実行でも重複しない。

        同じ system_task_key か、同名(大文字小文字・前後空白を無視)のタスクが既にあるものはスキップする。

        Copy the bundled catalog while retaining the advisory-lock semantics.
        """

        from services.default_tasks import default_task_rows

        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(:user_id)"),
            {"user_id": int(user_id)},
        )
        for (
            system_task_key,
            system_task_revision,
            name,
            prompt_template,
            response_rules,
            output_skeleton,
            input_examples,
            output_examples,
            display_order,
        ) in default_task_rows(include_key=True):
            existing_id = await self.session.scalar(
                select(Task.id)
                .where(
                    Task.user_id == int(user_id),
                    or_(
                        Task.system_task_key == system_task_key,
                        func.lower(func.btrim(Task.name))
                        == func.lower(func.btrim(name)),
                    ),
                )
                .limit(1)
            )
            if existing_id is not None:
                continue

            statement = (
                pg_insert(Task)
                .values(
                    user_id=int(user_id),
                    system_task_key=system_task_key,
                    system_task_revision=system_task_revision,
                    name=name,
                    prompt_template=prompt_template,
                    response_rules=response_rules,
                    output_skeleton=output_skeleton,
                    input_examples=input_examples,
                    output_examples=output_examples,
                    display_order=display_order,
                )
                .on_conflict_do_nothing()
            )
            await self.session.execute(statement)

    # 内部ヘルパー
    # Internal helpers -------------------------------------------------------

    @staticmethod
    def _serialize_user(user: User) -> dict[str, Any]:
        # 日本語: 認証プロバイダーの情報は ``user_auth_providers`` にある。ORM を正規化済みスキーマに合わせたときに users から
        # 旧プロバイダー列を削除したので、この payload は User エンティティが持つ項目だけにとどめる。
        # English: Authentication-provider metadata lives in ``user_auth_providers``.
        # The legacy provider columns were removed from ``users`` when the ORM
        # was aligned with the normalized schema, so keep this payload limited
        # to fields owned by the User entity.
        return {
            "id": user.id,
            "email": user.email,
            "is_verified": user.is_verified,
            "created_at": user.created_at,
            "username": user.username,
            "bio": user.bio,
            # 旧 `/static/uploads/...` を現行の配信URLへ読み替えて返す。
            # Rewrite the legacy `/static/uploads/...` value to the served URL.
            "avatar_url": normalize_avatar_url(user.avatar_url),
            "llm_profile_context": user.llm_profile_context,
            "generative_ui_skill_enabled": user.generative_ui_skill_enabled,
            "memo_tools_skill_enabled": user.memo_tools_skill_enabled,
            "prompt_tools_skill_enabled": user.prompt_tools_skill_enabled,
            "preferred_locale": user.preferred_locale,
        }
