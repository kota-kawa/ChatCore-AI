"""チャットのトップに並ぶ再利用可能なプロンプトテンプレート(タスク)の永続化境界。

user_id が NULL の行は同梱の標準タスクで、system_task_key で同梱定義とユーザー行を結び付けておくと、
ユーザーが編集するまでは言語別の文面が同梱定義に追随する。

Async SQLAlchemy persistence boundary for user task templates.

Tasks are the reusable prompt templates listed on the chat top page.  Rows with
user_id IS NULL are the bundled catalog, and system_task_key links a
user row back to the bundled definition so localized copy stays in sync until
the user customizes it.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import case, func, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from services.api_errors import ApiServiceError, ResourceNotFoundError
from services.datetime_serialization import serialize_datetime_iso
from services.default_tasks import localize_system_task, resolve_system_task_key
from services.error_messages import (
    ERROR_TASK_CHANGED_ELSEWHERE,
    ERROR_TASK_NAME_CONFLICT,
    ERROR_TASK_NOT_FOUND,
    ERROR_TASK_ORDER_INVALID,
)
from services.i18n import get_current_locale
from services.models import Task
from services.share_common import is_unique_violation

# 日本語: ユーザー単位の advisory lock の名前空間。名前の重複確認と挿入/並べ替えの間に別の書き込みが入らないようにする。
# English: Advisory-lock namespace for per-user task writes, so no other write lands between the duplicate-name
# check and the insert/reorder.
TASK_WRITE_LOCK_NAMESPACE = 1_413_567_307


class TaskRepository:
    """同梱の標準タスクとユーザー所有のタスクテンプレートを扱うリポジトリ。

    commit はせず、トランザクションは Service 側が持つ(1 つの作業単位ごとに独立した AsyncSession を渡す)。

    Repository for the bundled and user-owned task templates.

    The repository never commits.  Services own the transaction and pass an
    isolated AsyncSession for one unit of work.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # タスク
    # Tasks ------------------------------------------------------------------

    # 日本語: user_id 指定でそのユーザーのタスク、None で同梱の標準タスクを、表示順(未設定は末尾)で返す。locale に合わせて文面を差し替える。
    # English: Returns the user's tasks, or the bundled catalog when user_id is None, in display order (unset
    # last), localized to the locale.
    async def fetch_tasks(self, user_id: int | None, locale: str) -> list[dict[str, Any]]:
        rows = (
            await self.session.execute(
                select(Task)
                .where(Task.user_id == user_id, Task.deleted_at.is_(None))
                .order_by(func.coalesce(Task.display_order, 99999), Task.id)
            )
        ).scalars().all()
        return [self._localize_task(task, locale, is_default=False) for task in rows]

    # 日本語: プロンプト組み立て用に 1 件を引く。task_id があればそれを、無ければ標準タスクのキー(または名前)で探し、
    # ユーザー自身のタスクが同梱のものより優先される。
    # English: Fetches one task for prompt building: by task_id when given, otherwise by system key (or name),
    # preferring the user's own task over a bundled one.
    async def get_task_prompt_data(
        self, task: str, user_id: int | None, task_id: int | None = None
    ) -> dict[str, Any] | None:
        columns = (
            Task.id.label("task_id"),
            Task.system_task_key,
            Task.system_task_revision,
            Task.is_system_task_customized,
            Task.name,
            Task.prompt_template,
            Task.response_rules,
            Task.output_skeleton,
            Task.input_examples,
            Task.output_examples,
        )
        if task_id is not None:
            stmt = select(*columns).where(Task.id == task_id, Task.user_id == user_id, Task.deleted_at.is_(None))
        else:
            key = resolve_system_task_key(task)
            lookup_column = Task.system_task_key if key is not None else Task.name
            stmt = select(*columns).where(lookup_column == (key or task), Task.deleted_at.is_(None))
            if user_id:
                stmt = stmt.where(or_(Task.user_id == user_id, Task.user_id.is_(None))).order_by(
                    case((Task.user_id == user_id, 0), else_=1), Task.id
                )
            else:
                stmt = stmt.where(Task.user_id.is_(None)).order_by(Task.id)
            stmt = stmt.limit(1)
        row = (await self.session.execute(stmt)).mappings().first()
        return localize_system_task(dict(row), get_current_locale()) if row is not None else None

    # 日本語: 並び順の更新。new_order は有効なタスク ID の全件と過不足なく一致する必要があり、ずれていれば 400(同時の追加/削除を検知する)。
    # English: Reorders tasks. new_order must match the full set of active task ids exactly, otherwise 400
    # (detects concurrent adds/deletes).
    async def update_tasks_order(self, user_id: int, new_order: list[int]) -> None:
        await self._lock_user_tasks(user_id)
        rows = (
            await self.session.execute(
                select(Task.id).where(Task.user_id == user_id, Task.deleted_at.is_(None)).with_for_update()
            )
        ).all()
        active_ids = {int(task_id) for (task_id,) in rows}
        if len(new_order) != len(active_ids) or set(new_order) != active_ids:
            raise ApiServiceError(ERROR_TASK_ORDER_INVALID, 400, code="invalid_task_order")
        for index, task_id in enumerate(new_order):
            result = await self.session.execute(
                update(Task)
                .where(Task.id == task_id, Task.user_id == user_id, Task.deleted_at.is_(None))
                .values(display_order=index, updated_at=func.current_timestamp())
            )
            if result.rowcount != 1:
                raise ApiServiceError(ERROR_TASK_ORDER_INVALID, 400, code="invalid_task_order")

    # 日本語: タスクの論理削除(deleted_at を立てる)。
    # English: Soft-deletes a task by setting deleted_at.
    async def delete_task(self, user_id: int, task_id: int) -> None:
        await self._lock_user_tasks(user_id)
        result = await self.session.execute(
            update(Task)
            .where(Task.id == task_id, Task.user_id == user_id, Task.deleted_at.is_(None))
            .values(deleted_at=func.current_timestamp(), updated_at=func.current_timestamp())
        )
        if result.rowcount != 1:
            raise ResourceNotFoundError(ERROR_TASK_NOT_FOUND, code="task_not_found")

    async def get_owned_task(self, user_id: int, task_id: int) -> dict[str, Any]:
        """ユーザー自身のタスク 1 件を全項目で読み出す。チャットのツールが編集を提案する際の基準になる。

        Read one of the user's own Tasks in full, for chat tools to propose an edit against.
        """
        task = (
            await self.session.execute(
                select(Task).where(Task.id == task_id, Task.user_id == user_id, Task.deleted_at.is_(None))
            )
        ).scalar_one_or_none()
        if task is None:
            raise ResourceNotFoundError(ERROR_TASK_NOT_FOUND, code="task_not_found")
        return self._localize_task(task, get_current_locale(), is_default=False)

    # 日本語: タスクを編集する。expected_updated_at があれば、提案時から別の場所で更新されていないか確認
    # し、変わっていれば 409(target_changed)。
    # 同名(大文字小文字・前後空白を無視)の別タスクがあれば 409。None の項目は変更せず、標準タスク由来の行は「編集済み」の印を立てる。
    # English: Edits a task. With expected_updated_at it rejects with 409 (target_changed) if the task changed
    # since the proposal, and with 409 if another
    # task has the same name (case/whitespace-insensitive). None fields are left untouched, and rows derived
    # from a bundled task are flagged as customized.
    async def edit_task(
        self,
        user_id: int,
        task_id: int,
        new_task: str,
        prompt_template: str | None,
        response_rules: str | None,
        output_skeleton: str | None,
        input_examples: str | None,
        output_examples: str | None,
        *,
        expected_updated_at: str | None = None,
    ) -> bool:
        await self._lock_user_tasks(user_id)
        task = (
            await self.session.execute(
                select(Task)
                .where(Task.id == task_id, Task.user_id == user_id, Task.deleted_at.is_(None))
                .with_for_update()
            )
        ).scalar_one_or_none()
        if task is None:
            raise ResourceNotFoundError(ERROR_TASK_NOT_FOUND, code="task_not_found")
        if expected_updated_at is not None and serialize_datetime_iso(task.updated_at) != expected_updated_at:
            raise ApiServiceError(ERROR_TASK_CHANGED_ELSEWHERE, 409, code="target_changed")
        duplicate = await self.session.scalar(
            select(Task.id)
            .where(
                Task.user_id == user_id,
                Task.id != task_id,
                Task.deleted_at.is_(None),
                func.lower(func.btrim(Task.name)) == func.lower(func.btrim(new_task)),
            )
            .limit(1)
        )
        if duplicate is not None:
            raise ApiServiceError(ERROR_TASK_NAME_CONFLICT, 409, code="task_name_conflict")
        task.name = new_task
        for field, value in (
            ("prompt_template", prompt_template),
            ("response_rules", response_rules),
            ("output_skeleton", output_skeleton),
            ("input_examples", input_examples),
            ("output_examples", output_examples),
        ):
            if value is not None:
                setattr(task, field, value)
        if task.system_task_key is not None:
            task.is_system_task_customized = True
        task.updated_at = func.current_timestamp()
        await self.session.flush()
        return True

    # 日本語: タスクを末尾に追加する。同名のタスクは 409。事前確認をすり抜けた並行追加は、一意制約違反を同じ 409 に変換する。
    # English: Appends a task. A duplicate name gives 409; a concurrent insert that slips past the pre-check
    # is mapped from the unique violation to the same 409.
    async def add_task(
        self,
        user_id: int,
        title: str,
        prompt_content: str,
        response_rules: str,
        output_skeleton: str,
        input_examples: str,
        output_examples: str,
    ) -> int:
        await self._lock_user_tasks(user_id)
        duplicate = await self.session.scalar(
            select(Task.id)
            .where(
                Task.user_id == user_id,
                Task.deleted_at.is_(None),
                func.lower(func.btrim(Task.name)) == func.lower(func.btrim(title)),
            )
            .limit(1)
        )
        if duplicate is not None:
            raise ApiServiceError(ERROR_TASK_NAME_CONFLICT, 409, code="task_name_conflict")
        next_order = await self.session.scalar(
            select(func.coalesce(func.max(Task.display_order), -1) + 1).where(
                Task.user_id == user_id, Task.deleted_at.is_(None)
            )
        )
        task = Task(
            user_id=user_id,
            name=title,
            prompt_template=prompt_content,
            response_rules=response_rules,
            output_skeleton=output_skeleton,
            input_examples=input_examples,
            output_examples=output_examples,
            display_order=int(next_order or 0),
        )
        self.session.add(task)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            if is_unique_violation(exc):
                raise ApiServiceError(ERROR_TASK_NAME_CONFLICT, 409, code="task_name_conflict") from exc
            raise
        return task.id

    # 内部ヘルパー
    # Internal helpers -------------------------------------------------------

    # 日本語: ユーザー単位のトランザクション内 advisory lock。タスクの書き込みを直列化する。
    # English: Transaction-scoped per-user advisory lock that serializes task writes.
    async def _lock_user_tasks(self, user_id: int) -> None:
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(:namespace, :user_id)").bindparams(
                namespace=TASK_WRITE_LOCK_NAMESPACE, user_id=user_id
            )
        )

    @staticmethod
    def _localize_task(task: Task, locale: str, *, is_default: bool) -> dict[str, Any]:
        return localize_system_task(
            {
                "task_id": task.id,
                "system_task_key": task.system_task_key,
                "system_task_revision": task.system_task_revision,
                "is_system_task_customized": task.is_system_task_customized,
                "name": task.name,
                # チャットツールが提案時の版として使う。既存の一覧・単体取得の両方に付ける。
                # Used by the chat tools as the proposed-against revision; added to both the
                # list and the single-task read.
                "updated_at": serialize_datetime_iso(task.updated_at),
                "prompt_template": task.prompt_template,
                "response_rules": task.response_rules,
                "output_skeleton": task.output_skeleton,
                "input_examples": task.input_examples,
                "output_examples": task.output_examples,
                "is_default": is_default,
            },
            locale,
        )
