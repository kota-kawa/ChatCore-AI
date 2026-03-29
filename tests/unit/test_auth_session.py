import unittest

from services.auth_session import establish_authenticated_session
from services.session_middleware import SESSION_IDS_TO_DELETE_SCOPE_KEY
from tests.helpers.request_helpers import build_request


class AuthSessionTestCase(unittest.TestCase):
    def test_establish_authenticated_session_rotates_existing_session_id(self):
        request = build_request(path="/api/login", session={"pre_auth": "keep"})
        request.scope["session_id"] = "session-before-login"

        establish_authenticated_session(request, user_id="42", email="user@example.com")

        pending_ids = request.scope.get(SESSION_IDS_TO_DELETE_SCOPE_KEY)
        self.assertIsInstance(pending_ids, set)
        self.assertIn("session-before-login", pending_ids)
        self.assertIsNone(request.scope.get("session_id"))
        self.assertEqual(request.session["user_id"], 42)
        self.assertEqual(request.session["user_email"], "user@example.com")
        self.assertEqual(request.session["pre_auth"], "keep")
        self.assertTrue(request.session.get("_permanent"))

    def test_establish_authenticated_session_without_existing_session_id(self):
        request = build_request(path="/api/login", session={})

        establish_authenticated_session(request, user_id=7, email="user2@example.com")

        self.assertIsNone(request.scope.get("session_id"))
        self.assertNotIn(SESSION_IDS_TO_DELETE_SCOPE_KEY, request.scope)
        self.assertEqual(request.session["user_id"], 7)
        self.assertEqual(request.session["user_email"], "user2@example.com")
        self.assertTrue(request.session.get("_permanent"))


if __name__ == "__main__":
    unittest.main()
