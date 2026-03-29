import unittest
from unittest.mock import patch

from services import email_service


class FakeSMTP:
    def __init__(self, *, fail_on_starttls: bool = False, fail_on_login: bool = False):
        self.fail_on_starttls = fail_on_starttls
        self.fail_on_login = fail_on_login
        self.starttls_called = False
        self.login_args = None
        self.sent_message = None
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.closed = True
        return False

    def starttls(self):
        self.starttls_called = True
        if self.fail_on_starttls:
            raise RuntimeError("starttls failed")

    def login(self, username, password):
        self.login_args = (username, password)
        if self.fail_on_login:
            raise RuntimeError("login failed")

    def send_message(self, message):
        self.sent_message = message


class EmailServiceCredentialsTestCase(unittest.TestCase):
    def test_load_email_credentials_uses_send_password(self):
        with patch.dict(
            "os.environ",
            {"SEND_ADDRESS": "sender@example.com", "SEND_PASSWORD": "app-password"},
            clear=True,
        ):
            send_address, send_password = email_service._load_email_credentials()

        self.assertEqual(send_address, "sender@example.com")
        self.assertEqual(send_password, "app-password")

    def test_load_email_credentials_falls_back_to_legacy_env(self):
        with patch.dict(
            "os.environ",
            {
                "SEND_ADDRESS": "sender@example.com",
                "EMAIL_SEND_PASSWORD": "legacy-password",
            },
            clear=True,
        ):
            send_address, send_password = email_service._load_email_credentials()

        self.assertEqual(send_address, "sender@example.com")
        self.assertEqual(send_password, "legacy-password")

    def test_load_email_credentials_raises_when_missing(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(RuntimeError):
                email_service._load_email_credentials()

    def test_send_email_uses_context_manager_and_sends_message(self):
        fake_smtp = FakeSMTP()
        with patch.dict(
            "os.environ",
            {"SEND_ADDRESS": "sender@example.com", "SEND_PASSWORD": "app-password"},
            clear=True,
        ):
            with patch("services.email_service.smtplib.SMTP", return_value=fake_smtp):
                email_service.send_email(
                    to_address="receiver@example.com",
                    subject="subject",
                    body_text="body",
                )

        self.assertTrue(fake_smtp.starttls_called)
        self.assertEqual(fake_smtp.login_args, ("sender@example.com", "app-password"))
        self.assertEqual(fake_smtp.sent_message["To"], "receiver@example.com")
        self.assertTrue(fake_smtp.closed)

    def test_send_email_closes_connection_when_starttls_raises(self):
        fake_smtp = FakeSMTP(fail_on_starttls=True)
        with patch.dict(
            "os.environ",
            {"SEND_ADDRESS": "sender@example.com", "SEND_PASSWORD": "app-password"},
            clear=True,
        ):
            with patch("services.email_service.smtplib.SMTP", return_value=fake_smtp):
                with self.assertRaises(RuntimeError):
                    email_service.send_email(
                        to_address="receiver@example.com",
                        subject="subject",
                        body_text="body",
                    )

        self.assertTrue(fake_smtp.closed)

    def test_send_email_closes_connection_when_login_raises(self):
        fake_smtp = FakeSMTP(fail_on_login=True)
        with patch.dict(
            "os.environ",
            {"SEND_ADDRESS": "sender@example.com", "SEND_PASSWORD": "app-password"},
            clear=True,
        ):
            with patch("services.email_service.smtplib.SMTP", return_value=fake_smtp):
                with self.assertRaises(RuntimeError):
                    email_service.send_email(
                        to_address="receiver@example.com",
                        subject="subject",
                        body_text="body",
                    )

        self.assertTrue(fake_smtp.closed)


if __name__ == "__main__":
    unittest.main()
