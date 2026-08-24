import asyncio
import json
import unittest
from unittest.mock import patch

from blueprints.prompt_share.prompt_share_api import create_prompt
from services.guest_prompt_service import GuestPromptLimitExceeded
from tests.helpers.request_helpers import build_request


def make_request(payload, session=None):
    return build_request(
        method="POST",
        path="/prompt_share/api/prompts",
        json_body=payload,
        session=session,
    )


class GuestPromptPostingTestCase(unittest.TestCase):
    @staticmethod
    def _payload(**overrides):
        payload = {
            "title": "紹介文を作る",
            "description": "製品紹介文を作るためのプロンプト",
            "category": "",
            "content": "次の製品の紹介文を簡潔に書いてください。",
            "content_format": "prompt",
            "media_type": "text",
            "input_examples": "製品名: ChatCore",
            "output_examples": "ChatCore は…",
            "ai_model": "ChatGPT",
            "attributes": {},
            "resources": [],
        }
        payload.update(overrides)
        return payload

    def test_guest_can_create_text_prompt_and_receives_no_identifier(self):
        request = make_request(self._payload(), session={})

        with patch(
            "blueprints.prompt_share.prompt_share_api.create_guest_shared_prompt",
            return_value=44,
        ) as create_guest:
            with patch(
                "blueprints.prompt_share.prompt_share_api.get_request_client_ip",
                return_value="203.0.113.10",
            ):
                response = asyncio.run(create_prompt(request))

        self.assertEqual(response.status_code, 201)
        response_payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(response_payload["prompt_id"], 44)
        self.assertTrue(response_payload["is_guest"])
        self.assertNotIn("guest_token", response_payload)
        self.assertIn("guest_prompt_token", request.session)
        create_guest.assert_called_once()
        self.assertEqual(create_guest.call_args.args[1], "203.0.113.10")
        self.assertEqual(create_guest.call_args.args[2].description, "製品紹介文を作るためのプロンプト")

    def test_guest_rejects_url_in_every_free_text_field(self):
        for field in ("title", "description", "content", "input_examples", "output_examples", "ai_model"):
            with self.subTest(field=field):
                request = make_request(self._payload(**{field: "See https://example.test/path"}), session={})
                with patch("blueprints.prompt_share.prompt_share_api.create_guest_shared_prompt") as create_guest:
                    response = asyncio.run(create_prompt(request))

                self.assertEqual(response.status_code, 400)
                self.assertIn("URL", json.loads(response.body.decode("utf-8"))["error"])
                create_guest.assert_not_called()

    def test_guest_rejects_image_skill_resources_and_attributes(self):
        invalid_payloads = (
            self._payload(media_type="image"),
            self._payload(content_format="skill", content="", attributes={"skill_markdown": "# Skill"}),
            self._payload(resources=[{"path": "notes.txt"}]),
            self._payload(attributes={"unexpected": "value"}),
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                request = make_request(payload, session={})
                with patch("blueprints.prompt_share.prompt_share_api.create_guest_shared_prompt") as create_guest:
                    response = asyncio.run(create_prompt(request))

                self.assertEqual(response.status_code, 400)
                create_guest.assert_not_called()

    def test_guest_limit_returns_retry_after(self):
        request = make_request(self._payload(), session={})
        with patch(
            "blueprints.prompt_share.prompt_share_api.create_guest_shared_prompt",
            side_effect=GuestPromptLimitExceeded(123),
        ):
            response = asyncio.run(create_prompt(request))

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers["Retry-After"], "123")

    def test_logged_in_skill_post_keeps_existing_persistence_path(self):
        request = make_request(
            self._payload(
                content_format="skill",
                content="",
                attributes={"skill_markdown": "# Skill"},
                resources=[
                    {
                        "path": "scripts/main.py",
                        "role": "script",
                        "language": "python",
                        "content": "print('ok')",
                    }
                ],
            ),
            session={"user_id": 9},
        )
        with patch(
            "blueprints.prompt_share.prompt_share_api._create_prompt_for_user",
            return_value=55,
        ) as create_for_user:
            response = asyncio.run(create_prompt(request))

        self.assertEqual(response.status_code, 201)
        self.assertFalse(json.loads(response.body.decode("utf-8"))["is_guest"])
        self.assertEqual(create_for_user.call_args.args[0], 9)
        self.assertEqual(create_for_user.call_args.args[-2][0]["path"], "scripts/main.py")


if __name__ == "__main__":
    unittest.main()
