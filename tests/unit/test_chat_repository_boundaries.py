"""Guards for the feature-level split of the chat persistence boundary.

Chat rooms, projects, tasks, Skills and account profile rows used to share one
repository class.  These tests fail when a method drifts back across the
boundary instead of being added to the repository that owns those rows.
"""

import unittest

from services.repositories.chat_repository import ChatRepository
from services.repositories.project_repository import ProjectRepository
from services.repositories.task_repository import TaskRepository
from services.repositories.user_repository import UserRepository
from services.repositories.user_skill_repository import UserSkillRepository


def _public_methods(repository: type) -> set[str]:
    return {name for name in vars(repository) if not name.startswith("_")}


class RepositoryOwnershipTestCase(unittest.TestCase):
    def test_each_feature_owns_its_methods(self):
        owners = {
            ProjectRepository: {"create_project", "list_projects", "get_project", "get_project_context"},
            TaskRepository: {"fetch_tasks", "add_task", "edit_task", "delete_task", "update_tasks_order"},
            UserSkillRepository: {
                "list_user_skills",
                "create_user_skill",
                "import_user_skill",
                "get_generative_ui_skill_enabled",
            },
            UserRepository: {
                "get_user_by_id",
                "update_user_profile",
                "commit_email_change",
                "update_user_preferred_locale",
            },
        }
        for repository, expected in owners.items():
            with self.subTest(repository=repository.__name__):
                self.assertTrue(expected.issubset(_public_methods(repository)))

    def test_chat_repository_no_longer_owns_other_features(self):
        chat_methods = _public_methods(ChatRepository)
        for repository in (ProjectRepository, TaskRepository, UserSkillRepository, UserRepository):
            with self.subTest(repository=repository.__name__):
                self.assertEqual(chat_methods & _public_methods(repository), set())

    def test_chat_repository_keeps_room_and_history_methods(self):
        self.assertTrue(
            {
                "save_message",
                "create_room",
                "list_user_rooms",
                "switch_branch",
                "create_or_get_shared_chat_token",
                "revoke_shared_chat_token",
                "rebuild_room_summary",
            }.issubset(_public_methods(ChatRepository))
        )

    def test_advisory_lock_namespaces_stay_distinct(self):
        from services.repositories.task_repository import TASK_WRITE_LOCK_NAMESPACE
        from services.repositories.user_skill_repository import USER_SKILL_WRITE_LOCK_NAMESPACE

        self.assertNotEqual(TASK_WRITE_LOCK_NAMESPACE, USER_SKILL_WRITE_LOCK_NAMESPACE)


if __name__ == "__main__":
    unittest.main()
