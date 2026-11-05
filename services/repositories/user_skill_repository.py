"""ユーザーの Skill(user_skills)と、既定 Skill の ON/OFF 状態を永続化する境界。

ユーザー作成/共有から取り込んだ Skill の行と、既定 Skill の状態を持つ users の列
(generative_ui_skill_enabled / memo_tools_skill_enabled / prompt_tools_skill_enabled)を扱う。
既定 Skill はコードで定義され編集も削除もできないため、ユーザーごとの ON/OFF だけを保存する。
プロフィールではなく Skill の状態なので、保存先の列はここが管理する。

Async SQLAlchemy persistence boundary for user Skills.

This repository owns the user_skills rows and the users columns that hold the
built-in Skills' on/off state (generative_ui_skill_enabled, memo_tools_skill_enabled,
prompt_tools_skill_enabled).
The built-in Skills are defined in code and cannot be edited or deleted, so only
their per-user on/off state is stored, and it is kept here because it is Skill
state rather than profile state.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from services.api_errors import ApiServiceError, ResourceNotFoundError
from services.datetime_serialization import serialize_datetime_iso
from services.error_messages import (
    ERROR_SHARED_SKILL_CONTENT_MISSING,
    ERROR_SKILL_CHANGED_ELSEWHERE,
    ERROR_SKILL_LIMIT_REACHED,
    ERROR_SKILL_NAME_CONFLICT,
    ERROR_SKILL_NOT_FOUND,
)
from services.models import User, UserSkill
from services.share_common import is_unique_violation
from services.user_skills import (
    GENERATIVE_UI_SYSTEM_SKILL_KEY,
    MAX_USER_SKILL_NAME_LENGTH,
    MAX_USER_SKILLS,
    MEMO_TOOLS_SYSTEM_SKILL_KEY,
    PROMPT_TOOLS_SYSTEM_SKILL_KEY,
    normalize_user_skill_instructions,
    normalize_user_skill_name,
)

# 日本語: ユーザー単位の advisory lock の名前空間。上限確認・名前の重複確認と挿入の間に別の書き込みが入らないようにする。
# English: Advisory-lock namespace for per-user Skill writes, so no other write lands between the limit/duplicate-name
# checks and the insert.
USER_SKILL_WRITE_LOCK_NAMESPACE = 1_413_567_308
# 日本語: 共有 Skill の名前が空になったときの既定名。
# English: Fallback name when an imported Skill has no usable name.
DEFAULT_IMPORTED_SKILL_NAME = "共有Skill"
# 既定スキルの鍵と、その ON/OFF を持つ users の列。
# Built-in Skill keys and the users column holding each one's on/off state.
_SYSTEM_SKILL_COLUMNS = {
    GENERATIVE_UI_SYSTEM_SKILL_KEY: User.generative_ui_skill_enabled,
    MEMO_TOOLS_SYSTEM_SKILL_KEY: User.memo_tools_skill_enabled,
    PROMPT_TOOLS_SYSTEM_SKILL_KEY: User.prompt_tools_skill_enabled,
}


class UserSkillRepository:
    """ユーザーの Skill と、既定 Skill の ON/OFF を扱うリポジトリ。

    commit はせず、トランザクションは Service 側が持つ(1 つの作業単位ごとに独立した AsyncSession を渡す)。

    Repository for user Skills and the default Skill preference.

    The repository never commits.  Services own the transaction and pass an
    isolated AsyncSession for one unit of work.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ユーザーの Skill
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

    # 日本語: 有効(is_enabled)な Skill だけを作成順に返す。チャットの指示に反映される対象。
    # English: Returns only enabled Skills in creation order, the ones applied to chat instructions.
    async def list_enabled_user_skills(self, user_id: int) -> list[dict[str, Any]]:
        skills = (
            await self.session.execute(
                select(UserSkill)
                .where(UserSkill.user_id == user_id, UserSkill.is_enabled.is_(True))
                .order_by(UserSkill.created_at, UserSkill.id)
            )
        ).scalars().all()
        return [self._serialize_user_skill(skill) for skill in skills]

    # 日本語: Skill を作成する。上限数(MAX_USER_SKILLS)を超える場合と、同名(大文字小文字・前後空白を無視)がある場合は 409。
    # 事前確認をすり抜けた並行作成は、一意制約違反を同じ 409 に変換する。
    # English: Creates a Skill. Exceeding MAX_USER_SKILLS or reusing a name (case/whitespace-insensitive)
    # gives 409; a concurrent insert that
    # slips past the pre-check is mapped from the unique violation to the same 409.
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
        """共有プロンプトから取り込んだ Skill を作成する。すでに取り込み済みならそれを返す。

        戻り値は (Skill, 新規作成したか)。通常の Skill エディタと同じユーザー単位の advisory lock を使うので、
        2 つの入口をまたいでも上限数と正規化した名前の割り当てが原子的に保たれる。``source_prompt_id`` は手動作成の Skill や
        削除された共有プロンプトを許すためスキーマ上は NULL 可だが、取り込んだ行は元が公開されている間、この値で識別する。

        Create or return a Skill imported from a shared prompt.

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

    # 日本語: Skill の有効/無効を切り替える。行をロックして更新時刻も更新する。
    # English: Toggles a Skill on or off under a row lock and bumps its updated_at.
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

    async def get_user_skill(self, user_id: int, skill_id: int) -> dict[str, Any]:
        """ユーザー自身の Skill 1 件を全項目で読み出す。チャットのツールが編集を提案する際の基準になる。

        Read one of the user's own Skills in full, for chat tools to propose an edit against.
        """
        skill = await self._owned_user_skill(skill_id, user_id, lock=False)
        return self._serialize_user_skill(skill)

    # 名前・本文の書き換え。提案時の updated_at と食い違えば、別画面での更新を検知して失敗させる。
    # Rewrite the name and/or instructions. A mismatched ``expected_updated_at`` means the Skill
    # moved on since the proposal, so the caller fails instead of overwriting it.
    async def update_user_skill(
        self,
        user_id: int,
        skill_id: int,
        *,
        name: str | None,
        instructions: str | None,
        expected_updated_at: str | None,
    ) -> dict[str, Any]:
        await self._lock_user_skills(user_id)
        skill = await self._owned_user_skill(skill_id, user_id, lock=True)
        if expected_updated_at is not None and serialize_datetime_iso(skill.updated_at) != expected_updated_at:
            raise ApiServiceError(ERROR_SKILL_CHANGED_ELSEWHERE, 409, code="target_changed")
        if name is not None:
            normalized_name = normalize_user_skill_name(name)
            duplicate = await self.session.scalar(
                select(UserSkill.id)
                .where(
                    UserSkill.user_id == user_id,
                    UserSkill.id != skill_id,
                    func.lower(func.btrim(UserSkill.name)) == func.lower(func.btrim(normalized_name)),
                )
                .limit(1)
            )
            if duplicate is not None:
                raise ApiServiceError(ERROR_SKILL_NAME_CONFLICT, 409, code="skill_name_conflict")
            skill.name = normalized_name
        if instructions is not None:
            skill.instructions = normalize_user_skill_instructions(instructions)
        skill.updated_at = datetime.utcnow()
        try:
            await self.session.flush()
        except IntegrityError as exc:
            if is_unique_violation(exc):
                raise ApiServiceError(ERROR_SKILL_NAME_CONFLICT, 409, code="skill_name_conflict") from exc
            raise
        return self._serialize_user_skill(skill)

    # 既定の Skill
    # Built-in Skills ---------------------------------------------------------

    async def get_system_skill_states(self, user_id: int) -> dict[str, bool]:
        """1 ユーザーの既定 Skill すべての ON/OFF を、Skill のキーごとに返す。

        Return every built-in Skill's on/off state for one user, keyed by Skill key.
        """
        row = (
            await self.session.execute(
                select(*_SYSTEM_SKILL_COLUMNS.values()).where(User.id == int(user_id))
            )
        ).one_or_none()
        if row is None:
            raise ResourceNotFoundError(ERROR_SKILL_NOT_FOUND)
        return {key: bool(value) for key, value in zip(_SYSTEM_SKILL_COLUMNS, row, strict=True)}

    # 日本語: 既定 Skill の ON/OFF を、対応する users 列に書き込む。key は _SYSTEM_SKILL_COLUMNS にあるものに限る。
    # English: Writes a built-in Skill's on/off state to its users column; key must be one of _SYSTEM_SKILL_COLUMNS.
    async def set_system_skill_enabled(
        self,
        user_id: int,
        key: str,
        is_enabled: bool,
    ) -> bool:
        column = _SYSTEM_SKILL_COLUMNS[key]
        result = await self.session.execute(
            update(User)
            .where(User.id == int(user_id))
            .values({column.key: bool(is_enabled)})
        )
        if not result.rowcount:
            raise ResourceNotFoundError(ERROR_SKILL_NOT_FOUND)
        return bool(is_enabled)

    # 内部ヘルパー
    # Internal helpers -------------------------------------------------------

    # 日本語: 所有者が一致する Skill を取得し、無ければ 404。lock=True なら更新用に行ロックする。
    # English: Loads a Skill owned by the user or raises 404; lock=True takes a row lock for updates.
    async def _owned_user_skill(self, skill_id: int, user_id: int, *, lock: bool = False) -> UserSkill:
        stmt = select(UserSkill).where(UserSkill.id == skill_id, UserSkill.user_id == user_id)
        if lock:
            stmt = stmt.with_for_update()
        skill = (await self.session.execute(stmt)).scalar_one_or_none()
        if skill is None:
            raise ResourceNotFoundError(ERROR_SKILL_NOT_FOUND, code="skill_not_found")
        return skill

    # 日本語: ユーザー単位のトランザクション内 advisory lock。Skill の書き込みを直列化する。
    # English: Transaction-scoped per-user advisory lock that serializes Skill writes.
    async def _lock_user_skills(self, user_id: int) -> None:
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(:namespace, :user_id)").bindparams(
                namespace=USER_SKILL_WRITE_LOCK_NAMESPACE, user_id=user_id
            )
        )

    async def _available_imported_skill_name(self, *, user_id: int, name: str) -> str:
        """手動で作った Skill と衝突しない Skill 名を決める。重複するときは " (2)", " (3)" のように連番を付ける。

        Allocate a deterministic Skill name without colliding with manual Skills.
        """
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
