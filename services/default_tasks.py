"""新規ユーザー向けの既定タスク（システムタスク）のカタログを読み込み、API 応答・DB 投入用の形に変換する。
カタログは frontend/data/ 配下の JSON（リビジョンと言語ごと）で、起動時に不足分を共通タスクとして DB へ投入する。

Loads the catalog of built-in system tasks and converts it into API payloads and DB insert rows.
The catalogs are JSON files under frontend/data/ (per revision and locale); missing ones are seeded as shared tasks at startup.
"""

import asyncio
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from services.db import is_retryable_db_error, session_scope
from services.repositories.default_seed_repository import seed_default_tasks

# 日本語: 既定タスクの JSON の場所。無印が現行リビジョン、v1 は旧リビジョン、.en は英語版。
# English: Locations of the default task JSON files; unsuffixed is the current revision, v1 is the old one, and .en is English.
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
# 日本語: 現行のシステムタスクのリビジョン。リビジョン → 言語 → JSON のパスの対応表を持ち、旧リビジョンの行も表示用に解決できる。
# English: Current system task revision, plus a revision -> locale -> JSON path map so rows from older revisions can still be resolved.
CURRENT_SYSTEM_TASK_REVISION = 2
DEFAULT_TASK_CATALOG_PATHS = {
    1: {"ja": DEFAULT_TASKS_V1_JSON, "en": DEFAULT_TASKS_V1_EN_JSON},
    CURRENT_SYSTEM_TASK_REVISION: {"ja": DEFAULT_TASKS_JSON, "en": DEFAULT_TASKS_EN_JSON},
}
DEFAULT_TASK_CATALOGS = DEFAULT_TASK_CATALOG_PATHS[CURRENT_SYSTEM_TASK_REVISION]
# 日本語: シード時の DB 書き込みを、一時的なエラーに限って再試行する回数と待ち時間の基準（秒）。
# English: Retry count and base backoff (seconds) for seed writes on transient DB errors.
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
        raise TypeError("default_tasks.json must contain a list.")

    normalized: list[dict] = []
    for index, task in enumerate(tasks):
        if not isinstance(task, dict):
            raise TypeError("Each default task must be an object.")

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
    return [
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
        for task in load_default_tasks(locale)
    ]


@lru_cache(maxsize=4)
def default_tasks_by_key(
    locale: str = "ja",
    revision: int = CURRENT_SYSTEM_TASK_REVISION,
) -> dict[str, dict[str, Any]]:
    """言語別のシステムタスクカタログを、不変のキー（system_task_key）で引ける辞書にして返す。

    Return the localized system task catalog indexed by its stable key.
    """
    return {
        str(task["system_task_key"]): task
        for task in load_default_tasks(locale, revision)
        if task.get("system_task_key")
    }


def resolve_system_task_key(identifier: Any) -> str | None:
    """不変のキー、または言語別の組み込みタスク名から、不変のキーを解決する。
    全リビジョン・全言語のカタログを順に調べ、見つからなければ None を返す。

    Resolve a stable key or a localized built-in task name to its stable key.
    Searches every revision and locale; returns None when nothing matches.
    """
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
    """既知で未編集のシステムタスクの行にだけ、指定言語の文言を上書きして返す。
    ユーザーが編集済み、キーやリビジョンが不明な行は、そのままコピーして返す。

    Overlay localized fields only when a row is a known, untouched system task.
    Customized rows and rows with an unknown key or revision are returned as an unchanged copy.
    """
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


# データベースに不足しているデフォルトタスクをインサートし、追加された件数を返す
# Seed default tasks into the database if they do not already exist, returning the insert count.
async def ensure_default_tasks_seeded() -> int:
    # 共通タスク（user_id IS NULL）に不足分のみ追加し、追加件数を返す
    # Seed only missing shared tasks (user_id IS NULL) and return inserted count.
    for attempt in range(1, DB_WRITE_MAX_ATTEMPTS + 1):
        try:
            async with session_scope() as session, session.begin():
                return await seed_default_tasks(
                    session, default_task_rows(include_key=True)
                )
        except SQLAlchemyError as exc:
            # 日本語: 一時的な PostgreSQL の障害だけ再試行する。
            # 失敗したトランザクションは、次の独立した試行の前に session_scope がロールバックする。
            # Retry only transient PostgreSQL failures. session_scope rolls back
            # the failed transaction before the next isolated attempt.
            if is_retryable_db_error(exc) and attempt < DB_WRITE_MAX_ATTEMPTS:
                await asyncio.sleep(DB_RETRY_BACKOFF_SECONDS * attempt)
                continue
            raise

    raise RuntimeError("Failed to seed default tasks after retry attempts.")
