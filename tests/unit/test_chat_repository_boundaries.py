# チャット永続化の責務が、分割した所有repositoryを越えて戻らないことを検証する。
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


# クラス自身が定義した公開メソッド名（先頭が _ でないもの）の集合を返す。継承分は含まない。
# Returns the public method names defined on the class itself (not starting with _); inherited ones are excluded.
def _public_methods(repository: type) -> set[str]:
    return {name for name in vars(repository) if not name.startswith("_")}


class RepositoryOwnershipTestCase(unittest.TestCase):
    # 各機能のリポジトリが自分の担当メソッドを持つことを確認する。
    # Each feature repository owns its own methods.
    def test_each_feature_owns_its_methods(self):
        owners = {
            ProjectRepository: {"create_project", "list_projects", "get_project", "get_project_context"},
            TaskRepository: {"fetch_tasks", "add_task", "edit_task", "delete_task", "update_tasks_order"},
            UserSkillRepository: {
                "list_user_skills",
                "create_user_skill",
                "import_user_skill",
                "get_system_skill_states",
                "set_system_skill_enabled",
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

    # ChatRepository と他リポジトリで公開メソッド名が重ならない（境界を越えて逆戻りしない）。
    # ChatRepository shares no public method names with the other repositories, so nothing drifts back across the boundary.
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

    # タスクとスキルの書き込みロックの名前空間が別であること（同じだと同一ユーザーのタスクとスキルの書き込みが互いに待ち合うため）。
    # Task and Skill write-lock namespaces must differ; otherwise one user's task and Skill writes would block each other.
    def test_advisory_lock_namespaces_stay_distinct(self):
        from services.repositories.task_repository import TASK_WRITE_LOCK_NAMESPACE
        from services.repositories.user_skill_repository import USER_SKILL_WRITE_LOCK_NAMESPACE

        self.assertNotEqual(TASK_WRITE_LOCK_NAMESPACE, USER_SKILL_WRITE_LOCK_NAMESPACE)


if __name__ == "__main__":
    unittest.main()
