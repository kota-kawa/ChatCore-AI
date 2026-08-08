import importlib.util
import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = (
    REPO_ROOT
    / "alembic"
    / "versions"
    / "20260728_02_add_system_task_provenance.py"
)
TASKS_PATH = REPO_ROOT / "frontend" / "data" / "default_tasks.json"


def _load_migration_module():
    spec = importlib.util.spec_from_file_location("system_task_migration", MIGRATION_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load system-task migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SystemTaskProvenanceMigrationTestCase(unittest.TestCase):
    def test_migration_follows_locale_preference_revision(self):
        module = _load_migration_module()

        self.assertEqual(module.revision, "20260728_02")
        self.assertEqual(module.down_revision, "20260728_01")

    # 凍結された fingerprint は「マイグレーション作成時点の本文」のスナップショットで、
    # 既存 DB の行を照合するためのもの。既定タスクの文面を後から変えても、DB に残る
    # 行は古い文面のままなので、スナップショットを作り直してはいけない（照合が壊れる）。
    # そのため現在の JSON との一致ではなく、全 system_task_key が照合先を持つことを見る。
    # The frozen fingerprints snapshot the wording as of the migration, and exist to match
    # rows already in the database. Later edits to the shipped tasks must not regenerate
    # them: the stored rows still hold the old wording, so a regenerated snapshot would
    # stop matching. Assert key coverage rather than identity with the current JSON.
    def test_every_shipped_task_key_has_a_frozen_fingerprint(self):
        module = _load_migration_module()
        tasks = json.loads(TASKS_PATH.read_text(encoding="utf-8"))

        self.assertEqual(
            set(module._SYSTEM_TASK_KEY_BY_FINGERPRINT.values()),
            {task["system_task_key"] for task in tasks},
        )
        self.assertEqual(
            len(module._SYSTEM_TASK_KEY_BY_FINGERPRINT),
            len(set(module._SYSTEM_TASK_KEY_BY_FINGERPRINT.values())),
            "each system task key must resolve from exactly one frozen fingerprint",
        )

    def test_customized_task_does_not_match_frozen_fingerprint(self):
        module = _load_migration_module()
        task = json.loads(TASKS_PATH.read_text(encoding="utf-8"))[0]
        task["prompt_template"] += " customized"

        self.assertNotIn(
            module._fingerprint(task),
            module._SYSTEM_TASK_KEY_BY_FINGERPRINT,
        )


if __name__ == "__main__":
    unittest.main()
