"""Async SQLAlchemy persistence boundary for user Skills.

This repository owns the user_skills rows and the users.generative_ui_skill_enabled
column.  The generative UI Skill is defined in code and cannot be edited or
deleted, so only its per-user on/off state is stored, and it is kept here
because it is Skill state rather than profile state.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from services.api_errors import ApiServiceError, ResourceNotFoundError
from services.datetime_serialization import serialize_datetime_iso
from services.error_messages import (
    ERROR_SHARED_SKILL_CONTENT_MISSING,
    ERROR_SKILL_LIMIT_REACHED,
    ERROR_SKILL_NAME_CONFLICT,
    ERROR_SKILL_NOT_FOUND,
)
from services.models import User, UserSkill
from services.share_common import is_unique_violation
from services.user_skills import (
    MAX_USER_SKILL_NAME_LENGTH,
    MAX_USER_SKILLS,
    normalize_user_skill_instructions,
    normalize_user_skill_name,
)

USER_SKILL_WRITE_LOCK_NAMESPACE = 1_413_567_308
DEFAULT_IMPORTED_SKILL_NAME = "共有Skill"


class UserSkillRepository:
    """Repository for user Skills and the default Skill preference.

    The repository never commits.  Services own the transaction and pass an
    isolated AsyncSession for one unit of work.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # User skills ------------------------------------------------------------

    async def list_user_skills(self, user_id: int) -> list[dict[str, Any]]:
        skills = (
            await self.session.execute(
                select(UserSkill)
                .where(UserSkill.user_id == user_id)
                .order_by(UserSkill.created_at, UserSkill.id)
            )
        ).scalars().all()
        return [self._serialize_user_skill(skill) for skill in skills]

    async def list_enabled_user_skills(self, user_id: int) -> list[dict[str, Any]]:
        skills = (
            await self.session.execute(
                select(UserSkill)
                .where(UserSkill.user_id == user_id, UserSkill.is_enabled.is_(True))
                .order_by(UserSkill.created_at, UserSkill.id)
            )
        ).scalars().all()
        return [self._serialize_user_skill(skill) for skill in skills]

    async def create_user_skill(
        self,
        user_id: int,
        name: str,
        instructions: str,
    ) -> dict[str, Any]:
        normalized_name = normalize_user_skill_name(name)
        normalized_instructions = normalize_user_skill_instructions(instructions)
        await self._lock_user_skills(user_id)
        skill_count = await self.session.scalar(
            select(func.count(UserSkill.id)).where(UserSkill.user_id == user_id)
        )
        if int(skill_count or 0) >= MAX_USER_SKILLS:
            raise ApiServiceError(ERROR_SKILL_LIMIT_REACHED, 409, code="skill_limit_reached")

        duplicate = await self.session.scalar(
            select(UserSkill.id)
            .where(
                UserSkill.user_id == user_id,
                func.lower(func.btrim(UserSkill.name)) == func.lower(func.btrim(normalized_name)),
            )
            .limit(1)
        )
        if duplicate is not None:
            raise ApiServiceError(ERROR_SKILL_NAME_CONFLICT, 409, code="skill_name_conflict")

        skill = UserSkill(
            user_id=user_id,
            name=normalized_name,
            instructions=normalized_instructions,
            is_enabled=True,
        )
        self.session.add(skill)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            if is_unique_violation(exc):
                raise ApiServiceError(ERROR_SKILL_NAME_CONFLICT, 409, code="skill_name_conflict") from exc
            raise
        return self._serialize_user_skill(skill)

    async def import_user_skill(
        self,
        user_id: int,
        source_prompt_id: int,
        name: str,
        instructions: str,
    ) -> tuple[dict[str, Any], bool]:
        """Create or return a Skill imported from a shared prompt.

        The same per-user advisory lock as the regular Skill editor is used so
        the limit and normalized-name allocation remain atomic across both
        entry points.  ``source_prompt_id`` is deliberately nullable at the
        schema level so manually-created Skills and deleted shared prompts are
        still supported, but imported rows are identified by this value while
        their source remains public.
        """
        normalized_name = normalize_user_skill_name(name) or DEFAULT_IMPORTED_SKILL_NAME
        normalized_instructions = normalize_user_skill_instructions(instructions)
        if not normalized_instructions:
            raise ApiServiceError(ERROR_SHARED_SKILL_CONTENT_MISSING, 400, code="skill_content_missing")

        await self._lock_user_skills(user_id)
        existing = (
            await self.session.execute(
                select(UserSkill)
                .where(
                    UserSkill.user_id == int(user_id),
                    UserSkill.source_prompt_id == int(source_prompt_id),
                )
                .order_by(UserSkill.id)
                .limit(1)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return self._serialize_user_skill(existing), False

        skill_count = await self.session.scalar(
            select(func.count(UserSkill.id)).where(UserSkill.user_id == int(user_id))
        )
        if int(skill_count or 0) >= MAX_USER_SKILLS:
            raise ApiServiceError(ERROR_SKILL_LIMIT_REACHED, 409, code="skill_limit_reached")

        skill_name = await self._available_imported_skill_name(
            user_id=int(user_id),
            name=normalized_name,
        )
        skill = UserSkill(
            user_id=int(user_id),
            source_prompt_id=int(source_prompt_id),
            name=skill_name,
            instructions=normalized_instructions,
            is_enabled=True,
        )
        self.session.add(skill)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            if is_unique_violation(exc):
                raise ApiServiceError(ERROR_SKILL_NAME_CONFLICT, 409, code="skill_name_conflict") from exc
            raise
        return self._serialize_user_skill(skill), True

    async def delete_user_skill_by_source_prompt(self, user_id: int, source_prompt_id: int) -> bool:
        """Delete the Skill imported from a shared prompt, if it exists."""
        await self._lock_user_skills(user_id)
        result = await self.session.execute(
            delete(UserSkill).where(
                UserSkill.user_id == int(user_id),
                UserSkill.source_prompt_id == int(source_prompt_id),
            )
        )
        await self.session.flush()
        return bool(result.rowcount or 0)

    async def set_user_skill_enabled(
        self,
        user_id: int,
        skill_id: int,
        is_enabled: bool,
    ) -> dict[str, Any]:
        skill = await self._owned_user_skill(skill_id, user_id, lock=True)
        skill.is_enabled = is_enabled
        skill.updated_at = datetime.utcnow()
        await self.session.flush()
        return self._serialize_user_skill(skill)

    async def delete_user_skill(self, user_id: int, skill_id: int) -> None:
        skill = await self._owned_user_skill(skill_id, user_id, lock=True)
        await self.session.delete(skill)
        await self.session.flush()

    # Default generative UI Skill -------------------------------------------

    async def get_generative_ui_skill_enabled(self, user_id: int) -> bool:
        enabled = await self.session.scalar(
            select(User.generative_ui_skill_enabled).where(User.id == int(user_id))
        )
        if enabled is None:
            raise ResourceNotFoundError(ERROR_SKILL_NOT_FOUND)
        return bool(enabled)

    async def set_generative_ui_skill_enabled(
        self,
        user_id: int,
        is_enabled: bool,
    ) -> bool:
        result = await self.session.execute(
            update(User)
            .where(User.id == int(user_id))
            .values(generative_ui_skill_enabled=bool(is_enabled))
        )
        if not result.rowcount:
            raise ResourceNotFoundError(ERROR_SKILL_NOT_FOUND)
        return bool(is_enabled)

    # Internal helpers -------------------------------------------------------

    async def _owned_user_skill(self, skill_id: int, user_id: int, *, lock: bool = False) -> UserSkill:
        stmt = select(UserSkill).where(UserSkill.id == skill_id, UserSkill.user_id == user_id)
        if lock:
            stmt = stmt.with_for_update()
        skill = (await self.session.execute(stmt)).scalar_one_or_none()
        if skill is None:
            raise ResourceNotFoundError(ERROR_SKILL_NOT_FOUND, code="skill_not_found")
        return skill

    async def _lock_user_skills(self, user_id: int) -> None:
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(:namespace, :user_id)").bindparams(
                namespace=USER_SKILL_WRITE_LOCK_NAMESPACE, user_id=user_id
            )
        )

    async def _available_imported_skill_name(self, *, user_id: int, name: str) -> str:
        """Allocate a deterministic Skill name without colliding with manual Skills."""
        base_name = normalize_user_skill_name(name) or DEFAULT_IMPORTED_SKILL_NAME
        candidate = base_name
        suffix_number = 1
        while True:
            existing = await self.session.scalar(
                select(UserSkill.id)
                .where(
                    UserSkill.user_id == int(user_id),
                    func.lower(func.btrim(UserSkill.name)) == func.lower(func.btrim(candidate)),
                )
                .limit(1)
            )
            if existing is None:
                return candidate
            suffix_number += 1
            suffix = f" ({suffix_number})"
            candidate = f"{base_name[: MAX_USER_SKILL_NAME_LENGTH - len(suffix)]}{suffix}"

    @staticmethod
    def _serialize_user_skill(skill: UserSkill) -> dict[str, Any]:
        return {
            "id": skill.id,
            "system_skill_key": None,
            "name": str(skill.name or ""),
            "instructions": str(skill.instructions or ""),
            "is_enabled": bool(skill.is_enabled),
            "is_default": False,
            "can_edit": True,
            "can_delete": True,
            "created_at": serialize_datetime_iso(skill.created_at),
            "updated_at": serialize_datetime_iso(skill.updated_at),
        }
