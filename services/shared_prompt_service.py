"""公開プロンプトを新規作成するユースケース。

Use cases for creating public shared prompts.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from services.db import session_scope
from services.prompt_embedding_service import schedule_prompt_embedding
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
    """検証済みの公開プロンプトを 1 トランザクションで保存し、リクエスト外で埋め込みを作る。

    呼び出し側が session を渡した場合、埋め込みの予約はその呼び出し側のコミット前に行われる。
    ワーカーが先に動くと行が見つからず、プロンプトは ``pending`` のまま残り、後続のバックフィルが拾う。

    Persist a validated public prompt in one transaction, then embed it off-request.

    With a caller-supplied session the embedding is scheduled before that caller commits;
    if the worker runs first it finds no row, the prompt stays ``pending``, and the
    backfill picks it up.
    """
    prompt_repository = repository or SharedContentRepository()
    resources = resource_repository or PromptResourceRepository()
    persisted_attributes = dict(payload.attributes or {})
    # 日本語: 旧形式の入力はリクエストモデルが resources に正規化済みなので、新しい投稿の attributes JSON には重複して残さない。
    # English: Legacy input is normalized into resources by the request model and is not
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
        async with session_scope() as owned_session, owned_session.begin():
            prompt_id = await operation(owned_session)
    else:
        prompt_id = await operation(session)
    schedule_prompt_embedding(prompt_id)
    return prompt_id
