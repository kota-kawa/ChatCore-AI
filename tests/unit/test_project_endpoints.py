import asyncio
import json
import unittest
from unittest.mock import patch

from blueprints.chat.projects import (
    create_project_endpoint,
    delete_project_endpoint,
    list_projects_endpoint,
    assign_room_project_endpoint,
)
from services.api_errors import ForbiddenOperationError
from tests.helpers.request_helpers import build_request


class ProjectEndpointsTestCase(unittest.TestCase):
    def test_create_project_requires_login(self):
        request = build_request(
            method="POST",
            path="/api/projects",
            json_body={"name": "P"},
            session={},
        )
        response = asyncio.run(create_project_endpoint(request))
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(response.status_code, 401)
        self.assertIn("error", payload)

    def test_create_project_returns_created_project(self):
        request = build_request(
            method="POST",
            path="/api/projects",
            json_body={"name": "リサーチ", "instructions": "丁寧に"},
            session={"user_id": 7},
        )
        created = {"id": 3, "name": "リサーチ", "instructions": "丁寧に"}
        with patch("blueprints.chat.projects.create_project", return_value=created) as create_mock:
            response = asyncio.run(create_project_endpoint(request))

        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(response.status_code, 201)
        self.assertEqual(payload["project"], created)
        create_mock.assert_called_once_with(7, "リサーチ", "丁寧に")

    def test_list_projects_returns_projects(self):
        request = build_request(method="GET", path="/api/projects", session={"user_id": 7})
        projects = [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}]
        with patch("blueprints.chat.projects.list_projects", return_value=projects):
            response = asyncio.run(list_projects_endpoint(request))

        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["projects"], projects)

    def test_delete_project_propagates_forbidden(self):
        request = build_request(
            method="POST",
            path="/api/delete_project",
            json_body={"project_id": 5},
            session={"user_id": 7},
        )
        with patch(
            "blueprints.chat.projects.delete_project",
            side_effect=ForbiddenOperationError("他ユーザーのプロジェクトは操作できません"),
        ):
            response = asyncio.run(delete_project_endpoint(request))

        self.assertEqual(response.status_code, 403)

    def test_assign_room_project_unassign(self):
        request = build_request(
            method="POST",
            path="/api/assign_room_project",
            json_body={"room_id": "room-1", "project_id": None},
            session={"user_id": 7},
        )
        with patch("blueprints.chat.projects.assign_room_to_project") as assign_mock:
            response = asyncio.run(assign_room_project_endpoint(request))

        self.assertEqual(response.status_code, 200)
        assign_mock.assert_called_once_with("room-1", 7, None)


if __name__ == "__main__":
    unittest.main()
