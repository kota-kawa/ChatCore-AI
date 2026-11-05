"""公開プロンプト・SKILL 投稿の読み取りと、投稿・いいね・コメント・取り込みなどの操作をまとめたサービス。

HTTP や MCP などの transport から再利用できるように、DB 操作は SharedContentRepository などのリポジトリへ委ね、
ここでは入力の正規化、一覧カーソルの検証、公開 URL の組み立て、SKILL の取り込み変換を担当する。

Service for reading public prompt / SKILL posts and for posting, liking, commenting and importing them.

Reusable from transports such as HTTP and MCP: database work is delegated to repositories such as SharedContentRepository,
while this module normalizes input, validates list cursors, builds public URLs and converts SKILL posts for import.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime
from typing import Any, TypeVar

from pydantic import AnyHttpUrl, BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from services.api_errors import ApiServiceError
from services.db import session_scope
from services.error_messages import (
    ERROR_SHARED_SKILL_CONTENT_MISSING,
    ERROR_SHARED_SKILL_INVALID_TYPE,
    ERROR_SHARED_SKILL_NOT_FOUND,
    MESSAGE_SHARED_SKILL_ADDED,
    MESSAGE_SHARED_SKILL_ALREADY_ADDED,
)
from services.prompt_categories import category_keys_matching, normalize_category
from services.prompt_embedding_service import schedule_prompt_embedding
from services.prompt_types import CONTENT_FORMAT_SKILL, CONTENT_FORMATS, MEDIA_TYPES, serialize_axes
from services.repositories.prompt_impression_repository import PromptImpressionRepository
from services.repositories.prompt_resource_repository import PromptResourceRepository
from services.repositories.prompt_view_repository import PromptViewRepository
from services.repositories.shared_content_repository import SharedContentRepository
from services.repositories.user_skill_repository import UserSkillRepository
from services.share_common import ShareContentKind, build_public_share_url, build_share_url
from services.user_skills import normalize_user_skill_instructions

# 日本語: 一覧の既定／最大件数、スニペットの文字数、検索語の最大長。
# English: Default and maximum list size, snippet length, and maximum query length.
SHARED_CONTENT_DEFAULT_LIMIT = 20
SHARED_CONTENT_MAX_LIMIT = 50
SHARED_CONTENT_SNIPPET_LENGTH = 280
SHARED_CONTENT_MAX_QUERY_LENGTH = 500
T = TypeVar("T")


# 日本語: 一覧カーソルが不正、または別の検索条件向けだった場合の例外。
# English: Raised when a list cursor is invalid or belongs to a different set of filters.
class InvalidSharedContentCursorError(ValueError):
    """一覧カーソルが不正、または別の検索条件向けの場合に送出する。"""


# 日本語: 公開投稿の一覧 1 件分（本文は含まずスニペットだけ）。
# English: One entry of the public listing (a snippet instead of the full body).
class PublicSharedContentSummary(BaseModel):
    prompt_id: int
    title: str
    category: str = ""
    description: str = ""
    author: str
    content_format: str
    media_type: str
    snippet: str = ""
    created_at: datetime
    public_url: AnyHttpUrl


# 日本語: 公開投稿の一覧 1 ページ分。next_cursor は次ページがあるときだけ入る。
# English: One page of the public listing; next_cursor is set only when another page exists.
class PublicSharedContentPage(BaseModel):
    items: list[PublicSharedContentSummary] = Field(default_factory=list)
    limit: int
    has_next: bool
    next_cursor: str | None = None


# 日本語: SKILL に付く資源ファイルのメタデータ（本文なし）。
# English: Metadata of a resource file attached to a SKILL (without its content).
class PublicSkillResourceMetadata(BaseModel):
    path: str
    role: str
    language: str = ""
    media_type: str = "text/plain"
    size_bytes: int = Field(default=0, ge=0)
    sha256: str = ""


# 日本語: メタデータに本文を加えた、SKILL の資源ファイル 1 件。
# English: A SKILL resource file: the metadata plus its content.
class PublicSkillResourceDetail(PublicSkillResourceMetadata):
    content: str = ""


# 日本語: 公開投稿 1 件の詳細。SKILL の場合は本文・資源も含む。
# English: Details of one public post, including the SKILL body and resources for SKILL posts.
class PublicSharedContentDetail(BaseModel):
    prompt_id: int
    title: str
    category: str = ""
    description: str = ""
    content: str = ""
    author: str
    content_format: str
    media_type: str
    attachments: list[dict[str, str]] = Field(default_factory=list)
    skill_markdown: str = ""
    resources: list[PublicSkillResourceMetadata] = Field(default_factory=list)
    # 旧クライアント向け。scripts/main.py の本文から派生し、新規保存には使用しない。
    skill_python_script: str = ""
    input_examples: str = ""
    output_examples: str = ""
    ai_model: str = ""
    created_at: datetime
    updated_at: datetime | None = None
    public_url: AnyHttpUrl


# 日本語: MCP などの transport から再利用できる、公開投稿の読み取りと操作のサービス。
# English: Service for reading and operating on public posts, reusable from transports such as MCP.
class SharedContentService:
    """MCP等のtransportから再利用できる公開投稿の読み取りサービス。"""

    def __init__(
        self,
        *,
        public_base_url: str | None = None,
        repository: SharedContentRepository | None = None,
        resource_repository: PromptResourceRepository | None = None,
    ) -> None:
        self._public_base_url = public_base_url
        self._repository = repository or SharedContentRepository()
        self._resource_repository = resource_repository or PromptResourceRepository()
        self._view_repository = PromptViewRepository()
        self._impression_repository = PromptImpressionRepository()

    # 日本語: 渡されたセッションがあればそれで、無ければ自前で開いたセッションで読み取りを実行する。
    # English: Run a read on the given session, or on one opened here when none is given.
    @staticmethod
    async def _read(
        session: AsyncSession | None,
        operation: Callable[[AsyncSession], Awaitable[T]],
    ) -> T:
        if session is not None:
            return await operation(session)
        async with session_scope() as owned_session:
            return await operation(owned_session)

    # 日本語: 書き込みを実行する。セッションが渡されなければ自前でトランザクションを開き、成功時に確定する。
    # 渡された場合は呼び出し側が確定する。
    # English: Run a write. Without a given session it opens its own transaction and commits on success; with one, the caller commits.
    @staticmethod
    async def _write(
        session: AsyncSession | None,
        operation: Callable[[AsyncSession], Awaitable[T]],
    ) -> T:
        if session is not None:
            return await operation(session)
        async with session_scope() as owned_session, owned_session.begin():
            return await operation(owned_session)

    # 日本語: 公開投稿を新しい順に 1 ページ返す。検索条件を指紋にしてカーソルへ埋め込み、条件が違うカーソルは拒否する。
    # English: Return one page of public posts, newest first. A fingerprint of the filters is embedded in the cursor so a cursor from other
    # filters is rejected.
    async def list_public_content(
        self,
        *,
        query: str | None = None,
        limit: int = SHARED_CONTENT_DEFAULT_LIMIT,
        cursor: str | None = None,
        category: str | None = None,
        content_format: str | None = None,
        media_type: str | None = None,
        session: AsyncSession | None = None,
    ) -> PublicSharedContentPage:
        if session is None:
            async with session_scope() as owned_session:
                return await self.list_public_content(
                    query=query,
                    limit=limit,
                    cursor=cursor,
                    category=category,
                    content_format=content_format,
                    media_type=media_type,
                    session=owned_session,
                )
        normalized_query = self._normalize_query(query)
        normalized_category = self._normalize_category_filter(category)
        normalized_content_format = self._normalize_axis_filter(
            content_format,
            allowed=CONTENT_FORMATS,
            field_name="content_format",
        )
        normalized_media_type = self._normalize_axis_filter(
            media_type,
            allowed=MEDIA_TYPES,
            field_name="media_type",
        )
        normalized_limit = self._normalize_limit(limit)
        fingerprint = self._filter_fingerprint(
            query=normalized_query,
            category=normalized_category,
            content_format=normalized_content_format,
            media_type=normalized_media_type,
        )
        decoded_cursor = self._decode_cursor(cursor, expected_fingerprint=fingerprint)

        rows, has_next = await self._repository.list_public_content(
            session,
            limit=normalized_limit,
            cursor=decoded_cursor,
            query=normalized_query or None,
            category=normalized_category,
            content_format=normalized_content_format,
            media_type=normalized_media_type,
            matching_category_keys=(
                category_keys_matching(normalized_query) if normalized_query else []
            ),
        )
        items = [self._summary_from_row(row) for row in rows]
        next_cursor = None
        if has_next and items:
            last = items[-1]
            next_cursor = self._encode_cursor(
                created_at=last.created_at,
                prompt_id=last.prompt_id,
                fingerprint=fingerprint,
            )
        return PublicSharedContentPage(
            items=items,
            limit=normalized_limit,
            has_next=has_next,
            next_cursor=next_cursor,
        )

    # 日本語: 公開投稿 1 件の詳細を返す。無ければ None。SKILL では旧クライアント向けに scripts/main.py の本文も
    # skill_python_script へ入れる。
    # English: Return the details of one public post, or None. For SKILLs, the scripts/main.py body is also exposed as skill_python_script
    # for old clients.
    async def get_public_content(
        self,
        prompt_id: int,
        *,
        session: AsyncSession | None = None,
    ) -> PublicSharedContentDetail | None:
        if session is None:
            async with session_scope() as owned_session:
                return await self.get_public_content(prompt_id, session=owned_session)
        if isinstance(prompt_id, bool) or int(prompt_id) <= 0:
            raise ValueError("prompt_id must be a positive integer.")
        row = await self._repository.get_public_content(session, int(prompt_id))
        if row is None:
            return None

        axes = serialize_axes(row)
        resources = await self._resource_metadata_for_prompt(session, int(row["id"]))
        skill_python_script = str(axes["skill_python_script"])
        if axes["content_format"] == "skill":
            legacy_resource = await self._resource_repository.get_for_prompt(
                session,
                int(row["id"]),
                "scripts/main.py",
            )
            if legacy_resource is not None:
                skill_python_script = self._resource_content(legacy_resource)
        return PublicSharedContentDetail(
            prompt_id=int(row["id"]),
            title=str(row.get("title") or ""),
            category=str(row.get("category") or ""),
            description=str(row.get("description") or ""),
            content=str(row.get("content") or ""),
            author=str(row.get("author") or "ユーザー"),
            content_format=str(axes["content_format"]),
            media_type=str(axes["media_type"]),
            attachments=list(axes["attachments"]),
            skill_markdown=str(axes["skill_markdown"]),
            resources=resources,
            skill_python_script=skill_python_script,
            input_examples=str(row.get("input_examples") or ""),
            output_examples=str(row.get("output_examples") or ""),
            ai_model=str(row.get("ai_model") or ""),
            created_at=row["created_at"],
            updated_at=row.get("updated_at"),
            public_url=self._public_url(int(row["id"])),
        )

    # 日本語: 公開 SKILL の資源ファイルの一覧（本文なし）を返す。SKILL でなければ ValueError。
    # English: Return the resource metadata of a public SKILL; raises ValueError if the post is not a SKILL.
    async def list_public_skill_resources(
        self,
        prompt_id: int,
        *,
        session: AsyncSession | None = None,
    ) -> list[PublicSkillResourceMetadata] | None:
        if session is None:
            async with session_scope() as owned_session:
                return await self.list_public_skill_resources(prompt_id, session=owned_session)
        row = await self._get_public_skill_row(session, prompt_id)
        if row is None:
            return None
        return await self._resource_metadata_for_prompt(session, int(row["id"]))

    # 日本語: 公開 SKILL の資源ファイル 1 件を本文つきで返す。無ければ None。
    # English: Return one resource file of a public SKILL with its content, or None if it does not exist.
    async def get_public_skill_resource(
        self,
        prompt_id: int,
        path: str,
        *,
        session: AsyncSession | None = None,
    ) -> PublicSkillResourceDetail | None:
        if session is None:
            async with session_scope() as owned_session:
                return await self.get_public_skill_resource(
                    prompt_id,
                    path,
                    session=owned_session,
                )
        row = await self._get_public_skill_row(session, prompt_id)
        if row is None:
            return None
        normalized_path = str(path or "").strip()
        if not normalized_path:
            raise ValueError("path must not be blank.")
        resource = await self._resource_repository.get_for_prompt(
            session,
            int(row["id"]),
            normalized_path,
        )
        if resource is None:
            return None
        metadata = self._resource_metadata(resource)
        return PublicSkillResourceDetail(
            **metadata.model_dump(),
            content=self._resource_content(resource),
        )

    # 日本語: ここから create_prompt の手前までは、リポジトリの読み取りを同じセッション規則（_read）で呼ぶだけの委譲。
    # English: From here up to create_prompt, methods simply delegate to repository reads under the same session rule (_read).
    async def get_public_feed(
        self,
        *,
        user_id: int | None,
        limit: int,
        cursor: tuple[int, datetime, int] | None = None,
        category: str | None = None,
        content_format: str | None = None,
        media_type: str | None = None,
        author_id: int | None = None,
        locale: str = "ja",
        session: AsyncSession | None = None,
    ) -> list[dict[str, Any]]:
        return await self._read(
            session,
            lambda active: self._repository.get_public_feed(
                active,
                user_id=user_id,
                limit=limit,
                cursor=cursor,
                category=category,
                content_format=content_format,
                media_type=media_type,
                author_id=author_id,
                locale=locale,
            ),
        )

    async def get_recommended_prompts(
        self,
        *,
        exclude_prompt_id: int | None,
        limit: int,
        locale: str = "ja",
        session: AsyncSession | None = None,
    ) -> list[dict[str, Any]]:
        return await self._read(
            session,
            lambda active: self._repository.get_recommended_prompts(
                active,
                exclude_prompt_id=exclude_prompt_id,
                limit=limit,
                locale=locale,
            ),
        )

    async def get_public_prompt_detail(
        self,
        prompt_id: int,
        *,
        session: AsyncSession | None = None,
    ) -> dict[str, Any] | None:
        return await self._read(
            session,
            lambda active: self._repository.get_public_prompt_detail(active, prompt_id),
        )

    async def get_public_author_profile(
        self,
        user_id: int,
        *,
        session: AsyncSession | None = None,
    ) -> dict[str, Any] | None:
        return await self._read(
            session,
            lambda active: self._repository.get_public_author_profile(active, user_id),
        )

    async def search_public_prompts(
        self,
        *,
        query: str,
        page: int,
        per_page: int,
        user_id: int | None,
        content_format: str | None,
        media_type: str | None,
        include_total: bool,
        locale: str,
        matching_category_keys: list[str],
        query_embedding: list[float] | None = None,
        session: AsyncSession | None = None,
    ) -> dict[str, Any]:
        if not query:
            return {
                "rows": [],
                "total": 0,
                "has_next": False,
            }
        return await self._read(
            session,
            lambda active: self._repository.search_public_prompts(
                active,
                query=query,
                page=page,
                per_page=per_page,
                user_id=user_id,
                content_format=content_format,
                media_type=media_type,
                include_total=include_total,
                locale=locale,
                matching_category_keys=matching_category_keys,
                query_embedding=query_embedding,
            ),
        )

    # 日本語: 閲覧数・表示回数の記録は書き込みなので _write を通す。
    # English: Recording views and impressions is a write, so it goes through _write.
    async def record_public_view(
        self,
        prompt_id: int,
        *,
        session: AsyncSession | None = None,
    ) -> int | None:
        return await self._write(
            session,
            lambda active: self._view_repository.increment_public_view(active, prompt_id),
        )

    async def record_public_impressions(
        self,
        prompt_ids: list[int],
        *,
        session: AsyncSession | None = None,
    ) -> int:
        return await self._write(
            session,
            lambda active: self._impression_repository.increment_public_impressions(active, prompt_ids),
        )

    # 日本語: 投稿と資源ファイルを同じトランザクションで作成し、投稿 ID を返す。
    # English: Create a post and its resource files in one transaction and return the post ID.
    async def create_prompt(
        self,
        *,
        user_id: int,
        title: str,
        category: str,
        content: str,
        description: str | None,
        content_format: str,
        media_type: str,
        input_examples: str | None,
        output_examples: str | None,
        ai_model: str | None,
        attributes: dict[str, Any],
        resources: list[object],
        attachments: list[dict[str, Any]],
        session: AsyncSession | None = None,
    ) -> int:
        async def operation(active: AsyncSession) -> int:
            prompt_id = await self._repository.create_prompt(
                active,
                user_id=user_id,
                title=title,
                category=category,
                content=content,
                description=description,
                content_format=content_format,
                media_type=media_type,
                input_examples=input_examples,
                output_examples=output_examples,
                ai_model=ai_model,
                attributes=attributes,
                attachments=attachments,
            )
            await self._resource_repository.insert_many(active, prompt_id, resources)
            return prompt_id

        return await self._write(session, operation)

    # 日本語: 自分の投稿を更新する。resources が None なら資源は変えない。更新できたときだけ埋め込みの再計算を予約する。
    # English: Update the user's own post. resources=None leaves resources unchanged; embedding recomputation is scheduled only when an
    # update happened.
    async def update_prompt(
        self,
        *,
        user_id: int,
        prompt_id: int,
        title: str,
        category: str,
        content: str,
        description: str | None,
        content_format: str,
        media_type: str,
        input_examples: str | None,
        output_examples: str | None,
        attributes: dict[str, Any],
        resources: list[object] | None,
        session: AsyncSession | None = None,
    ) -> bool:
        async def operation(active: AsyncSession) -> bool:
            updated = await self._repository.update_prompt_for_user(
                active,
                user_id=user_id,
                prompt_id=prompt_id,
                title=title,
                category=category,
                content=content,
                description=description,
                content_format=content_format,
                media_type=media_type,
                input_examples=input_examples,
                output_examples=output_examples,
                attributes=attributes,
            )
            if updated and resources is not None:
                await self._resource_repository.replace_for_prompt(active, prompt_id, resources)
            return updated

        updated = await self._write(session, operation)
        if updated:
            schedule_prompt_embedding(prompt_id)
        return updated

    # 日本語: 自分の投稿を削除し、(削除前の添付ファイル, 削除件数) を返す。添付は呼び出し側がストレージから消すために使う。
    # English: Delete the user's own post and return (attachments before deletion, deleted count); the caller uses the attachments to clean
    # up storage.
    async def delete_prompt(
        self,
        *,
        user_id: int,
        prompt_id: int,
        session: AsyncSession | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        async def operation(active: AsyncSession) -> tuple[list[dict[str, Any]], int]:
            attachments = await self._repository.get_active_prompt_attachments(
                active,
                user_id=user_id,
                prompt_id=prompt_id,
            )
            deleted = await self._repository.delete_prompt_for_user(
                active,
                user_id=user_id,
                prompt_id=prompt_id,
            )
            return attachments, deleted

        return await self._write(session, operation)

    async def get_active_prompt_attachments(
        self,
        *,
        user_id: int,
        prompt_id: int,
        session: AsyncSession | None = None,
    ) -> list[dict[str, Any]]:
        return await self._read(
            session,
            lambda active: self._repository.get_active_prompt_attachments(
                active,
                user_id=user_id,
                prompt_id=prompt_id,
            ),
        )

    async def list_my_prompts(
        self,
        *,
        user_id: int,
        session: AsyncSession | None = None,
    ) -> list[dict[str, Any]]:
        return await self._read(
            session,
            lambda active: self._repository.list_my_prompts(active, user_id=user_id),
        )

    async def list_liked_prompts(
        self,
        *,
        user_id: int,
        session: AsyncSession | None = None,
    ) -> list[dict[str, Any]]:
        return await self._read(
            session,
            lambda active: self._repository.list_liked_prompts(active, user_id=user_id),
        )

    # 日本語: 公開プロンプトを自分のタスクとして取り込む。(結果, HTTP ステータス) を返し、投稿が無い・本文が空の場合は 404/400。
    # English: Import a public prompt as the user's own task. Returns (result, HTTP status): 404 if the post is missing, 400 if it has no
    # body.
    async def import_prompt_as_task(
        self,
        *,
        user_id: int,
        prompt_id: int,
        session: AsyncSession | None = None,
    ) -> tuple[dict[str, Any], int]:
        async def operation(active: AsyncSession) -> tuple[dict[str, Any], int]:
            prompt = await self._repository.get_prompt_for_import(
                active,
                prompt_id=prompt_id,
            )
            if prompt is None:
                return {"error": "対象の公開プロンプトが見つかりませんでした。"}, 404
            prompt_template = self._compose_task_prompt_template(prompt)
            if not prompt_template:
                return {"error": "タスクとして追加できる本文がありません。"}, 400
            return await self._repository.add_prompt_as_task(
                active,
                user_id=user_id,
                prompt_id=prompt_id,
                prompt_template=prompt_template,
            )

        return await self._write(session, operation)

    async def import_prompt_as_skill(
        self,
        *,
        user_id: int,
        prompt_id: int,
        session: AsyncSession | None = None,
    ) -> tuple[dict[str, Any], int]:
        """公開された SKILL 投稿を、利用者の再利用できる Skill に取り込む。

        Import a public SKILL post into the user's reusable Skills.
        """

        async def operation(active: AsyncSession) -> tuple[dict[str, Any], int]:
            prompt = await self._repository.get_prompt_for_import(
                active,
                prompt_id=prompt_id,
            )
            if prompt is None:
                return {"error": ERROR_SHARED_SKILL_NOT_FOUND}, 404
            if str(prompt.get("content_format") or "").strip().lower() != CONTENT_FORMAT_SKILL:
                return {"error": ERROR_SHARED_SKILL_INVALID_TYPE}, 400

            # 日本語: 公開された定義とテキスト資源を 1 つの Skill にまとめる。normalize_user_skill_instructions が、手で作った Skill と同じ
            # 12,000 文字の上限を適用する。
            # English: Keep the published definition and its text resources together in
            # the user Skill.  ``normalize_user_skill_instructions`` enforces
            # the same 12,000-character contract as manually-created Skills.
            instructions = normalize_user_skill_instructions(self._compose_task_prompt_template(prompt))
            if not instructions:
                return {"error": ERROR_SHARED_SKILL_CONTENT_MISSING}, 400

            try:
                skill, created = await UserSkillRepository(active).import_user_skill(
                    user_id=int(user_id),
                    source_prompt_id=int(prompt_id),
                    name=str(prompt.get("title") or "共有Skill"),
                    instructions=instructions,
                )
            except ApiServiceError as exc:
                return exc.to_payload(), exc.status_code

            return {
                "message": MESSAGE_SHARED_SKILL_ADDED if created else MESSAGE_SHARED_SKILL_ALREADY_ADDED,
                "skill_id": int(skill["id"]),
                "added_to_skills": True,
            }, 201 if created else 200

        return await self._write(session, operation)

    # 日本語: ここから report_comment までは、いいね・コメント・通報の操作をリポジトリへ渡す委譲。判定や重複抑止はリポジトリ側にある。
    # English: From here to report_comment, methods hand like/comment/report operations to the repository, which owns the checks and
    # duplicate suppression.
    async def remove_prompt_as_task(
        self,
        *,
        user_id: int,
        prompt_id: int,
        session: AsyncSession | None = None,
    ) -> tuple[dict[str, Any], int]:
        return await self._write(
            session,
            lambda active: self._repository.remove_prompt_as_task(
                active,
                user_id=user_id,
                prompt_id=prompt_id,
            ),
        )

    async def add_like(
        self,
        *,
        user_id: int,
        prompt_id: int,
        session: AsyncSession | None = None,
    ) -> tuple[dict[str, Any], int]:
        return await self._write(
            session,
            lambda active: self._repository.add_like(
                active,
                user_id=user_id,
                prompt_id=prompt_id,
            ),
        )

    async def remove_like(
        self,
        *,
        user_id: int,
        prompt_id: int,
        session: AsyncSession | None = None,
    ) -> int:
        return await self._write(
            session,
            lambda active: self._repository.remove_like(
                active,
                user_id=user_id,
                prompt_id=prompt_id,
            ),
        )

    async def list_comments(
        self,
        *,
        prompt_id: int,
        limit: int,
        session: AsyncSession | None = None,
    ) -> tuple[list[dict[str, Any]] | None, int]:
        async def operation(active: AsyncSession) -> tuple[list[dict[str, Any]] | None, int]:
            comments = await self._repository.list_prompt_comments(
                active,
                prompt_id=prompt_id,
                limit=limit,
            )
            if comments is None:
                return None, 0
            return comments, await self._repository.count_visible_comments(active, prompt_id)

        return await self._read(session, operation)

    async def add_comment(
        self,
        *,
        user_id: int,
        prompt_id: int,
        content: str,
        actor_is_admin: bool,
        duplicate_window_seconds: int,
        session: AsyncSession | None = None,
    ) -> tuple[dict[str, Any], int]:
        return await self._write(
            session,
            lambda active: self._repository.add_comment(
                active,
                user_id=user_id,
                prompt_id=prompt_id,
                content=content,
                actor_is_admin=actor_is_admin,
                duplicate_window_seconds=duplicate_window_seconds,
            ),
        )

    async def delete_comment(
        self,
        *,
        actor_user_id: int,
        comment_id: int,
        actor_is_admin: bool,
        session: AsyncSession | None = None,
    ) -> tuple[dict[str, Any], int]:
        return await self._write(
            session,
            lambda active: self._repository.delete_comment(
                active,
                actor_user_id=actor_user_id,
                comment_id=comment_id,
                actor_is_admin=actor_is_admin,
            ),
        )

    async def report_comment(
        self,
        *,
        reporter_user_id: int,
        comment_id: int,
        reason: str,
        details: str | None,
        auto_hide_threshold: int,
        session: AsyncSession | None = None,
    ) -> tuple[dict[str, Any], int]:
        return await self._write(
            session,
            lambda active: self._repository.report_comment(
                active,
                reporter_user_id=reporter_user_id,
                comment_id=comment_id,
                reason=reason,
                details=details,
                auto_hide_threshold=auto_hide_threshold,
            ),
        )

    # 日本語: 資源ファイルを Markdown のコードフェンスに変換する。本文に含まれるバッククォートより長いフェンスにして、
    # 本文でフェンスが閉じないようにする。
    # English: Render a resource file as a Markdown code fence, using a fence longer than any backtick run in the content so it cannot close
    # early.
    @staticmethod
    def _resource_code_fence(resource: Mapping[str, Any]) -> str:
        path = str(resource.get("path") or "").strip()
        content = str(resource.get("content") or "")
        if not path or not content:
            return ""
        language = re.sub(r"[^a-zA-Z0-9_+.-]", "", str(resource.get("language") or "text"))
        longest_run = max(
            (len(match.group(0)) for match in re.finditer(r"`+", content)),
            default=0,
        )
        fence = "`" * max(3, longest_run + 1)
        return f"## Resource: `{path}`\n\n{fence}{language}\n{content}\n{fence}"

    # 日本語: タスク／Skill として取り込むための本文を組み立てる。通常の投稿は本文そのまま、SKILL は SKILL.md に
    # 資源のコードフェンスを続ける。資源が無い旧形式では skill_python_script を scripts/main.py として補う。
    # English: Build the body to import as a task or Skill. A normal post is used as is; a SKILL is its markdown
    # followed by resource code fences, and for the legacy form without resources skill_python_script is added as scripts/main.py.
    @classmethod
    def _compose_task_prompt_template(cls, prompt: Mapping[str, Any]) -> str:
        if str(prompt.get("content_format") or "").strip().lower() != CONTENT_FORMAT_SKILL:
            return str(prompt.get("content") or "")
        parts: list[str] = []
        attributes = prompt.get("attributes") if isinstance(prompt.get("attributes"), dict) else {}
        skill_markdown = str(attributes.get("skill_markdown") or "")
        if skill_markdown:
            parts.append(skill_markdown)
        resources = prompt.get("resources") if isinstance(prompt.get("resources"), list) else []
        for resource in resources:
            if isinstance(resource, dict):
                rendered = cls._resource_code_fence(resource)
                if rendered:
                    parts.append(rendered)
        if not resources:
            legacy_script = str(attributes.get("skill_python_script") or "")
            if legacy_script:
                parts.append(
                    cls._resource_code_fence(
                        {
                            "path": "scripts/main.py",
                            "language": "python",
                            "content": legacy_script,
                        }
                    )
                )
        return "\n\n".join(parts) or str(prompt.get("content") or "")

    # 日本語: 公開 SKILL の行を取得する。投稿が無ければ None、SKILL 以外なら ValueError。
    # English: Fetch the row of a public SKILL: None if the post does not exist, ValueError if it is not a SKILL.
    async def _get_public_skill_row(
        self,
        session: AsyncSession,
        prompt_id: int,
    ) -> dict[str, Any] | None:
        if isinstance(prompt_id, bool) or int(prompt_id) <= 0:
            raise ValueError("prompt_id must be a positive integer.")
        row = await self._repository.get_public_content(session, int(prompt_id))
        if row is None:
            return None
        axes = serialize_axes(row)
        if axes["content_format"] != "skill":
            raise ValueError("指定された投稿はSKILLではありません。")
        return row

    async def _resource_metadata_for_prompt(
        self,
        session: AsyncSession,
        prompt_id: int,
    ) -> list[PublicSkillResourceMetadata]:
        return [
            self._resource_metadata(resource)
            for resource in await self._resource_repository.list_for_prompt(session, prompt_id)
        ]

    # 日本語: 資源ファイルのデータからメタデータを作る。サイズが無ければ本文の UTF-8 バイト数で補う。
    # English: Build metadata from resource data, falling back to the UTF-8 byte length of the content when no size is stored.
    @classmethod
    def _resource_metadata(cls, resource: object) -> PublicSkillResourceMetadata:
        data = cls._resource_mapping(resource)
        content = str(data.get("text_content") or data.get("content") or "")
        return PublicSkillResourceMetadata(
            path=str(data.get("path") or ""),
            role=str(data.get("role") or "other"),
            language=str(data.get("language") or ""),
            media_type=str(data.get("media_type") or "text/plain"),
            size_bytes=int(data.get("size_bytes") or len(content.encode("utf-8"))),
            sha256=str(data.get("sha256") or ""),
        )

    @classmethod
    def _resource_content(cls, resource: object) -> str:
        data = cls._resource_mapping(resource)
        return str(data.get("text_content") or data.get("content") or "")

    # 日本語: 資源を辞書として読めるようにする。Mapping はそのまま、Pydantic モデルは model_dump() で辞書にする。
    # English: Make a resource readable as a mapping: a Mapping as is, a Pydantic model via model_dump().
    @staticmethod
    def _resource_mapping(resource: object) -> Mapping[str, Any]:
        if isinstance(resource, Mapping):
            return resource
        model_dump = getattr(resource, "model_dump", None)
        if callable(model_dump):
            return model_dump()
        raise TypeError("resource must be a mapping or Pydantic model.")

    # 日本語: 以下の _normalize_* は入力を検証して正規化する。不正な値は ValueError にして、transport 側で入力エラーとして扱えるようにする。
    # English: The _normalize_* helpers below validate and normalize input; invalid values raise ValueError so transports can report an
    # input error.
    @staticmethod
    def _normalize_limit(value: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("limit must be an integer.") from exc
        if parsed <= 0:
            raise ValueError("limit must be a positive integer.")
        return min(parsed, SHARED_CONTENT_MAX_LIMIT)

    @staticmethod
    def _normalize_query(value: str | None) -> str:
        if value is None:
            return ""
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("query must not be blank.")
        if len(normalized) > SHARED_CONTENT_MAX_QUERY_LENGTH:
            raise ValueError(
                f"query must be {SHARED_CONTENT_MAX_QUERY_LENGTH} characters or fewer."
            )
        return normalized

    @staticmethod
    def _normalize_category_filter(value: str | None) -> str | None:
        raw = str(value or "").strip()
        if not raw or raw.lower() == "all":
            return None
        normalized = normalize_category(raw)
        if normalized is None:
            raise ValueError("category is invalid.")
        return normalized

    @staticmethod
    def _normalize_axis_filter(
        value: str | None,
        *,
        allowed: dict[str, Any],
        field_name: str,
    ) -> str | None:
        normalized = str(value or "").strip().lower()
        if not normalized or normalized == "all":
            return None
        if normalized not in allowed:
            raise ValueError(f"{field_name} is invalid.")
        return normalized

    # 日本語: 検索条件の指紋（SHA-256 の先頭 16 文字）。カーソルが別の条件で発行されたものでないことを確かめるために使う。
    # English: Fingerprint of the filters (first 16 hex chars of SHA-256), used to check that a cursor was issued for the same filters.
    @staticmethod
    def _filter_fingerprint(
        *,
        query: str,
        category: str | None,
        content_format: str | None,
        media_type: str | None,
    ) -> str:
        serialized = json.dumps(
            {
                "query": query.casefold(),
                "category": category,
                "content_format": content_format,
                "media_type": media_type,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]

    # 日本語: 作成日時・ID・条件の指紋を base64 にしたカーソルを作る。次ページはこの位置より後から読む。
    # English: Build a cursor from the creation time, ID and filter fingerprint (base64); the next page continues after that position.
    @staticmethod
    def _encode_cursor(
        *,
        created_at: datetime,
        prompt_id: int,
        fingerprint: str,
    ) -> str:
        payload = json.dumps(
            {
                "created_at": created_at.isoformat(),
                "id": prompt_id,
                "filter": fingerprint,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")

    # 日本語: カーソルを (作成日時, ID) に戻す。壊れている、または条件の指紋が違う場合は InvalidSharedContentCursorError。
    # English: Decode a cursor into (created_at, id); a corrupt cursor or a mismatched filter fingerprint raises
    # InvalidSharedContentCursorError.
    @staticmethod
    def _decode_cursor(
        value: str | None,
        *,
        expected_fingerprint: str,
    ) -> tuple[datetime, int] | None:
        if not value:
            return None
        try:
            padded = value + "=" * (-len(value) % 4)
            decoded = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
            payload = json.loads(decoded)
            if not isinstance(payload, dict) or payload.get("filter") != expected_fingerprint:
                raise ValueError
            created_at = payload.get("created_at")
            prompt_id = payload.get("id")
            if not isinstance(created_at, str) or isinstance(prompt_id, bool):
                raise TypeError
            parsed_id = int(prompt_id)
            if parsed_id <= 0:
                raise ValueError
            return datetime.fromisoformat(created_at.replace("Z", "+00:00")), parsed_id
        except (
            ValueError,
            TypeError,
            json.JSONDecodeError,
            UnicodeDecodeError,
            binascii.Error,
        ) as exc:
            raise InvalidSharedContentCursorError("The shared-content cursor is invalid.") from exc

    def _summary_from_row(self, row: dict[str, Any]) -> PublicSharedContentSummary:
        axes = serialize_axes(row)
        return PublicSharedContentSummary(
            prompt_id=int(row["id"]),
            title=str(row.get("title") or ""),
            category=str(row.get("category") or ""),
            description=str(row.get("description") or ""),
            author=str(row.get("author") or "ユーザー"),
            content_format=str(axes["content_format"]),
            media_type=str(axes["media_type"]),
            snippet=self._make_snippet(str(row.get("snippet_source") or "")),
            created_at=row["created_at"],
            public_url=self._public_url(int(row["id"])),
        )

    # 日本語: 空白をまとめ、上限を超える場合は切り詰めて「…」を付けたスニペットにする。
    # English: Collapse whitespace and truncate with an ellipsis when over the snippet limit.
    @staticmethod
    def _make_snippet(value: str) -> str:
        normalized = " ".join(value.split())
        if len(normalized) <= SHARED_CONTENT_SNIPPET_LENGTH:
            return normalized
        return normalized[: SHARED_CONTENT_SNIPPET_LENGTH - 1].rstrip() + "…"

    def _public_url(self, prompt_id: int) -> str:
        # 日本語: 明示指定が無ければ共通の解決結果を使い、経路ごとのホスト差を防ぐ
        # English: Fall back to the shared resolution so every transport agrees on the host.
        if not self._public_base_url:
            return build_public_share_url(ShareContentKind.PROMPT, prompt_id)
        return build_share_url(
            self._public_base_url,
            ShareContentKind.PROMPT,
            prompt_id,
        )
