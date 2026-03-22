import asyncio
import json
import unittest
from unittest.mock import patch

from blueprints.auth import api_current_user
from tests.helpers.request_helpers import build_request


def make_request(session=None):
    return build_request(method="GET", path="/api/current_user", session=session)


class CurrentUserTestCase(unittest.TestCase):
    def test_current_user_logged_out(self):
        request = make_request()
        response = asyncio.run(api_current_user(request))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.body.decode()), {"logged_in": False})

    def test_current_user_logged_in(self):
        request = make_request(session={"user_id": 7})
        with patch("blueprints.auth.get_user_by_id") as mock_get_user:
            mock_get_user.return_value = {
                "id": 7,
                "email": "user@example.com",
                "username": "kota",
            }
            response = asyncio.run(api_current_user(request))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            json.loads(response.body.decode()),
            {
                "logged_in": True,
                "user": {"id": 7, "email": "user@example.com", "username": "kota"},
            },
        )


if __name__ == "__main__":
    unittest.main()
