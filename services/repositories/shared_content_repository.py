"""Persistence boundary for the prompt-share domain.

The prompt-share domain has a few deliberately PostgreSQL-specific reads (the
feed CTE, JSONB resource aggregation, and advisory-lock based guest/task
operations).  They live here as SQLAlchemy Core statements.  Simple row
changes use the mapped models, and no method in this repository commits or
rolls back the caller's :class:`AsyncSession`.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any

from sqlalchemy import (
    ARRAY,
    String,
    bindparam,
    delete,
    func,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from services.models import (
    GuestPromptSubmission,
    Prompt,
    PromptComment,
    PromptCommentReport,
    PromptLike,
    Task,
    User,
)
from services.prompt_types import normalize_content_format, normalize_media_type
from services.search_terms import build_like_pattern, split_search_terms


SNIPPET_SOURCE_MAX_LENGTH = 1000


def _rowcount(result: Any) -> int:
    """Read the affected-row count exposed by PostgreSQL DML results."""
    return int(getattr(result, "rowcount", 0) or 0)


def _rows(result: Any) -> list[dict[str, Any]]:
    return [dict(row) for row in result.mappings().all()]


def _first(result: Any) -> dict[str, Any] | None:
    row = result.mappings().first()
    return dict(row) if row is not None else None


class SharedContentRepository:
    """ORM/Core repository for public prompts and their interactions."""

    async def list_public_content(
        self,
        session: AsyncSession,
        *,
        limit: int,
        cursor: tuple[datetime, int] | None = None,
        query: str | None = None,
        category: str | None = None,
        content_format: str | None = None,
        media_type: str | None = None,
        matching_category_keys: list[str] | None = None,
    ) -> tuple[list[dict[str, Any]], bool]:
        """List public content using stable keyset pagination."""
        conditions = ["p.is_public = TRUE", "p.deleted_at IS NULL"]
        params: dict[str, Any] = {
            "snippet_limit": SNIPPET_SOURCE_MAX_LENGTH,
            "limit": int(limit) + 1,
        }
        if category is not None:
            conditions.append("p.category = :category")
            params["category"] = category
        if content_format is not None:
            conditions.append("p.content_format = :content_format")
            params["content_format"] = content_format
        if media_type is not None:
            conditions.append("p.media_type = :media_type")
            params["media_type"] = media_type
        for index, term in enumerate(split_search_terms(query or "")):
            term_key = f"search_term_{index}"
            category_key = f"category_keys_{index}"
            conditions.append(
                f"""(
                    p.title ILIKE :{term_key} ESCAPE '\\'
                    OR p.content ILIKE :{term_key} ESCAPE '\\'
                    OR p.description ILIKE :{term_key} ESCAPE '\\'
                    OR p.category ILIKE :{term_key} ESCAPE '\\'
                    OR p.category = ANY(:{category_key})
                    OR p.author ILIKE :{term_key} ESCAPE '\\'
                    OR u.username ILIKE :{term_key} ESCAPE '\\'
                    OR (
                        p.content_format = 'skill'
                        AND COALESCE(p.attributes->>'skill_markdown', '')
                            ILIKE :{term_key} ESCAPE '\\'
                    )
                )"""
            )
            params[term_key] = build_like_pattern(term)
            params[category_key] = matching_category_keys or []
        if cursor is not None:
            conditions.append("(p.created_at, p.id) < (:cursor_created_at, :cursor_id)")
            params["cursor_created_at"], params["cursor_id"] = cursor

        statement = text(
            f"""
            SELECT
                p.id,
                p.title,
                p.category,
                COALESCE(u.username, p.author, 'ユーザー') AS author,
                p.description,
                p.content_format,
                p.media_type,
                LEFT(
                    CASE
                        WHEN NULLIF(p.description, '') IS NOT NULL THEN p.description
                        WHEN p.content_format = 'skill'
                            THEN COALESCE(p.attributes->>'skill_markdown', '')
                        ELSE p.content
                    END,
                    :snippet_limit
                ) AS snippet_source,
                p.created_at
            FROM prompts AS p
            LEFT JOIN users AS u ON u.id = p.user_id
            WHERE {' AND '.join(conditions)}
            ORDER BY p.created_at DESC, p.id DESC
            LIMIT :limit
            """
        )
        for index in range(len(split_search_terms(query or ""))):
            statement = statement.bindparams(
                bindparam(f"category_keys_{index}", type_=ARRAY(String))
            )
        result = await session.execute(statement, params)
        rows = _rows(result)
        return rows[: int(limit)], len(rows) > int(limit)

    async def get_public_content(
        self,
        session: AsyncSession,
        prompt_id: int,
    ) -> dict[str, Any] | None:
        """Read a visible public prompt and its JSONB fields."""
        result = await session.execute(
            text(
                """
                SELECT
                    p.id,
                    p.title,
                    p.category,
                    p.content,
                    p.description,
                    COALESCE(u.username, p.author, 'ユーザー') AS author,
                    p.user_id AS author_user_id,
                    COALESCE(u.avatar_url, '/static/user-icon.png') AS author_avatar_url,
                    p.content_format,
                    p.media_type,
                    p.attributes,
                    p.attachments,
                    p.input_examples,
                    p.output_examples,
                    p.ai_model,
                    p.created_at,
                    p.updated_at
                FROM prompts AS p
                LEFT JOIN users AS u ON u.id = p.user_id
                WHERE p.id = :prompt_id
                  AND p.is_public = TRUE
                  AND p.deleted_at IS NULL
                LIMIT 1
                """
            ),
            {"prompt_id": int(prompt_id)},
        )
        return _first(result)

    async def search_public_prompts(
        self,
        session: AsyncSession,
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
    ) -> dict[str, Any]:
        """Search public prompts with page-first JSONB/interaction aggregation."""
        offset = (int(page) - 1) * int(per_page)
        axis_conditions = ["(p.system_prompt_key IS NULL OR p.content_locale = :locale)"]
        params: dict[str, Any] = {
            "locale": locale,
            "search_term": f"%{query}%",
            "category_keys": matching_category_keys,
            "fetch_limit": int(per_page) + 1,
            "offset": offset,
            "actor_user_id": user_id,
        }
        if content_format is not None:
            axis_conditions.append("p.content_format = :search_content_format")
            params["search_content_format"] = content_format
        if media_type is not None:
            axis_conditions.append("p.media_type = :search_media_type")
            params["search_media_type"] = media_type
        matched_condition = """(
            p.title ILIKE :search_term OR
            p.content ILIKE :search_term OR
            p.description ILIKE :search_term OR
            p.category = ANY(:category_keys) OR
            p.author ILIKE :search_term OR
            u.username ILIKE :search_term
        )"""
        count = None
        if include_total:
            count_result = await session.execute(
                text(
                    f"""
                    SELECT COUNT(*)
                    FROM prompts AS p
                    LEFT JOIN users AS u ON u.id = p.user_id
                    WHERE p.is_public = TRUE AND p.deleted_at IS NULL
                      AND {' AND '.join(axis_conditions)}
                      AND {matched_condition}
                    """
                ).bindparams(bindparam("category_keys", type_=ARRAY(String))),
                params,
            )
            count = int(count_result.scalar_one() or 0)
        result = await session.execute(
            text(
                f"""
                WITH matched_prompts AS (
                  SELECT
                    p.id, p.title, p.category, p.content, p.description,
                    COALESCE(u.username, p.author, 'ユーザー') AS author,
                    p.input_examples, p.output_examples, p.content_format,
                    p.media_type, p.attributes, p.attachments,
                    COALESCE(pvc.view_count, 0) AS view_count,
                    COALESCE(
                      (
                        SELECT jsonb_agg(
                          jsonb_build_object(
                            'id', pr.id, 'path', pr.path, 'role', pr.role,
                            'language', COALESCE(pr.language, ''),
                            'media_type', pr.media_type, 'size_bytes', pr.size_bytes,
                            'sha256', pr.sha256, 'sort_order', pr.sort_order
                          ) ORDER BY pr.sort_order, pr.id
                        ) FROM prompt_resources AS pr WHERE pr.prompt_id = p.id
                      ), '[]'::jsonb
                    ) AS resources,
                    COALESCE(
                      (
                        SELECT pr.text_content FROM prompt_resources AS pr
                        WHERE pr.prompt_id = p.id AND lower(pr.path) = 'scripts/main.py'
                        LIMIT 1
                      ), ''
                    ) AS resource_python_script,
                    p.created_at
                  FROM prompts AS p
                  LEFT JOIN users AS u ON u.id = p.user_id
                  LEFT JOIN prompt_view_counts AS pvc ON pvc.prompt_id = p.id
                  WHERE p.is_public = TRUE AND p.deleted_at IS NULL
                    AND {' AND '.join(axis_conditions)}
                    AND {matched_condition}
                  ORDER BY COALESCE(pvc.view_count, 0) DESC, p.created_at DESC, p.id DESC
                  LIMIT :fetch_limit OFFSET :offset
                )
                SELECT p.*,
                       COALESCE(pc.comment_count, 0) AS comment_count,
                       EXISTS (
                         SELECT 1 FROM prompt_likes AS pl
                         WHERE pl.user_id = :actor_user_id AND pl.prompt_id = p.id
                       ) AS liked,
                       EXISTS (
                         SELECT 1 FROM task_with_examples AS used_tasks
                         WHERE used_tasks.user_id = :actor_user_id
                           AND used_tasks.deleted_at IS NULL
                           AND used_tasks.source_prompt_id = p.id
                       ) AS used_in_chat
                FROM matched_prompts AS p
                LEFT JOIN LATERAL (
                  SELECT COUNT(*) AS comment_count
                  FROM prompt_comments
                  WHERE deleted_at IS NULL AND hidden_by_reports_at IS NULL
                    AND prompt_id = p.id
                ) AS pc ON TRUE
                ORDER BY p.view_count DESC, p.created_at DESC, p.id DESC
                """
            ).bindparams(bindparam("category_keys", type_=ARRAY(String))),
            params,
        )
        rows = _rows(result)
        has_next = page * per_page < count if count is not None else len(rows) > per_page
        return {
            "rows": rows[: int(per_page)],
            "total": count,
            "has_next": has_next,
        }

    async def get_public_feed(
        self,
        session: AsyncSession,
        *,
        user_id: int | None,
        limit: int,
        cursor: tuple[int, datetime, int] | None = None,
        category: str | None = None,
        content_format: str | None = None,
        media_type: str | None = None,
        author_id: int | None = None,
        locale: str = "ja",
    ) -> list[dict[str, Any]]:
        """Fetch a feed page with flags and JSONB resource metadata in one query."""
        conditions = ["(p.system_prompt_key IS NULL OR p.content_locale = :locale)"]
        params: dict[str, Any] = {
            "locale": locale,
            "actor_user_id": user_id,
            "fetch_limit": min(max(int(limit), 1), 100) + 1,
        }
        if category is not None:
            conditions.append("p.category = :feed_category")
            params["feed_category"] = category
        if content_format is not None:
            conditions.append("p.content_format = :feed_content_format")
            params["feed_content_format"] = content_format
        if media_type is not None:
            conditions.append("p.media_type = :feed_media_type")
            params["feed_media_type"] = media_type
        if author_id is not None:
            conditions.append("p.user_id = :feed_author_id")
            params["feed_author_id"] = author_id
        if cursor is not None:
            conditions.append(
                "(COALESCE(pvc.view_count, 0), p.created_at, p.id) "
                "< (:feed_view_count, :feed_created_at, :feed_id)"
            )
            params["feed_view_count"], params["feed_created_at"], params["feed_id"] = cursor

        result = await session.execute(
            text(
                f"""
                WITH page_prompts AS (
                  SELECT
                    p.id,
                    p.title,
                    p.category,
                    p.content,
                    p.description,
                    COALESCE(u.username, p.author, 'ユーザー') AS author,
                    p.user_id AS author_user_id,
                    COALESCE(u.avatar_url, '/static/user-icon.png') AS author_avatar_url,
                    p.input_examples,
                    p.output_examples,
                    p.ai_model,
                    p.content_format,
                    p.media_type,
                    p.attributes,
                    p.attachments,
                    COALESCE(pvc.view_count, 0) AS view_count,
                    COALESCE(
                      (
                        SELECT jsonb_agg(
                          jsonb_build_object(
                            'id', pr.id,
                            'path', pr.path,
                            'role', pr.role,
                            'language', COALESCE(pr.language, ''),
                            'media_type', pr.media_type,
                            'size_bytes', pr.size_bytes,
                            'sha256', pr.sha256,
                            'sort_order', pr.sort_order
                          ) ORDER BY pr.sort_order, pr.id
                        )
                        FROM prompt_resources AS pr
                        WHERE pr.prompt_id = p.id
                      ),
                      '[]'::jsonb
                    ) AS resources,
                    COALESCE(
                      (
                        SELECT pr.text_content
                        FROM prompt_resources AS pr
                        WHERE pr.prompt_id = p.id
                          AND lower(pr.path) = 'scripts/main.py'
                        LIMIT 1
                      ),
                      ''
                    ) AS resource_python_script,
                    p.created_at
                  FROM prompts AS p
                  LEFT JOIN users AS u ON u.id = p.user_id
                  LEFT JOIN prompt_view_counts AS pvc ON pvc.prompt_id = p.id
                  WHERE p.is_public = TRUE
                    AND p.deleted_at IS NULL
                    AND {' AND '.join(conditions)}
                  ORDER BY COALESCE(pvc.view_count, 0) DESC, p.created_at DESC, p.id DESC
                  LIMIT :fetch_limit
                )
                SELECT
                    p.*,
                    COALESCE(pc.comment_count, 0) AS comment_count,
                    EXISTS (
                      SELECT 1 FROM prompt_likes AS pl
                      WHERE pl.user_id = :actor_user_id AND pl.prompt_id = p.id
                    ) AS liked,
                    EXISTS (
                      SELECT 1 FROM task_with_examples AS used_tasks
                      WHERE used_tasks.user_id = :actor_user_id
                        AND used_tasks.deleted_at IS NULL
                        AND used_tasks.source_prompt_id = p.id
                    ) AS used_in_chat
                FROM page_prompts AS p
                LEFT JOIN LATERAL (
                    SELECT COUNT(*) AS comment_count
                    FROM prompt_comments
                    WHERE deleted_at IS NULL
                      AND hidden_by_reports_at IS NULL
                      AND prompt_id = p.id
                ) AS pc ON TRUE
                ORDER BY p.view_count DESC, p.created_at DESC, p.id DESC
                """
            ),
            params,
        )
        return _rows(result)

    async def get_recommended_prompts(
        self,
        session: AsyncSession,
        *,
        exclude_prompt_id: int | None,
        limit: int,
        locale: str = "ja",
    ) -> list[dict[str, Any]]:
        """Return a bounded random sample of visible public prompts."""
        result = await session.execute(
            text(
                """
                SELECT
                    p.id,
                    p.title,
                    p.category,
                    p.content,
                    p.description,
                    COALESCE(u.username, p.author, 'ユーザー') AS author,
                    p.user_id AS author_user_id,
                    COALESCE(u.avatar_url, '/static/user-icon.png') AS author_avatar_url,
                    p.content_format,
                    p.media_type,
                    p.attributes,
                    p.attachments,
                    COALESCE(pvc.view_count, 0) AS view_count,
                    COALESCE(
                      (
                        SELECT jsonb_agg(
                          jsonb_build_object(
                            'id', pr.id,
                            'path', pr.path,
                            'role', pr.role,
                            'language', COALESCE(pr.language, ''),
                            'media_type', pr.media_type,
                            'size_bytes', pr.size_bytes,
                            'sha256', pr.sha256,
                            'sort_order', pr.sort_order
                          ) ORDER BY pr.sort_order, pr.id
                        )
                        FROM prompt_resources AS pr
                        WHERE pr.prompt_id = p.id
                      ),
                      '[]'::jsonb
                    ) AS resources,
                    COALESCE(
                      (
                        SELECT pr.text_content
                        FROM prompt_resources AS pr
                        WHERE pr.prompt_id = p.id
                          AND lower(pr.path) = 'scripts/main.py'
                        LIMIT 1
                      ),
                      ''
                    ) AS resource_python_script,
                    p.created_at
                FROM prompts AS p
                LEFT JOIN users AS u ON u.id = p.user_id
                LEFT JOIN prompt_view_counts AS pvc ON pvc.prompt_id = p.id
                WHERE p.is_public = TRUE
                  AND p.deleted_at IS NULL
                  AND (p.system_prompt_key IS NULL OR p.content_locale = :locale)
                  AND COALESCE(p.id <> :exclude_prompt_id, TRUE)
                ORDER BY RANDOM()
                LIMIT :limit
                """
            ),
            {
                "locale": locale,
                "exclude_prompt_id": exclude_prompt_id,
                "limit": int(limit),
            },
        )
        return _rows(result)

    async def get_public_prompt_detail(
        self,
        session: AsyncSession,
        prompt_id: int,
    ) -> dict[str, Any] | None:
        """Read a public prompt detail with view/comment/resource aggregates."""
        result = await session.execute(
            text(
                """
                SELECT
                    p.id,
                    p.title,
                    p.category,
                    p.content,
                    p.description,
                    COALESCE(u.username, p.author, 'ユーザー') AS author,
                    p.user_id AS author_user_id,
                    COALESCE(u.avatar_url, '/static/user-icon.png') AS author_avatar_url,
                    p.input_examples,
                    p.output_examples,
                    p.ai_model,
                    p.content_format,
                    p.media_type,
                    p.attributes,
                    p.attachments,
                    COALESCE(pvc.view_count, 0) AS view_count,
                    COALESCE(
                      (
                        SELECT jsonb_agg(
                          jsonb_build_object(
                            'id', pr.id,
                            'path', pr.path,
                            'role', pr.role,
                            'language', COALESCE(pr.language, ''),
                            'media_type', pr.media_type,
                            'content', COALESCE(pr.text_content, ''),
                            'size_bytes', pr.size_bytes,
                            'sha256', pr.sha256,
                            'sort_order', pr.sort_order
                          ) ORDER BY pr.sort_order, pr.id
                        )
                        FROM prompt_resources AS pr
                        WHERE pr.prompt_id = p.id
                      ),
                      '[]'::jsonb
                    ) AS resources,
                    COALESCE(
                      (
                        SELECT pr.text_content
                        FROM prompt_resources AS pr
                        WHERE pr.prompt_id = p.id
                          AND lower(pr.path) = 'scripts/main.py'
                        LIMIT 1
                      ),
                      ''
                    ) AS resource_python_script,
                    (
                        SELECT COUNT(*)
                        FROM prompt_comments AS pc
                        WHERE pc.prompt_id = p.id
                          AND pc.deleted_at IS NULL
                          AND pc.hidden_by_reports_at IS NULL
                    ) AS comment_count,
                    p.created_at,
                    p.updated_at
                FROM prompts AS p
                LEFT JOIN users AS u ON u.id = p.user_id
                LEFT JOIN prompt_view_counts AS pvc ON pvc.prompt_id = p.id
                WHERE p.id = :prompt_id
                  AND p.is_public = TRUE
                  AND p.deleted_at IS NULL
                LIMIT 1
                """
            ),
            {"prompt_id": int(prompt_id)},
        )
        return _first(result)

    async def get_public_author_profile(
        self,
        session: AsyncSession,
        user_id: int,
    ) -> dict[str, Any] | None:
        """Return a profile only when the user has a visible public post."""
        result = await session.execute(
            text(
                """
                SELECT
                    u.id,
                    COALESCE(u.username, 'ユーザー') AS username,
                    COALESCE(u.avatar_url, '/static/user-icon.png') AS avatar_url,
                    COALESCE(u.bio, '') AS bio,
                    (
                        SELECT COUNT(*)
                        FROM prompts AS p
                        WHERE p.user_id = u.id
                          AND p.is_public = TRUE
                          AND p.deleted_at IS NULL
                    ) AS prompt_count
                FROM users AS u
                WHERE u.id = :user_id
                LIMIT 1
                """
            ),
            {"user_id": int(user_id)},
        )
        row = _first(result)
        if row is None or int(row.get("prompt_count") or 0) <= 0:
            return None
        row["prompt_count"] = int(row.get("prompt_count") or 0)
        return row

    async def create_prompt(
        self,
        session: AsyncSession,
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
        attachments: list[dict[str, Any]],
    ) -> int:
        """Insert a public prompt using ORM and return its generated ID."""
        username = await session.scalar(select(User.username).where(User.id == int(user_id)))
        prompt = Prompt(
            user_id=int(user_id),
            is_public=True,
            title=title,
            category=category,
            content=content,
            author=username or "ユーザー",
            input_examples=input_examples,
            output_examples=output_examples,
            ai_model=ai_model or None,
            content_format=normalize_content_format(content_format),
            media_type=normalize_media_type(media_type),
            attributes=dict(attributes or {}),
            attachments=list(attachments or []),
            description=description or None,
        )
        session.add(prompt)
        await session.flush()
        return int(prompt.id)

    async def update_prompt_for_user(
        self,
        session: AsyncSession,
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
    ) -> bool:
        """Update a live prompt owned by the actor."""
        result = await session.execute(
            select(Prompt).where(
                Prompt.id == int(prompt_id),
                Prompt.user_id == int(user_id),
                Prompt.deleted_at.is_(None),
            )
        )
        prompt = result.scalar_one_or_none()
        if prompt is None:
            return False
        prompt.title = title
        prompt.category = category
        prompt.content = content
        prompt.description = description or None
        prompt.content_format = normalize_content_format(content_format)
        prompt.media_type = normalize_media_type(media_type)
        prompt.attributes = dict(attributes or {})
        prompt.input_examples = input_examples
        prompt.output_examples = output_examples
        prompt.updated_at = func.now()
        await session.flush()
        return True

    async def delete_prompt_for_user(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        prompt_id: int,
    ) -> int:
        """Soft-delete a prompt owned by the actor."""
        result = await session.execute(
            update(Prompt)
            .where(
                Prompt.id == int(prompt_id),
                Prompt.user_id == int(user_id),
                Prompt.deleted_at.is_(None),
            )
            .values(deleted_at=func.now())
        )
        return _rowcount(result)

    async def get_active_prompt_attachments(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        prompt_id: int,
    ) -> list[dict[str, Any]]:
        """Read attachment descriptors before a prompt is soft-deleted."""
        result = await session.execute(
            select(Prompt.attachments).where(
                Prompt.id == int(prompt_id),
                Prompt.user_id == int(user_id),
                Prompt.deleted_at.is_(None),
            )
        )
        attachments = result.scalar_one_or_none()
        return [value for value in attachments if isinstance(value, dict)] if isinstance(attachments, list) else []

    async def list_my_prompts(
        self,
        session: AsyncSession,
        *,
        user_id: int,
    ) -> list[dict[str, Any]]:
        """List a user's non-deleted prompts with resource metadata."""
        result = await session.execute(
            text(
                """
                SELECT
                    p.id, p.title, p.category, p.content, p.description,
                    p.input_examples, p.output_examples, p.content_format,
                    p.media_type, p.attributes, p.attachments,
                    COALESCE(
                      (
                        SELECT jsonb_agg(
                          jsonb_build_object(
                            'id', pr.id, 'path', pr.path, 'role', pr.role,
                            'language', COALESCE(pr.language, ''),
                            'media_type', pr.media_type, 'size_bytes', pr.size_bytes,
                            'sha256', pr.sha256, 'sort_order', pr.sort_order
                          ) ORDER BY pr.sort_order, pr.id
                        ) FROM prompt_resources AS pr WHERE pr.prompt_id = p.id
                      ), '[]'::jsonb
                    ) AS resources,
                    COALESCE(
                      (
                        SELECT pr.text_content FROM prompt_resources AS pr
                        WHERE pr.prompt_id = p.id AND lower(pr.path) = 'scripts/main.py'
                        LIMIT 1
                      ), ''
                    ) AS resource_python_script,
                    p.created_at
                FROM prompts AS p
                WHERE p.user_id = :user_id AND p.deleted_at IS NULL
                ORDER BY p.created_at DESC, p.id DESC
                """
            ),
            {"user_id": int(user_id)},
        )
        return _rows(result)

    async def list_saved_prompts(
        self,
        session: AsyncSession,
        *,
        user_id: int,
    ) -> list[dict[str, Any]]:
        """List active task templates saved by a user."""
        result = await session.execute(
            select(Task)
            .where(Task.user_id == int(user_id), Task.deleted_at.is_(None))
            .order_by(Task.created_at.desc(), Task.id.desc())
        )
        return [
            {
                "id": task.id,
                "name": task.name,
                "prompt_template": task.prompt_template,
                "response_rules": task.response_rules,
                "output_skeleton": task.output_skeleton,
                "input_examples": task.input_examples,
                "output_examples": task.output_examples,
                "display_order": task.display_order,
                "created_at": task.created_at,
                "source_prompt_id": task.source_prompt_id,
            }
            for task in result.scalars().all()
        ]

    async def list_liked_prompts(
        self,
        session: AsyncSession,
        *,
        user_id: int,
    ) -> list[dict[str, Any]]:
        """List a user's likes and the currently visible prompt cards."""
        result = await session.execute(
            text(
                """
                SELECT
                    pl.id AS like_id, pl.prompt_id, p.title, p.category, p.content,
                    p.description, COALESCE(u.username, p.author, 'ユーザー') AS author,
                    p.content_format, p.media_type, p.attributes, p.attachments,
                    COALESCE(
                      (
                        SELECT jsonb_agg(
                          jsonb_build_object(
                            'id', pr.id, 'path', pr.path, 'role', pr.role,
                            'language', COALESCE(pr.language, ''),
                            'media_type', pr.media_type, 'size_bytes', pr.size_bytes,
                            'sha256', pr.sha256, 'sort_order', pr.sort_order
                          ) ORDER BY pr.sort_order, pr.id
                        ) FROM prompt_resources AS pr WHERE pr.prompt_id = p.id
                      ), '[]'::jsonb
                    ) AS resources,
                    COALESCE(
                      (
                        SELECT pr.text_content FROM prompt_resources AS pr
                        WHERE pr.prompt_id = p.id AND lower(pr.path) = 'scripts/main.py'
                        LIMIT 1
                      ), ''
                    ) AS resource_python_script,
                    p.input_examples, p.output_examples,
                    p.created_at AS prompt_created_at, pl.created_at AS liked_at
                FROM prompt_likes AS pl
                JOIN prompts AS p
                  ON p.id = pl.prompt_id AND p.is_public = TRUE AND p.deleted_at IS NULL
                LEFT JOIN users AS u ON u.id = p.user_id
                WHERE pl.user_id = :user_id
                ORDER BY pl.created_at DESC, pl.id DESC
                """
            ),
            {"user_id": int(user_id)},
        )
        return _rows(result)

    async def delete_saved_prompt(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        task_id: int,
    ) -> int:
        result = await session.execute(
            update(Task)
            .where(
                Task.id == int(task_id),
                Task.user_id == int(user_id),
                Task.deleted_at.is_(None),
            )
            .values(deleted_at=func.now())
        )
        return _rowcount(result)

    async def get_prompt_for_import(
        self,
        session: AsyncSession,
        *,
        prompt_id: int,
    ) -> dict[str, Any] | None:
        """Load the public prompt data needed by the task-import workflow."""
        result = await session.execute(
            text(
                """
                SELECT title, content, input_examples, output_examples,
                       content_format, media_type, attributes,
                       COALESCE(
                         (
                           SELECT jsonb_agg(
                             jsonb_build_object(
                               'path', pr.path, 'role', pr.role,
                               'language', COALESCE(pr.language, ''),
                               'media_type', pr.media_type,
                               'content', COALESCE(pr.text_content, ''),
                               'size_bytes', pr.size_bytes, 'sha256', pr.sha256,
                               'sort_order', pr.sort_order
                             ) ORDER BY pr.sort_order, pr.id
                           ) FROM prompt_resources AS pr WHERE pr.prompt_id = prompts.id
                         ), '[]'::jsonb
                       ) AS resources
                FROM prompts
                WHERE id = :prompt_id AND is_public = TRUE AND deleted_at IS NULL
                """
            ),
            {"prompt_id": int(prompt_id)},
        )
        return _first(result)

    async def available_imported_task_name(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        title: str,
    ) -> str:
        """Allocate a deterministic non-conflicting task title."""
        base_title = title[:255]
        candidate = base_title
        suffix_number = 1
        while True:
            result = await session.execute(
                text(
                    """
                    SELECT 1 FROM task_with_examples
                    WHERE user_id = :user_id AND deleted_at IS NULL
                      AND LOWER(BTRIM(name)) = LOWER(BTRIM(:name))
                    LIMIT 1
                    """
                ),
                {"user_id": int(user_id), "name": candidate},
            )
            if result.first() is None:
                return candidate
            suffix_number += 1
            suffix = f" ({suffix_number})"
            candidate = f"{base_title[:255 - len(suffix)]}{suffix}"

    async def add_prompt_as_task(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        prompt_id: int,
        prompt_template: str,
    ) -> tuple[dict[str, Any], int]:
        """Import a prompt into task templates under an advisory lock."""
        prompt = await self.get_prompt_for_import(session, prompt_id=prompt_id)
        if prompt is None:
            return {"error": "対象の公開プロンプトが見つかりませんでした。"}, 404
        if not prompt_template:
            return {"error": "タスクとして追加できる本文がありません。"}, 400

        await session.execute(
            text("SELECT pg_advisory_xact_lock(:user_id)"),
            {"user_id": int(user_id)},
        )
        existing = await session.execute(
            text(
                """
                SELECT id FROM task_with_examples
                WHERE user_id = :user_id AND deleted_at IS NULL
                  AND source_prompt_id = :prompt_id
                ORDER BY id ASC LIMIT 1
                """
            ),
            {"user_id": int(user_id), "prompt_id": int(prompt_id)},
        )
        existing_row = _first(existing)
        if existing_row:
            return {
                "message": "すでにチャットで使えるように追加済みです。",
                "saved_id": existing_row["id"],
                "used_in_chat": True,
            }, 200

        task_name = await self.available_imported_task_name(
            session, user_id=user_id, title=str(prompt.get("title") or "")
        )
        next_display_order = await session.scalar(
            text(
                """
                SELECT COALESCE(MAX(display_order), -1) + 1
                FROM task_with_examples
                WHERE user_id = :user_id AND deleted_at IS NULL
                """
            ),
            {"user_id": int(user_id)},
        )
        result = await session.execute(
            text(
                """
                INSERT INTO task_with_examples
                    (user_id, source_prompt_id, name, prompt_template,
                     input_examples, output_examples, display_order)
                VALUES (:user_id, :prompt_id, :name, :prompt_template,
                        :input_examples, :output_examples, :display_order)
                ON CONFLICT DO NOTHING
                RETURNING id
                """
            ),
            {
                "user_id": int(user_id),
                "prompt_id": int(prompt_id),
                "name": task_name,
                "prompt_template": prompt_template,
                "input_examples": prompt.get("input_examples") or "",
                "output_examples": prompt.get("output_examples") or "",
                "display_order": int(next_display_order or 0),
            },
        )
        saved_id = result.scalar_one_or_none()
        if saved_id is None:
            concurrent = await session.execute(
                text(
                    """
                    SELECT id FROM task_with_examples
                    WHERE user_id = :user_id AND source_prompt_id = :prompt_id
                      AND deleted_at IS NULL LIMIT 1
                    """
                ),
                {"user_id": int(user_id), "prompt_id": int(prompt_id)},
            )
            concurrent_row = _first(concurrent)
            if concurrent_row:
                return {
                    "message": "すでにチャットで使えるように追加済みです。",
                    "saved_id": concurrent_row["id"],
                    "used_in_chat": True,
                }, 200
            return {"error": "同じ名前のタスクがすでにあります。"}, 409
        return {
            "message": "チャットで使えるように追加しました。",
            "saved_id": int(saved_id),
            "used_in_chat": True,
        }, 201

    async def remove_prompt_as_task(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        prompt_id: int,
    ) -> tuple[dict[str, Any], int]:
        result = await session.execute(
            update(Task)
            .where(
                Task.user_id == int(user_id),
                Task.source_prompt_id == int(prompt_id),
                Task.deleted_at.is_(None),
            )
            .values(deleted_at=func.now())
        )
        if not _rowcount(result):
            return {"message": "チャットで使う設定はすでに解除されています。", "used_in_chat": False}, 200
        return {"message": "チャットで使う設定を解除しました。", "used_in_chat": False}, 200

    async def add_like(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        prompt_id: int,
    ) -> tuple[dict[str, Any], int]:
        prompt_exists = await session.scalar(
            select(Prompt.id).where(
                Prompt.id == int(prompt_id),
                Prompt.is_public.is_(True),
                Prompt.deleted_at.is_(None),
            )
        )
        if prompt_exists is None:
            return {"error": "対象の公開プロンプトが見つかりませんでした。"}, 404
        result = await session.execute(
            pg_insert(PromptLike)
            .values(user_id=int(user_id), prompt_id=int(prompt_id))
            .on_conflict_do_nothing(index_elements=["user_id", "prompt_id"])
            .returning(PromptLike.id)
        )
        inserted = result.scalar_one_or_none()
        if inserted is not None:
            return {"message": "いいねしました。", "liked": True}, 201
        return {"message": "すでにいいねしています。", "liked": True}, 200

    async def remove_like(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        prompt_id: int,
    ) -> int:
        result = await session.execute(
            delete(PromptLike).where(
                PromptLike.user_id == int(user_id),
                PromptLike.prompt_id == int(prompt_id),
            )
        )
        return _rowcount(result)

    async def count_visible_comments(self, session: AsyncSession, prompt_id: int) -> int:
        value = await session.scalar(
            select(func.count(PromptComment.id)).where(
                PromptComment.prompt_id == int(prompt_id),
                PromptComment.deleted_at.is_(None),
                PromptComment.hidden_by_reports_at.is_(None),
            )
        )
        return int(value or 0)

    async def list_prompt_comments(
        self,
        session: AsyncSession,
        *,
        prompt_id: int,
        limit: int,
    ) -> list[dict[str, Any]] | None:
        """Return visible comments, or None when the prompt is not public."""
        prompt_exists = await session.scalar(
            select(Prompt.id).where(
                Prompt.id == int(prompt_id),
                Prompt.is_public.is_(True),
                Prompt.deleted_at.is_(None),
            )
        )
        if prompt_exists is None:
            return None
        result = await session.execute(
            text(
                """
                SELECT pc.id, pc.prompt_id, pc.user_id,
                       COALESCE(u.username, 'ユーザー') AS author_name,
                       pc.content, pc.created_at, p.user_id AS prompt_owner_id
                FROM prompt_comments AS pc
                JOIN prompts AS p ON p.id = pc.prompt_id AND p.deleted_at IS NULL
                JOIN users AS u ON u.id = pc.user_id
                WHERE pc.prompt_id = :prompt_id
                  AND pc.deleted_at IS NULL
                  AND pc.hidden_by_reports_at IS NULL
                ORDER BY pc.created_at ASC, pc.id ASC
                LIMIT :limit
                """
            ),
            {"prompt_id": int(prompt_id), "limit": int(limit)},
        )
        return _rows(result)

    async def add_comment(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        prompt_id: int,
        content: str,
        actor_is_admin: bool,
        duplicate_window_seconds: int,
    ) -> tuple[dict[str, Any], int]:
        prompt_result = await session.execute(
            select(Prompt.id, Prompt.user_id).where(
                Prompt.id == int(prompt_id),
                Prompt.is_public.is_(True),
                Prompt.deleted_at.is_(None),
            )
        )
        prompt = prompt_result.first()
        if prompt is None:
            return {"error": "対象の公開プロンプトが見つかりませんでした。"}, 404
        duplicated = await session.scalar(
            text(
                """
                SELECT id FROM prompt_comments
                WHERE user_id = :user_id AND prompt_id = :prompt_id AND content = :content
                  AND deleted_at IS NULL
                  AND created_at >= CURRENT_TIMESTAMP - (:window * INTERVAL '1 second')
                LIMIT 1
                """
            ),
            {
                "user_id": int(user_id),
                "prompt_id": int(prompt_id),
                "content": content,
                "window": int(duplicate_window_seconds),
            },
        )
        if duplicated is not None:
            return {"error": "同じ内容のコメントは時間をおいて投稿してください。"}, 409

        result = await session.execute(
            pg_insert(PromptComment)
            .values(prompt_id=int(prompt_id), user_id=int(user_id), content=content)
            .returning(
                PromptComment.id,
                PromptComment.prompt_id,
                PromptComment.user_id,
                PromptComment.content,
                PromptComment.created_at,
            )
        )
        inserted = dict(result.mappings().one())
        username = await session.scalar(select(User.username).where(User.id == int(user_id)))
        inserted.update(
            {
                "author_name": username or "ユーザー",
                "prompt_owner_id": prompt[1],
                "actor_is_admin": actor_is_admin,
            }
        )
        inserted["comment_count"] = await self.count_visible_comments(session, prompt_id)
        return inserted, 201

    async def delete_comment(
        self,
        session: AsyncSession,
        *,
        actor_user_id: int,
        comment_id: int,
        actor_is_admin: bool,
    ) -> tuple[dict[str, Any], int]:
        result = await session.execute(
            text(
                """
                SELECT pc.id, pc.prompt_id, pc.user_id, p.user_id AS prompt_owner_id
                FROM prompt_comments AS pc
                JOIN prompts AS p ON p.id = pc.prompt_id AND p.deleted_at IS NULL
                WHERE pc.id = :comment_id AND pc.deleted_at IS NULL
                LIMIT 1
                """
            ),
            {"comment_id": int(comment_id)},
        )
        comment = _first(result)
        if comment is None:
            return {"error": "対象コメントが見つかりませんでした。"}, 404
        if not actor_is_admin and actor_user_id not in {
            comment.get("user_id"),
            comment.get("prompt_owner_id"),
        }:
            return {"error": "このコメントを削除する権限がありません。"}, 403
        await session.execute(
            update(PromptComment)
            .where(PromptComment.id == int(comment_id), PromptComment.deleted_at.is_(None))
            .values(deleted_at=func.now())
        )
        count = await self.count_visible_comments(session, int(comment["prompt_id"]))
        return {
            "prompt_id": int(comment["prompt_id"]),
            "comment_count": count,
        }, 200

    async def report_comment(
        self,
        session: AsyncSession,
        *,
        reporter_user_id: int,
        comment_id: int,
        reason: str,
        details: str | None,
        auto_hide_threshold: int,
    ) -> tuple[dict[str, Any], int]:
        result = await session.execute(
            text(
                """
                SELECT pc.id, pc.prompt_id, pc.user_id
                FROM prompt_comments AS pc
                JOIN prompts AS p ON p.id = pc.prompt_id AND p.deleted_at IS NULL
                WHERE pc.id = :comment_id
                  AND pc.deleted_at IS NULL
                  AND pc.hidden_by_reports_at IS NULL
                LIMIT 1
                """
            ),
            {"comment_id": int(comment_id)},
        )
        comment = _first(result)
        if comment is None:
            return {"error": "対象コメントが見つかりませんでした。"}, 404
        if int(comment.get("user_id") or 0) == int(reporter_user_id):
            return {"error": "自分のコメントは報告できません。"}, 400

        inserted_result = await session.execute(
            pg_insert(PromptCommentReport)
            .values(
                comment_id=int(comment_id),
                reporter_user_id=int(reporter_user_id),
                reason=reason,
                details=details or None,
            )
            .on_conflict_do_nothing(index_elements=["comment_id", "reporter_user_id"])
            .returning(PromptCommentReport.id)
        )
        inserted = inserted_result.scalar_one_or_none()
        prompt_id = int(comment["prompt_id"])
        if inserted is None:
            return {
                "already_reported": True,
                "hidden": False,
                "prompt_id": prompt_id,
                "comment_count": await self.count_visible_comments(session, prompt_id),
            }, 200

        report_count = await session.scalar(
            select(func.count(PromptCommentReport.id)).where(
                PromptCommentReport.comment_id == int(comment_id)
            )
        )
        hidden = False
        if int(report_count or 0) >= int(auto_hide_threshold):
            hide_result = await session.execute(
                update(PromptComment)
                .where(
                    PromptComment.id == int(comment_id),
                    PromptComment.hidden_by_reports_at.is_(None),
                )
                .values(hidden_by_reports_at=func.now(), hidden_reason="reported")
            )
            hidden = bool(_rowcount(hide_result))
        return {
            "prompt_id": prompt_id,
            "comment_count": await self.count_visible_comments(session, prompt_id),
            "hidden": hidden,
            "already_reported": False,
        }, 201

    async def create_guest_prompt(
        self,
        session: AsyncSession,
        *,
        cookie_hash: str,
        ip_hash: str,
        title: str,
        category: str,
        content: str,
        input_examples: str | None,
        output_examples: str | None,
        ai_model: str | None,
        description: str | None,
        lock_keys: Iterable[str],
    ) -> tuple[int | None, int | None]:
        """Enforce the guest quota and insert prompt/submission atomically.

        The return value is ``(prompt_id, retry_after)``.  A non-``None`` retry
        value means the quota was consumed recently and no insert occurred.
        """
        for lock_key in sorted(lock_keys):
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
                {"lock_key": lock_key},
            )
        retry_after = await session.scalar(
            text(
                """
                SELECT GREATEST(
                    1,
                    CEIL(EXTRACT(EPOCH FROM (
                        MAX(created_at) + INTERVAL '24 hours' - NOW()
                    )))::INTEGER
                ) AS retry_after
                FROM guest_prompt_submissions
                WHERE created_at > NOW() - INTERVAL '24 hours'
                  AND (guest_cookie_hash = :cookie_hash OR client_ip_hash = :ip_hash)
                HAVING MAX(created_at) IS NOT NULL
                """
            ),
            {"cookie_hash": cookie_hash, "ip_hash": ip_hash},
        )
        if retry_after is not None:
            return None, int(retry_after or 1)

        prompt = Prompt(
            user_id=None,
            is_public=True,
            title=title,
            category=category,
            content=content,
            author="ゲスト",
            input_examples=input_examples,
            output_examples=output_examples,
            ai_model=ai_model or None,
            content_format="prompt",
            media_type="text",
            attributes={},
            attachments=[],
            description=description or None,
        )
        session.add(prompt)
        await session.flush()
        session.add(
            GuestPromptSubmission(
                prompt_id=int(prompt.id),
                guest_cookie_hash=cookie_hash,
                client_ip_hash=ip_hash,
            )
        )
        await session.flush()
        return int(prompt.id), None

    async def claim_guest_prompts(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        cookie_hash: str,
    ) -> list[int]:
        """Claim every matching unclaimed guest prompt in one CTE."""
        result = await session.execute(
            text(
                """
                WITH claimed_prompts AS (
                    UPDATE prompts AS p
                       SET user_id = :user_id,
                           author = (
                               SELECT COALESCE(username, 'ユーザー')
                               FROM users WHERE id = :user_id
                           ),
                           updated_at = NOW()
                      FROM guest_prompt_submissions AS gps
                     WHERE gps.prompt_id = p.id
                       AND gps.guest_cookie_hash = :cookie_hash
                       AND gps.claimed_at IS NULL
                       AND p.user_id IS NULL
                    RETURNING gps.id, p.id
                )
                UPDATE guest_prompt_submissions AS gps
                   SET claimed_by_user_id = :user_id,
                       claimed_at = NOW()
                  FROM claimed_prompts AS claimed
                 WHERE gps.id = claimed.id
                RETURNING gps.prompt_id
                """
            ),
            {"user_id": int(user_id), "cookie_hash": cookie_hash},
        )
        return [int(value) for value in result.scalars().all()]
