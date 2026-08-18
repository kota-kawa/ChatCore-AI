import importlib.util
import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = (
    REPO_ROOT
    / "alembic"
    / "versions"
    / "20260809_01_use_copy_fence_in_shipped_tasks.py"
)
TASKS_PATH = REPO_ROOT / "frontend" / "data" / "default_tasks.v1.json"
UPDATED_KEYS = {"email_writing", "reply_writing"}


def _load_migration_module():
    spec = importlib.util.spec_from_file_location("copy_fence_task_migration", MIGRATION_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load copy fence task migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _shipped_tasks_by_key() -> dict[str, dict]:
    tasks = json.loads(TASKS_PATH.read_text(encoding="utf-8"))
    return {task["system_task_key"]: task for task in tasks}


class CopyFenceTaskMigrationTestCase(unittest.TestCase):
    def test_migration_follows_unique_active_tasks_revision(self):
        module = _load_migration_module()

        self.assertEqual(module.revision, "20260809_01")
        self.assertEqual(module.down_revision, "20260730_01")

    def test_migration_covers_every_task_whose_wording_changed(self):
        module = _load_migration_module()

        self.assertEqual(
            {update["system_task_key"] for update in module._TASK_TEXT_UPDATES},
            UPDATED_KEYS,
        )

    # DB を配布時の本文へ合わせるためのマイグレーションなので、"updated" 側が
    # 現在同梱している JSON と一字一句同じでなければ意味がない。
    # The migration exists to bring the database in line with the shipped wording, so the
    # "updated" side has to match the frozen revision-1 JSON character for character.
    def test_updated_wording_matches_the_shipped_tasks(self):
        module = _load_migration_module()
        shipped = _shipped_tasks_by_key()

        for update in module._TASK_TEXT_UPDATES:
            task = shipped[update["system_task_key"]]
            for field in module._UPDATED_FIELDS:
                self.assertEqual(
                    update["updated"][field],
                    task[field],
                    f"{update['system_task_key']}.{field} drifted from the shipped task",
                )

    # 変更前の本文が違っていると WHERE 句が一致せず、更新が黙って何もしない。
    # A wrong "previous" side makes the WHERE clause miss, and the update silently no-ops.
    def test_previous_wording_still_uses_the_plain_text_fence(self):
        module = _load_migration_module()

        for update in module._TASK_TEXT_UPDATES:
            self.assertIn("```text", update["previous"]["output_skeleton"])
            self.assertNotIn("```chatcore-copy", update["previous"]["output_skeleton"])
            self.assertIn("```chatcore-copy", update["updated"]["output_skeleton"])
            self.assertNotIn("```text", update["updated"]["output_skeleton"])

    # 利用者が編集した行を書き換えないことが、この移行の前提条件。
    # Leaving user-edited rows alone is the precondition of this migration.
    def test_update_only_touches_untouched_shared_rows(self):
        source = MIGRATION_PATH.read_text(encoding="utf-8")

        self.assertIn("WHERE user_id IS NULL", source)
        for field in ("prompt_template", "response_rules", "output_skeleton", "output_examples"):
            self.assertIn(f"AND {field} = :previous_{field}", source)

    def test_downgrade_restores_the_previous_wording(self):
        source = MIGRATION_PATH.read_text(encoding="utf-8")

        self.assertIn('_rewrite("previous", "updated")', source)
        self.assertIn('_rewrite("updated", "previous")', source)


if __name__ == "__main__":
    unittest.main()
