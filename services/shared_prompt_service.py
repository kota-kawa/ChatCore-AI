"""Transport-independent creation of public shared prompts."""

from __future__ import annotations

import json
from typing import Any

from services.db import get_db_connection
from services.prompt_types import (
    SKILL_PYTHON_SCRIPT_KEY,
    normalize_content_format,
    normalize_media_type,
)
from services.repositories.prompt_resource_repository import PromptResourceRepository
from services.request_models import SharedPromptCreateRequest


def create_shared_prompt(
    user_id: int,
    payload: SharedPromptCreateRequest,
    *,
    attachments: list[dict[str, str]] | None = None,
    resource_repository: PromptResourceRepository | None = None,
) -> int:
    """Persist a validated public prompt on behalf of an authenticated user."""
    repository = resource_repository or PromptResourceRepository()
    persisted_attributes = dict(payload.attributes or {})
    # Legacy input is converted to resources by SharedPromptCreateRequest and is never
    # written back into the attributes JSON of a newly created post.
    persisted_attributes.pop(SKILL_PYTHON_SCRIPT_KEY, None)
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO prompts (
                    title, category, content, author, content_format, media_type,
                    attributes, attachments, input_examples, output_examples,
                    ai_model, user_id, is_public, created_at, updated_at
                )
                VALUES (
                    %s, %s, %s,
                    (SELECT COALESCE(username, 'ユーザー') FROM users WHERE id = %s),
                    %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s, TRUE, NOW(), NOW()
                )
                RETURNING id
                """,
                (
                    payload.title,
                    payload.category,
                    payload.content,
                    user_id,
                    normalize_content_format(payload.content_format),
                    normalize_media_type(payload.media_type),
                    json.dumps(persisted_attributes),
                    json.dumps(attachments or []),
                    payload.input_examples,
                    payload.output_examples,
                    payload.ai_model or None,
                    user_id,
                ),
            )
            row: tuple[Any, ...] | None = cursor.fetchone()
            if not row:
                raise RuntimeError("Shared prompt insert did not return an ID.")
            prompt_id = int(row[0])
            repository.insert_many(cursor, prompt_id, payload.resources)
            conn.commit()
            return prompt_id
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()
