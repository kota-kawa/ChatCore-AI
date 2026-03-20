import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from .db import get_db_connection

DEFAULT_TASKS_JSON = (
    Path(__file__).resolve().parent.parent / "frontend" / "data" / "default_tasks.json"
)


@lru_cache(maxsize=1)
def load_default_tasks() -> list[dict]:
    # JSON からデフォルトタスクを読み込み、型とキーを正規化する
    # Load default tasks from JSON and normalize schema/types.
    with DEFAULT_TASKS_JSON.open(encoding="utf-8") as fp:
        tasks = json.load(fp)

    if not isinstance(tasks, list):
        raise ValueError("default_tasks.json must contain a list.")

    normalized: list[dict] = []
    for index, task in enumerate(tasks):
        if not isinstance(task, dict):
            raise ValueError("Each default task must be an object.")

        normalized.append(
            {
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


def default_task_payloads() -> list[dict]:
    # APIレスポンス向けに is_default を付与した形へ変換する
    # Build API payload objects with is_default metadata.
    payloads = []
    for task in load_default_tasks():
        payloads.append(
            {
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


def default_task_rows() -> list[tuple]:
    # DB INSERT 用のタプル配列へ変換する
    # Convert normalized tasks into DB insert row tuples.
    rows = []
    for task in load_default_tasks():
        rows.append(
            (
                task["name"],
                task["prompt_template"],
                task["response_rules"],
                task["output_skeleton"],
                task["input_examples"],
                task["output_examples"],
                task["display_order"],
            )
        )
    return rows


def _extract_name(row: dict[str, Any] | tuple[Any, ...] | None) -> str | None:
    # dict/tuple どちらの fetch 結果でも name を取り出せるようにする
    # Extract "name" from either dict-based or tuple-based DB rows.
    if row is None:
        return None
    if isinstance(row, dict):
        return row.get("name")
    return row[0]


def ensure_default_tasks_seeded() -> int:
    # 共通タスク（user_id IS NULL）に不足分のみ追加し、追加件数を返す
    # Seed only missing shared tasks (user_id IS NULL) and return inserted count.
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT name
              FROM task_with_examples
             WHERE user_id IS NULL
            """
        )
        existing_names = {
            name
            for name in (_extract_name(row) for row in cursor.fetchall())
            if isinstance(name, str)
        }

        inserted = 0
        for (
            name,
            template,
            response_rules,
            output_skeleton,
            input_example,
            output_example,
            display_order,
        ) in default_task_rows():
            if name in existing_names:
                continue

            cursor.execute(
                """
                INSERT INTO task_with_examples
                      (
                          user_id,
                          name,
                          prompt_template,
                          response_rules,
                          output_skeleton,
                          input_examples,
                          output_examples,
                          display_order
                      )
                VALUES (NULL, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    name,
                    template,
                    response_rules,
                    output_skeleton,
                    input_example,
                    output_example,
                    display_order,
                ),
            )
            inserted += 1

        if inserted > 0:
            conn.commit()

        return inserted
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()
