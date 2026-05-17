import unittest
from unittest.mock import patch

from services import email_service


class FakeResponse:
    def __init__(self, status_code=200, json_payload=None, text=""):
        self.status_code = status_code
        self._json_payload = json_payload
        self.text = text

    def json(self):
        if isinstance(self._json_payload, Exception):
            raise self._json_payload
        return self._json_payload


class EmailServiceConfigTestCase(unittest.TestCase):
    def test_load_resend_config_uses_resend_from_address(self):
        with patch.dict(
            "os.environ",
            {
                "RESEND_API_KEY": "re_test",
                "RESEND_FROM_ADDRESS": "Chat Core <noreply@example.com>",
                "SEND_ADDRESS": "legacy@example.com",
            },
            clear=True,
        ):
            api_key, from_address = email_service._load_resend_config()

        self.assertEqual(api_key, "re_test")
        self.assertEqual(from_address, "Chat Core <noreply@example.com>")

    def test_load_resend_config_falls_back_to_send_address(self):
        with patch.dict(
            "os.environ",
            {
                "RESEND_API_KEY": "re_test",
                "SEND_ADDRESS": "sender@example.com",
            },
            clear=True,
        ):
            api_key, from_address = email_service._load_resend_config()

        self.assertEqual(api_key, "re_test")
        self.assertEqual(from_address, "sender@example.com")

    def test_load_resend_config_raises_when_missing(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(RuntimeError):
                email_service._load_resend_config()

    def test_send_email_posts_plain_text_message_to_resend(self):
        fake_response = FakeResponse(status_code=200, json_payload={"id": "email-id"})
        with patch.dict(
            "os.environ",
            {
                "RESEND_API_KEY": "re_test",
                "RESEND_FROM_ADDRESS": "Chat Core <noreply@example.com>",
            },
            clear=True,
        ):
            with patch(
                "services.email_service.requests.post",
                return_value=fake_response,
            ) as mock_post:
                email_service.send_email(
                    to_address="receiver@example.com",
                    subject="subject",
                    body_text="body",
                )

        mock_post.assert_called_once_with(
            "https://api.resend.com/emails",
            headers={
                "Authorization": "Bearer re_test",
                "Content-Type": "application/json",
                "User-Agent": "Chat-Core/1.0",
            },
            json={
                "from": "Chat Core <noreply@example.com>",
                "to": ["receiver@example.com"],
                "subject": "subject",
                "text": "body",
            },
            timeout=10,
        )

    def test_send_email_does_not_call_resend_when_config_is_missing(self):
        with patch.dict("os.environ", {}, clear=True):
            with patch("services.email_service.requests.post") as mock_post:
                with self.assertRaises(RuntimeError):
                    email_service.send_email(
                        to_address="receiver@example.com",
                        subject="subject",
                        body_text="body",
                    )

        mock_post.assert_not_called()

    def test_send_email_raises_for_resend_error_message(self):
        fake_response = FakeResponse(
            status_code=403,
            json_payload={"message": "invalid api key"},
        )
        with patch.dict(
            "os.environ",
            {
                "RESEND_API_KEY": "re_test",
                "RESEND_FROM_ADDRESS": "sender@example.com",
            },
            clear=True,
        ):
            with patch(
                "services.email_service.requests.post",
                return_value=fake_response,
            ):
                with self.assertRaisesRegex(RuntimeError, "403: invalid api key"):
                    email_service.send_email(
                        to_address="receiver@example.com",
                        subject="subject",
                        body_text="body",
                    )

    def test_send_email_raises_for_resend_plain_text_error(self):
        fake_response = FakeResponse(
            status_code=500,
            json_payload=ValueError("not json"),
            text="upstream failed",
        )
        with patch.dict(
            "os.environ",
            {
                "RESEND_API_KEY": "re_test",
                "RESEND_FROM_ADDRESS": "sender@example.com",
            },
            clear=True,
        ):
            with patch(
                "services.email_service.requests.post",
                return_value=fake_response,
            ):
                with self.assertRaisesRegex(RuntimeError, "500: upstream failed"):
                    email_service.send_email(
                        to_address="receiver@example.com",
                        subject="subject",
                        body_text="body",
                    )


if __name__ == "__main__":
    unittest.main()
