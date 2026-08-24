import asyncio
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from services.db import is_retryable_db_error, session_scope
from services.repositories.default_seed_repository import seed_default_tasks

DEFAULT_TASKS_JSON = (
    Path(__file__).resolve().parent.parent / "frontend" / "data" / "default_tasks.json"
)
DEFAULT_TASKS_EN_JSON = (
    Path(__file__).resolve().parent.parent / "frontend" / "data" / "default_tasks.en.json"
)
DEFAULT_TASKS_V1_JSON = (
    Path(__file__).resolve().parent.parent / "frontend" / "data" / "default_tasks.v1.json"
)
DEFAULT_TASKS_V1_EN_JSON = (
    Path(__file__).resolve().parent.parent / "frontend" / "data" / "default_tasks.v1.en.json"
)
CURRENT_SYSTEM_TASK_REVISION = 2
DEFAULT_TASK_CATALOG_PATHS = {
    1: {"ja": DEFAULT_TASKS_V1_JSON, "en": DEFAULT_TASKS_V1_EN_JSON},
    CURRENT_SYSTEM_TASK_REVISION: {"ja": DEFAULT_TASKS_JSON, "en": DEFAULT_TASKS_EN_JSON},
}
DEFAULT_TASK_CATALOGS = DEFAULT_TASK_CATALOG_PATHS[CURRENT_SYSTEM_TASK_REVISION]
DB_WRITE_MAX_ATTEMPTS = 3
DB_RETRY_BACKOFF_SECONDS = 0.05


# JSONファイルからデフォルトタスク定義を読み込んでキャッシュし、正規化した辞書のリストを返す
# Load, cache, and normalize default task definitions from the JSON file.
@lru_cache(maxsize=4)
def load_default_tasks(
    locale: str = "ja",
    revision: int = CURRENT_SYSTEM_TASK_REVISION,
) -> list[dict]:
    # JSON からデフォルトタスクを読み込み、型とキーを正規化する
    # Load default tasks from JSON and normalize schema/types.
    normalized_locale = str(locale or "ja").lower().replace("_", "-").split("-", 1)[0]
    revision_catalogs = DEFAULT_TASK_CATALOG_PATHS.get(revision)
    if revision_catalogs is None:
        raise ValueError(f"Unknown system task revision: {revision}")
    catalog_path = revision_catalogs.get(normalized_locale, revision_catalogs["ja"])
    with catalog_path.open(encoding="utf-8") as fp:
        tasks = json.load(fp)

    if not isinstance(tasks, list):
        raise ValueError("default_tasks.json must contain a list.")

    normalized: list[dict] = []
    for index, task in enumerate(tasks):
        if not isinstance(task, dict):
            raise ValueError("Each default task must be an object.")

        normalized.append(
            {
                "system_task_key": str(task.get("system_task_key") or f"legacy:{index}"),
                "system_task_revision": int(task.get("system_task_revision", revision)),
                "name": str(task["name"]),
                "prompt_template": str(task["prompt_template"]),
                "response_rules": str(task.get("response_rules", "")),
                "output_skeleton": str(task.get("output_skeleton", "")),
                "input_examples": str(task.get("input_examples", "")),
                "output_examples": str(task.get("output_examples", "")),
                "display_order": int(task.get("display_order", index)),
            }
        )
    return normalized


# APIレスポンス用のペイロード形式に変換したデフォルトタスクのリストを返す
# Convert and return default tasks formatted as API payloads.
def default_task_payloads(locale: str = "ja") -> list[dict]:
    # APIレスポンス向けに is_default を付与した形へ変換する
    # Build API payload objects with is_default metadata.
    payloads = []
    for task in load_default_tasks(locale):
        payloads.append(
            {
                "system_task_key": task.get("system_task_key"),
                "name": task["name"],
                "prompt_template": task["prompt_template"],
                "response_rules": task["response_rules"],
                "output_skeleton": task["output_skeleton"],
                "input_examples": task["input_examples"],
                "output_examples": task["output_examples"],
                "is_default": True,
            }
        )
    return payloads


@lru_cache(maxsize=4)
def default_tasks_by_key(
    locale: str = "ja",
    revision: int = CURRENT_SYSTEM_TASK_REVISION,
) -> dict[str, dict[str, Any]]:
    """Return the localized system task catalog indexed by its stable key."""
    return {
        str(task["system_task_key"]): task
        for task in load_default_tasks(locale, revision)
        if task.get("system_task_key")
    }


def resolve_system_task_key(identifier: Any) -> str | None:
    """Resolve a stable key or a localized built-in task name to its stable key."""
    normalized = str(identifier or "").strip()
    if not normalized:
        return None

    for revision in DEFAULT_TASK_CATALOG_PATHS:
        for locale in DEFAULT_TASK_CATALOGS:
            catalog = default_tasks_by_key(locale, revision)
            if normalized in catalog:
                return normalized
            for system_task_key, task in catalog.items():
                if normalized == task["name"]:
                    return system_task_key
    return None


def localize_system_task(
    task: dict[str, Any],
    locale: str = "ja",
) -> dict[str, Any]:
    """Overlay localized fields only when a row is a known, untouched system task."""
    if task.get("is_system_task_customized"):
        return dict(task)

    system_task_key = str(task.get("system_task_key") or "").strip()
    try:
        revision = int(
            task.get("system_task_revision") or CURRENT_SYSTEM_TASK_REVISION
        )
    except (TypeError, ValueError):
        return dict(task)

    revision_catalogs = DEFAULT_TASK_CATALOG_PATHS.get(revision)
    if revision_catalogs is None:
        return dict(task)

    localized = default_tasks_by_key(locale, revision).get(system_task_key)
    if localized is None:
        return dict(task)

    result = dict(task)
    for field in (
        "name",
        "prompt_template",
        "response_rules",
        "output_skeleton",
        "input_examples",
        "output_examples",
    ):
        result[field] = localized[field]
    result["system_task_key"] = system_task_key
    result["system_task_revision"] = revision
    return result


# データベース挿入用のタプル形式に変換したデフォルトタスクのリストを返す
# Convert and return default tasks formatted as tuples for database insertion.
def default_task_rows(locale: str = "ja", *, include_key: bool = False) -> list[tuple]:
    # DB INSERT 用のタプル配列へ変換する
    # Convert normalized tasks into DB insert row tuples.
    rows = []
    for task in load_default_tasks(locale):
        row = (
                task["name"],
                task["prompt_template"],
                task["response_rules"],
                task["output_skeleton"],
                task["input_examples"],
                task["output_examples"],
                task["display_order"],
        )
        rows.append(
            (
                task.get("system_task_key"),
                task.get("system_task_revision", CURRENT_SYSTEM_TASK_REVISION),
                *row,
            )
            if include_key
            else row
        )
    return rows


# データベース行オブジェクト（辞書またはタプル）から名前フィールドを抽出する
# Extract the name field from a database row object (which can be a dict or tuple).
def _extract_name(row: dict[str, Any] | tuple[Any, ...] | None) -> str | None:
    # dict/tuple どちらの fetch 結果でも name を取り出せるようにする
    # Extract "name" from either dict-based or tuple-based DB rows.
    if row is None:
        return None
    if isinstance(row, dict):
        return row.get("name")
    return row[0]


def _extract_system_key_and_name(
    row: dict[str, Any] | tuple[Any, ...] | None,
) -> tuple[str | None, str | None]:
    if row is None:
        return None, None
    if isinstance(row, dict):
        return row.get("system_task_key"), row.get("name")
    return row[0], row[1]


# データベースに不足しているデフォルトタスクをインサートし、追加された件数を返す
# Seed default tasks into the database if they do not already exist, returning the insert count.
async def ensure_default_tasks_seeded() -> int:
    # 共通タスク（user_id IS NULL）に不足分のみ追加し、追加件数を返す
    # Seed only missing shared tasks (user_id IS NULL) and return inserted count.
    for attempt in range(1, DB_WRITE_MAX_ATTEMPTS + 1):
        try:
            async with session_scope() as session:
                async with session.begin():
                    return await seed_default_tasks(
                        session, default_task_rows(include_key=True)
                    )
        except SQLAlchemyError as exc:
            # Retry only transient PostgreSQL failures. session_scope rolls back
            # the failed transaction before the next isolated attempt.
            if is_retryable_db_error(exc) and attempt < DB_WRITE_MAX_ATTEMPTS:
                await asyncio.sleep(DB_RETRY_BACKOFF_SECONDS * attempt)
                continue
            raise

    raise RuntimeError("Failed to seed default tasks after retry attempts.")
