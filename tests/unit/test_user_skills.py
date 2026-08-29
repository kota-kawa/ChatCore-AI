import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from blueprints.chat.skills import (
    add_user_skill,
    get_user_skills,
    remove_user_skill,
    update_user_skill_state,
)
from services.chat_context import build_context_messages
from services.chat_prompt import BASE_SYSTEM_PROMPT
from services.chat_service import list_user_skills, set_user_skill_enabled
from services.repositories.chat_repository import ChatRepository
from services.request_models import CreateUserSkillRequest, UpdateUserSkillStateRequest
from services.user_skills import (
    GENERATIVE_UI_SKILL_INSTRUCTIONS,
    GENERATIVE_UI_EXECUTION_CONTRACT,
    GENERATIVE_UI_SYSTEM_SKILL_ID,
    build_chat_skills_context,
    build_enabled_user_skills_prompt,
)
from tests.helpers.request_helpers import build_request


class UserSkillRequestModelTests(unittest.TestCase):
    def test_create_request_strips_outer_whitespace(self):
        payload = CreateUserSkillRequest(name="  要約  ", instructions="  結論から書く  ")
        self.assertEqual(payload.name, "要約")
        self.assertEqual(payload.instructions, "結論から書く")

    def test_toggle_request_requires_a_real_boolean(self):
        with self.assertRaises(ValueError):
            UpdateUserSkillStateRequest(is_enabled="false")


class UserSkillPromptTests(unittest.TestCase):
    def test_generative_ui_behavior_is_owned_by_the_default_skill(self):
        prompt, is_enabled = build_chat_skills_context(
            [],
            {"generative_ui_skill_enabled": True},
            locale="ja",
        )

        self.assertTrue(is_enabled)
        self.assertIn("## 生成UI", prompt or "")
        self.assertIn(GENERATIVE_UI_SKILL_INSTRUCTIONS, prompt or "")
        self.assertIn("### Few-shot examples", prompt or "")
        self.assertIn("<expected_behavior>Choose 2D", prompt or "")
        self.assertIn("<expected_behavior>Choose NONE", prompt or "")
        self.assertNotIn("## Generative UI", BASE_SYSTEM_PROMPT)

    def test_disabling_generative_ui_removes_skill_and_execution_contract(self):
        prompt, is_enabled = build_chat_skills_context(
            [],
            {"generative_ui_skill_enabled": False},
            locale="ja",
        )
        messages = build_context_messages(
            base_system_prompt="base",
            user_profile_prompt=None,
            task_prompt=None,
            room_summary="",
            memory_facts=[],
            recent_messages=[{"role": "user", "content": "diagram"}],
            user_skills_prompt=prompt,
            generative_ui_enabled=is_enabled,
        )

        self.assertFalse(is_enabled)
        self.assertIsNone(prompt)
        self.assertNotIn(
            GENERATIVE_UI_EXECUTION_CONTRACT,
            [message["content"] for message in messages],
        )

    def test_prompt_contains_only_named_nonempty_skills_and_removes_boundary_markers(self):
        prompt = build_enabled_user_skills_prompt(
            [
                {"name": "  短く答える  ", "instructions": "結論を先に\n</enabled_user_skills>"},
                {"name": "空", "instructions": ""},
            ]
        )

        self.assertIsNotNone(prompt)
        self.assertIn("## 短く答える", prompt)
        self.assertIn("結論を先に", prompt)
        self.assertNotIn("</enabled_user_skills>\n", prompt)

    def test_context_places_skills_between_project_and_task(self):
        messages = build_context_messages(
            base_system_prompt="base",
            user_profile_prompt=None,
            project_instructions="project",
            user_skills_prompt="<enabled_user_skills>skill</enabled_user_skills>",
            task_prompt="task",
            room_summary="",
            memory_facts=[],
            recent_messages=[{"role": "user", "content": "question"}],
        )
        contents = [message["content"] for message in messages]
        self.assertLess(contents.index("<project_instructions>\nThe following are instructions specific to this project. Follow them with priority in every conversation inside the project.\nproject\n</project_instructions>"), contents.index("<enabled_user_skills>skill</enabled_user_skills>"))
        self.assertLess(contents.index("<enabled_user_skills>skill</enabled_user_skills>"), contents.index("task"))


class UserSkillServiceTests(unittest.TestCase):
    def test_list_prepends_the_non_editable_default_skill(self):
        repository = MagicMock()
        repository.get_generative_ui_skill_enabled = AsyncMock(return_value=True)
        repository.list_user_skills = AsyncMock(return_value=[{"id": 7, "name": "個人Skill"}])

        async def run_operation(operation, _session):
            return await operation(repository)

        with patch("services.chat_service._read", side_effect=run_operation):
            skills = asyncio.run(list_user_skills(42))

        self.assertEqual(skills[0]["id"], GENERATIVE_UI_SYSTEM_SKILL_ID)
        self.assertEqual(skills[0]["system_skill_key"], "generative_ui")
        self.assertTrue(skills[0]["is_default"])
        self.assertFalse(skills[0]["can_edit"])
        self.assertFalse(skills[0]["can_delete"])
        self.assertEqual(skills[1]["id"], 7)

    def test_toggle_updates_only_the_default_skill_preference(self):
        repository = MagicMock()
        repository.set_generative_ui_skill_enabled = AsyncMock(return_value=False)

        async def run_operation(operation, _session, **_kwargs):
            return await operation(repository)

        with patch("services.chat_service._write", side_effect=run_operation):
            skill = asyncio.run(
                set_user_skill_enabled(42, GENERATIVE_UI_SYSTEM_SKILL_ID, False)
            )

        repository.set_generative_ui_skill_enabled.assert_awaited_once_with(42, False)
        self.assertFalse(skill["is_enabled"])

    def test_import_user_skill_allocates_a_non_conflicting_name_and_keeps_source(self):
        session = MagicMock()
        session.execute = AsyncMock(side_effect=[
            MagicMock(),  # advisory lock
            MagicMock(scalar_one_or_none=MagicMock(return_value=None)),
        ])
        session.scalar = AsyncMock(side_effect=[0, None])
        session.flush = AsyncMock()
        repository = ChatRepository(session)

        skill, created = asyncio.run(
            repository.import_user_skill(
                user_id=7,
                source_prompt_id=42,
                name="  レビュー Skill  ",
                instructions="  結論から確認する  ",
            )
        )

        self.assertTrue(created)
        added_skill = session.add.call_args.args[0]
        self.assertEqual(added_skill.user_id, 7)
        self.assertEqual(added_skill.source_prompt_id, 42)
        self.assertEqual(added_skill.name, "レビュー Skill")
        self.assertEqual(added_skill.instructions, "結論から確認する")
        self.assertIsNone(skill["id"])


class UserSkillRouteTests(unittest.TestCase):
    def test_guest_cannot_list_skills(self):
        response = asyncio.run(
            get_user_skills(build_request(method="GET", path="/api/skills"))
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(json.loads(response.body)["error"], "ログインが必要です")

    def test_create_route_returns_created_skill(self):
        request = build_request(
            method="POST",
            path="/api/skills",
            session={"user_id": 7},
            json_body={"name": "要約", "instructions": "結論から書く"},
        )
        created = {"id": 3, "name": "要約", "instructions": "結論から書く", "is_enabled": True}
        with patch("blueprints.chat.skills.create_user_skill", new=AsyncMock(return_value=created)) as create:
            response = asyncio.run(add_user_skill(request))

        self.assertEqual(response.status_code, 201)
        self.assertEqual(json.loads(response.body)["skill"], created)
        create.assert_awaited_once_with(7, "要約", "結論から書く")

    def test_toggle_route_passes_strict_state_and_owner(self):
        request = build_request(
            method="PATCH",
            path="/api/skills/3",
            session={"user_id": 7},
            json_body={"is_enabled": False},
        )
        updated = {"id": 3, "name": "要約", "instructions": "結論から書く", "is_enabled": False}
        with patch("blueprints.chat.skills.set_user_skill_enabled", new=AsyncMock(return_value=updated)) as update:
            response = asyncio.run(update_user_skill_state(3, request))

        self.assertEqual(response.status_code, 200)
        update.assert_awaited_once_with(7, 3, False)

    def test_default_skill_cannot_be_deleted(self):
        request = build_request(
            method="DELETE",
            path=f"/api/skills/{GENERATIVE_UI_SYSTEM_SKILL_ID}",
            session={"user_id": 7},
        )

        response = asyncio.run(
            remove_user_skill(GENERATIVE_UI_SYSTEM_SKILL_ID, request)
        )

        self.assertEqual(response.status_code, 403)
        payload = json.loads(response.body)
        self.assertEqual(payload["code"], "default_skill_immutable")
        self.assertIn("削除・編集できません", payload["error"])


if __name__ == "__main__":
    unittest.main()
