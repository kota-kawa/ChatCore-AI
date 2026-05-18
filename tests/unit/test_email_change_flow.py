import asyncio
import json
import unittest
from unittest.mock import patch

from blueprints.chat.profile import (
    EMAIL_CHANGE_STAGE_CURRENT,
    EMAIL_CHANGE_STAGE_NEW,
    EMAIL_CHANGE_SESSION_KEY,
    confirm_email_change,
    request_email_change,
)
from tests.helpers.request_helpers import build_request


def make_request(path, json_body, session=None):
    return build_request(
        method="POST",
        path=path,
        json_body=json_body,
        session=session or {},
    )


class RequestEmailChangeTestCase(unittest.TestCase):
    def test_rejects_unauthenticated_requests(self):
        request = make_request(
            "/api/user/email/request_change",
            {"new_email": "new@example.com"},
        )
        response = asyncio.run(request_email_change(request))
        self.assertEqual(response.status_code, 401)

    def test_rejects_email_matching_current_address(self):
        session = {"user_id": 1, "csrf_token": "x"}
        request = make_request(
            "/api/user/email/request_change",
            {"new_email": "alice@example.com"},
            session=session,
        )
        with patch(
            "blueprints.chat.profile.get_user_by_id",
            return_value={"id": 1, "email": "alice@example.com"},
        ):
            response = asyncio.run(request_email_change(request))
        self.assertEqual(response.status_code, 400)
        self.assertIn("同じ", json.loads(response.body.decode("utf-8"))["error"])

    def test_rejects_email_owned_by_another_user(self):
        session = {"user_id": 1}
        request = make_request(
            "/api/user/email/request_change",
            {"new_email": "claimed@example.com"},
            session=session,
        )
        with (
            patch(
                "blueprints.chat.profile.get_user_by_id",
                return_value={"id": 1, "email": "alice@example.com"},
            ),
            patch(
                "blueprints.chat.profile.get_user_by_email",
                return_value={"id": 2, "email": "claimed@example.com"},
            ),
        ):
            response = asyncio.run(request_email_change(request))
        self.assertEqual(response.status_code, 400)
        self.assertIn(
            "利用できません",
            json.loads(response.body.decode("utf-8"))["error"],
        )

    def test_rejects_malformed_email(self):
        session = {"user_id": 1}
        request = make_request(
            "/api/user/email/request_change",
            {"new_email": "not-an-email"},
            session=session,
        )
        response = asyncio.run(request_email_change(request))
        self.assertEqual(response.status_code, 400)

    def test_rejects_email_with_newline_injection(self):
        session = {"user_id": 1}
        request = make_request(
            "/api/user/email/request_change",
            {"new_email": "victim@example.com\nBcc: attacker@evil.test"},
            session=session,
        )
        response = asyncio.run(request_email_change(request))
        self.assertEqual(response.status_code, 400)

    def test_stores_code_and_new_email_in_session_on_success(self):
        session = {"user_id": 1}
        request = make_request(
            "/api/user/email/request_change",
            {"new_email": "new@example.com"},
            session=session,
        )
        with (
            patch(
                "blueprints.chat.profile.get_user_by_id",
                return_value={"id": 1, "email": "alice@example.com"},
            ),
            patch(
                "blueprints.chat.profile.get_user_by_email",
                return_value=None,
            ),
            patch(
                "blueprints.chat.profile.consume_auth_email_send_limits",
                return_value=(True, None),
            ),
            patch(
                "blueprints.chat.profile.consume_auth_email_daily_quota",
                return_value=(True, 49, 50),
            ),
            patch(
                "blueprints.chat.profile.generate_verification_code",
                return_value="424242",
            ),
            patch("blueprints.chat.profile.send_email") as mock_send,
            patch("blueprints.chat.profile.time.time", return_value=1000),
        ):
            response = asyncio.run(request_email_change(request))

        self.assertEqual(response.status_code, 200)
        state = session.get(EMAIL_CHANGE_SESSION_KEY)
        self.assertEqual(state["stage"], EMAIL_CHANGE_STAGE_CURRENT)
        self.assertEqual(state["code"], "424242")
        self.assertEqual(state["current_email"], "alice@example.com")
        self.assertEqual(state["new_email"], "new@example.com")
        self.assertEqual(state["issued_at"], 1000)
        self.assertEqual(state["attempts"], 0)
        # The first verification mail must be sent to the current address.
        mock_send.assert_called_once()
        kwargs = mock_send.call_args.kwargs
        self.assertEqual(kwargs["to_address"], "alice@example.com")


class ConfirmEmailChangeTestCase(unittest.TestCase):
    def _session_with_state(self, **overrides):
        state = {
            "stage": EMAIL_CHANGE_STAGE_NEW,
            "code": "424242",
            "current_email": "alice@example.com",
            "new_email": "new@example.com",
            "issued_at": 1000,
            "attempts": 0,
        }
        state.update(overrides)
        return {"user_id": 1, EMAIL_CHANGE_SESSION_KEY: state}

    def test_rejects_when_no_pending_request(self):
        request = make_request(
            "/api/user/email/confirm_change",
            {"auth_code": "424242"},
            session={"user_id": 1},
        )
        response = asyncio.run(confirm_email_change(request))
        self.assertEqual(response.status_code, 400)

    def test_expired_code_is_cleared(self):
        session = self._session_with_state()
        request = make_request(
            "/api/user/email/confirm_change",
            {"auth_code": "424242"},
            session=session,
        )
        with patch("blueprints.chat.profile.time.time", return_value=99999):
            response = asyncio.run(confirm_email_change(request))
        self.assertEqual(response.status_code, 400)
        self.assertNotIn(EMAIL_CHANGE_SESSION_KEY, session)

    def test_wrong_code_increments_attempts(self):
        session = self._session_with_state()
        request = make_request(
            "/api/user/email/confirm_change",
            {"auth_code": "000000"},
            session=session,
        )
        with patch("blueprints.chat.profile.time.time", return_value=1001):
            response = asyncio.run(confirm_email_change(request))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(session[EMAIL_CHANGE_SESSION_KEY]["attempts"], 1)

    def test_too_many_failures_clears_session(self):
        session = self._session_with_state(attempts=4)
        request = make_request(
            "/api/user/email/confirm_change",
            {"auth_code": "000000"},
            session=session,
        )
        with patch("blueprints.chat.profile.time.time", return_value=1001):
            response = asyncio.run(confirm_email_change(request))
        self.assertEqual(response.status_code, 429)
        self.assertNotIn(EMAIL_CHANGE_SESSION_KEY, session)

    def test_current_email_confirmation_sends_code_to_new_address(self):
        session = self._session_with_state(stage=EMAIL_CHANGE_STAGE_CURRENT)
        request = make_request(
            "/api/user/email/confirm_change",
            {"auth_code": "424242"},
            session=session,
        )
        with (
            patch("blueprints.chat.profile.time.time", return_value=1001),
            patch(
                "blueprints.chat.profile.generate_verification_code",
                return_value="858585",
            ),
            patch(
                "blueprints.chat.profile.consume_auth_email_send_limits",
                return_value=(True, None),
            ),
            patch(
                "blueprints.chat.profile.consume_auth_email_daily_quota",
                return_value=(True, 49, 50),
            ),
            patch("blueprints.chat.profile.send_email") as mock_send,
            patch(
                "blueprints.chat.profile._commit_email_change",
                return_value=True,
            ) as mock_commit,
        ):
            response = asyncio.run(confirm_email_change(request))

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["stage"], EMAIL_CHANGE_STAGE_NEW)
        state = session[EMAIL_CHANGE_SESSION_KEY]
        self.assertEqual(state["stage"], EMAIL_CHANGE_STAGE_NEW)
        self.assertEqual(state["code"], "858585")
        self.assertEqual(state["issued_at"], 1001)
        self.assertEqual(state["attempts"], 0)
        mock_send.assert_called_once()
        self.assertEqual(mock_send.call_args.kwargs["to_address"], "new@example.com")
        mock_commit.assert_not_called()

    def test_success_commits_change_and_updates_session_email(self):
        session = self._session_with_state()
        request = make_request(
            "/api/user/email/confirm_change",
            {"auth_code": "424242"},
            session=session,
        )
        with (
            patch("blueprints.chat.profile.time.time", return_value=1001),
            patch(
                "blueprints.chat.profile._commit_email_change",
                return_value=True,
            ) as mock_commit,
        ):
            response = asyncio.run(confirm_email_change(request))
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["email"], "new@example.com")
        self.assertNotIn(EMAIL_CHANGE_SESSION_KEY, session)
        self.assertEqual(session["user_email"], "new@example.com")
        mock_commit.assert_called_once_with(1, "new@example.com")

    def test_email_taken_between_request_and_confirm_returns_409(self):
        session = self._session_with_state()
        request = make_request(
            "/api/user/email/confirm_change",
            {"auth_code": "424242"},
            session=session,
        )
        with (
            patch("blueprints.chat.profile.time.time", return_value=1001),
            patch(
                "blueprints.chat.profile._commit_email_change",
                return_value=False,
            ),
        ):
            response = asyncio.run(confirm_email_change(request))
        self.assertEqual(response.status_code, 409)


class ProfileEndpointRefusesEmailChangeTestCase(unittest.TestCase):
    def test_profile_post_with_different_email_returns_400(self):
        from blueprints.chat.profile import user_profile

        scope = {
            "type": "http",
            "asgi": {"spec_version": "2.3", "version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/api/user/profile",
            "raw_path": b"/api/user/profile",
            "query_string": b"",
            "headers": [
                (
                    b"content-type",
                    b"multipart/form-data; boundary=----testboundary",
                ),
            ],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
            "session": {"user_id": 1},
        }

        boundary = b"----testboundary"
        body = (
            b"--" + boundary + b"\r\n"
            b'Content-Disposition: form-data; name="username"\r\n\r\n'
            b"alice\r\n"
            b"--" + boundary + b"\r\n"
            b'Content-Disposition: form-data; name="email"\r\n\r\n'
            b"attacker@example.com\r\n"
            b"--" + boundary + b"\r\n"
            b'Content-Disposition: form-data; name="bio"\r\n\r\n'
            b"hello\r\n"
            b"--" + boundary + b"\r\n"
            b'Content-Disposition: form-data; name="llm_profile_context"\r\n\r\n'
            b"\r\n"
            b"--" + boundary + b"--\r\n"
        )

        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}

        from starlette.requests import Request
        request = Request(scope, receive)

        with patch(
            "blueprints.chat.profile.get_user_by_id",
            return_value={"id": 1, "email": "alice@example.com"},
        ):
            response = asyncio.run(user_profile(request))

        self.assertEqual(response.status_code, 400)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertIn("メールアドレス", payload["error"])


if __name__ == "__main__":
    unittest.main()
