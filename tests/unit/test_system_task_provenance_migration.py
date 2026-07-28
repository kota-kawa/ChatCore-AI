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

    def test_all_current_japanese_defaults_have_frozen_fingerprint(self):
        module = _load_migration_module()
        tasks = json.loads(TASKS_PATH.read_text(encoding="utf-8"))

        resolved_keys = {
            module._SYSTEM_TASK_KEY_BY_FINGERPRINT[module._fingerprint(task)]
            for task in tasks
        }
        self.assertEqual(resolved_keys, {task["system_task_key"] for task in tasks})

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
