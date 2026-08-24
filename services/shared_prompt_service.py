"""Use cases for creating public shared prompts."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from services.db import session_scope
from services.prompt_types import SKILL_PYTHON_SCRIPT_KEY
from services.repositories.prompt_resource_repository import PromptResourceRepository
from services.repositories.shared_content_repository import SharedContentRepository
from services.request_models import SharedPromptCreateRequest


async def create_shared_prompt(
    user_id: int,
    payload: SharedPromptCreateRequest,
    *,
    attachments: list[dict[str, str]] | None = None,
    resource_repository: PromptResourceRepository | None = None,
    repository: SharedContentRepository | None = None,
    session: AsyncSession | None = None,
) -> int:
    """Persist a validated public prompt in one transaction."""
    prompt_repository = repository or SharedContentRepository()
    resources = resource_repository or PromptResourceRepository()
    persisted_attributes = dict(payload.attributes or {})
    # Legacy input is normalized into resources by the request model and is not
    # duplicated into the attributes JSON of a new post.
    persisted_attributes.pop(SKILL_PYTHON_SCRIPT_KEY, None)

    async def operation(active: AsyncSession) -> int:
        prompt_id = await prompt_repository.create_prompt(
            active,
            user_id=user_id,
            title=payload.title,
            category=payload.category,
            content=payload.content,
            description=payload.description,
            content_format=payload.content_format,
            media_type=payload.media_type,
            input_examples=payload.input_examples,
            output_examples=payload.output_examples,
            ai_model=payload.ai_model,
            attributes=persisted_attributes,
            attachments=attachments or [],
        )
        await resources.insert_many(active, prompt_id, payload.resources)
        return prompt_id

    if session is None:
        async with session_scope() as owned_session:
            async with owned_session.begin():
                return await operation(owned_session)
    return await operation(session)
