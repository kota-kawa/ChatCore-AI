"""SQLAlchemy persistence for resources bundled with shared SKILL posts."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from services.models import PromptResource
from services.prompt_resources import (
    resource_sha256,
    resource_size_bytes,
    validate_resource_path,
)


class PromptResourceRepository:
    """Persist prompt resources inside the caller-owned transaction."""

    @staticmethod
    def _field(resource: object, name: str, default: str = "") -> str:
        if isinstance(resource, Mapping):
            value = resource.get(name, default)
        else:
            value = getattr(resource, name, default)
        return str(value if value is not None else default)

    async def insert_many(
        self,
        session: AsyncSession,
        prompt_id: int,
        resources: Iterable[object],
    ) -> None:
        """Insert resources without committing the caller's transaction."""
        rows = []
        for sort_order, resource in enumerate(resources):
            content = self._field(resource, "content")
            rows.append(
                PromptResource(
                    prompt_id=int(prompt_id),
                    path=validate_resource_path(self._field(resource, "path")),
                    role=self._field(resource, "role", "other"),
                    language=self._field(resource, "language", "text"),
                    media_type=self._field(resource, "media_type", "text/plain"),
                    text_content=content,
                    storage_key=None,
                    size_bytes=resource_size_bytes(content),
                    sha256=resource_sha256(content),
                    sort_order=sort_order,
                )
            )
        if rows:
            session.add_all(rows)
            await session.flush()

    async def replace_for_prompt(
        self,
        session: AsyncSession,
        prompt_id: int,
        resources: Iterable[object],
    ) -> None:
        """Atomically replace all resources using the caller's transaction."""
        await session.execute(
            delete(PromptResource).where(PromptResource.prompt_id == int(prompt_id))
        )
        await self.insert_many(session, prompt_id, resources)

    @staticmethod
    def _as_mapping(resource: PromptResource) -> dict[str, Any]:
        return {
            "id": resource.id,
            "prompt_id": resource.prompt_id,
            "path": resource.path,
            "role": resource.role,
            "language": resource.language,
            "media_type": resource.media_type,
            "content": resource.text_content,
            "text_content": resource.text_content,
            "storage_key": resource.storage_key,
            "size_bytes": resource.size_bytes,
            "sha256": resource.sha256,
            "sort_order": resource.sort_order,
            "created_at": resource.created_at,
            "updated_at": resource.updated_at,
        }

    async def list_for_prompt(
        self,
        session: AsyncSession,
        prompt_id: int,
    ) -> list[dict[str, Any]]:
        """List resources in stable package order."""
        result = await session.execute(
            select(PromptResource)
            .where(PromptResource.prompt_id == int(prompt_id))
            .order_by(PromptResource.sort_order.asc(), PromptResource.id.asc())
        )
        return [self._as_mapping(resource) for resource in result.scalars().all()]

    async def get_for_prompt(
        self,
        session: AsyncSession,
        prompt_id: int,
        path: str,
    ) -> dict[str, Any] | None:
        """Get one resource by its canonical, case-insensitive path."""
        normalized_path = validate_resource_path(path)
        result = await session.execute(
            select(PromptResource)
            .where(
                PromptResource.prompt_id == int(prompt_id),
                func.lower(PromptResource.path) == normalized_path.lower(),
            )
            .order_by(PromptResource.id.asc())
            .limit(1)
        )
        resource = result.scalar_one_or_none()
        return self._as_mapping(resource) if resource is not None else None
